"""
MOD 完整导出器 — 一键生成完整可用的 HOI4 MOD
参考 KR（Kaiserreich）的文件结构
"""
import os
import struct
import numpy as np

from data.constants import (
    MAP_WIDTH, MAP_HEIGHT,
    TILE_LAND, TILE_SEA, TILE_LAKE,
    OCEAN_HEIGHT, LAND_BASE_HEIGHT, SEA_LEVEL,
    DEFAULT_MOD_NAME,
)
from data.terrain_types import TERRAIN_PALETTE_INDEX, DEFAULT_TERRAIN_FOR_TILE
from domain.generators.province import generate_province_colors
from export.bmp_writer import (
    write_provinces_bmp, write_heightmap_bmp,
    write_terrain_bmp, write_rivers_bmp,
)


def export_full_mod(
    tile_map: np.ndarray,
    province_map: np.ndarray,
    output_dir: str,
    mod_name: str = DEFAULT_MOD_NAME,
    tag: str = "AAA",
    state_mgr=None,
    country_mgr=None,
    river_map: np.ndarray | None = None,
    terrain_map: np.ndarray | None = None,
    height_map: np.ndarray | None = None,
    continent_mgr=None,
    adjacency_mgr=None,
    railway_mgr=None,
    supply_mgr=None,
    colormap_settings=None,
    default_map_settings=None,
    adjacency_rule_mgr=None,
    strategic_region_mgr=None,
    provincial_terrain: dict[int, str] | None = None,
    scope: dict[str, bool] | None = None,
    assets: dict[str, bytes] | None = None,
    dirty_assets: set[str] | None = None,
) -> None:
    """一键导出完整 MOD。scope 控制导出范围，None=全部导出。

    assets/dirty_assets: 美术资产系统。导入的 MOD 原始美术文件保存在 assets 中，
    未被编辑触发 dirty 的资产在导出时直接写回原字节（保留原美术）。
    """
    if assets is None:
        assets = {}
    if dirty_assets is None:
        dirty_assets = set()
    if int(province_map.max()) == 0:
        raise ValueError("没有省份数据，请先生成省份")

    # 防御性刷新全局尺寸：用户可能加载了非默认尺寸项目但没触发 set_map_size,
    # 或某些 writer 在文件顶部 import MAP_* 已绑定旧值（lazy import 的会刷新）
    from data.constants import set_map_size as _set_map_size
    _set_map_size(province_map.shape[1], province_map.shape[0])

    # scope 默认全部开启
    if scope is None:
        scope = {}
    def _enabled(key: str) -> bool:
        return scope.get(key, True)

    # 清理 < 8 像素的碎屑省份，合并到最大相邻省份（只改导出副本）。
    # 必须在压实之前做：碎屑被吞掉本身会产生新的 ID 空洞
    province_map = _merge_tiny_provinces(province_map, min_pixels=8)

    # 压实省份 ID（可选，导入 MOD 时建议关闭以保留原 ID）。
    # 只作用于导出副本：province_map 上一步已是拷贝，引用省份 ID 的
    # manager 深拷贝后再重编号——项目本体（含撤销历史）不受影响。
    # 即使 ID 已连续也要跑：mapping 同时清掉指向已删省份的死引用
    if _enabled("compact_ids"):
        import copy as _copy
        state_mgr = _copy.deepcopy(state_mgr)
        country_mgr = _copy.deepcopy(country_mgr)
        strategic_region_mgr = _copy.deepcopy(strategic_region_mgr)
        continent_mgr = _copy.deepcopy(continent_mgr)
        adjacency_mgr = _copy.deepcopy(adjacency_mgr)
        railway_mgr = _copy.deepcopy(railway_mgr)
        supply_mgr = _copy.deepcopy(supply_mgr)
        adjacency_rule_mgr = _copy.deepcopy(adjacency_rule_mgr)
        from domain.map_data import MapData as _MD
        _tmp = _MD.__new__(_MD)
        _tmp.province_map = province_map
        _tmp.tile_map = tile_map
        _tmp.provincial_terrain = dict(provincial_terrain) if provincial_terrain else {}
        _tmp.compact_with_references(
            state_mgr=state_mgr, country_mgr=country_mgr,
            strategic_region_mgr=strategic_region_mgr,
            continent_mgr=continent_mgr, adjacency_mgr=adjacency_mgr,
            railway_mgr=railway_mgr, supply_mgr=supply_mgr,
            adjacency_rule_mgr=adjacency_rule_mgr,
        )
        provincial_terrain = _tmp.provincial_terrain
    province_count = int(province_map.max())

    colors = generate_province_colors(province_count)

    # 向量化分类省份（陆地 / 海洋 / 湖泊），避免逐省份全图扫描
    land_ids, sea_ids, lake_ids = _classify_provinces_fast(
        province_count, province_map, tile_map
    )

    # === 同步 tile_map 到 province 分类 ===
    # _classify_provinces_fast 按"像素多数表决"分类 province，必然有少量像素
    # tile ≠ province type（例：60% LAND+40% SEA 的 province 被归为 land，但那
    # 40% SEA 像素在 tile_map 里还是 SEA）。若不同步：
    #   - buildings writer 坐标验证用 tile_map，找不到 LAND 像素 → 写错坐标
    #   - HOI4 判 coastal 看 provinces.bmp + type，和 tile_map 判定分歧
    # 同步后保证：tile_map[y,x] 类型 = pid_map[y,x] 所属 province 的 type
    _sync_tile_with_province_class(tile_map, province_map, land_ids, sea_ids, lake_ids)

    # === BMP 文件 ===
    write_provinces_bmp(province_map, output_dir, colors)

    # 高度图：优先用用户编辑的，否则自动生成
    if height_map is not None and int(height_map.max()) != int(height_map.min()):
        heightmap = height_map
    else:
        heightmap = _gen_heightmap(tile_map)
    write_heightmap_bmp(heightmap, output_dir)

    # 地形图：优先用用户编辑的，否则自动生成
    if terrain_map is not None and int(terrain_map.max()) > 0:
        write_terrain_bmp(terrain_map, output_dir)
    else:
        write_terrain_bmp(_gen_terrain(tile_map), output_dir)

    write_rivers_bmp(output_dir, river_map, shape=tile_map.shape)
    # trees.bmp: 从 terrain_map 自动生成树木分布 (A8)
    from export.writers.map.trees_bmp import (
        write_trees_bmp as _write_trees_new,
        auto_generate_tree_map,
    )
    _tm_for_trees = terrain_map if terrain_map is not None else _gen_terrain(tile_map)
    _tree_map = auto_generate_tree_map(_tm_for_trees)
    _write_trees_new(output_dir, tree_map=_tree_map)
    # cities.bmp: 从 urban terrain 生成城市标记 (Feature 11)
    from export.writers.map.cities_bmp import write_cities_bmp as _write_cities_new
    _write_cities_new(output_dir, terrain_map=terrain_map)
    # world_normal.bmp — 法线贴图，可被导入的原版本替代
    from export.asset_helper import write_or_restore
    write_or_restore(
        "map/world_normal.bmp", output_dir, assets, dirty_assets,
        lambda: _write_normal_map(heightmap, output_dir),
    )

    # colormap_rgb_cityemissivemask_a.dds 战略视角总览贴图
    # (不覆盖会看到 vanilla 地球大陆)
    from export.writers.map.colormap_dds import write_colormap_dds
    write_or_restore(
        "map/terrain/colormap_rgb_cityemissivemask_a.dds",
        output_dir, assets, dirty_assets,
        lambda: write_colormap_dds(tile_map, output_dir, settings=colormap_settings,
                                   terrain_map=terrain_map, height_map=heightmap),
    )

    # colormap_water_0/1/2.dds 海洋着色贴图 — 三个 MIP 都视作一组
    from export.writers.map.colormap_dds import write_water_colormap_dds

    def _gen_water_colormap():
        write_water_colormap_dds(tile_map, output_dir)

    # 只要有一个 MIP 是 clean 就用整组原字节；否则重新生成三个
    water_paths = [
        "map/terrain/colormap_water_0.dds",
        "map/terrain/colormap_water_1.dds",
        "map/terrain/colormap_water_2.dds",
    ]
    all_water_clean = all(
        p in assets and p not in dirty_assets for p in water_paths
    )
    if all_water_clean:
        for p in water_paths:
            write_or_restore(p, output_dir, assets, dirty_assets, lambda: None)
    else:
        _gen_water_colormap()

    # ambient_object.txt — 地图边框 (frame_border_top/bottom 挡住上下空白)
    from export.writers.map.ambient_object import write_ambient_object_txt
    write_ambient_object_txt(output_dir)

    # seasons.txt — 季节视觉定义（必须有，否则崩溃）
    _write_seasons_txt(output_dir)

    # default.map 引擎配置文件 (A3, 用户可通过菜单调整 tree palette / river_max_level)
    from export.writers.map.default_map import write_default_map
    write_default_map(
        output_dir,
        settings=default_map_settings,
        province_count=int(province_map.max()),
    )

    # === 同步 terrain_map 与 tile_map ===
    # 用户可能扩张/缩小陆地后没重新生成地形，导致 terrain_map 与 tile_map 不一致。
    # 修正：陆地上的 ocean 地形→plains，海洋上的陆地地形→ocean
    # （与 gen_from_project.py 相同的修正逻辑）
    if terrain_map is not None:
        _sync_terrain_with_tile(terrain_map, tile_map)

    # === 一次性计算海岸线（definition.csv + buildings.txt 共享）===
    # **省级邻接**判定 — 和 HOI4 完全一致（按 definition.csv 的 type 字段判）
    # 不能用 tile_map 像素级判定，因为 _classify_provinces_fast 按像素多数表决
    # 分类，与 tile_map 像素级邻接不等价 → HOI4 判 coastal 但 buildings.txt 没
    # 写 port → "Province X coastal but no port" → start_game 崩溃
    coastal_set, land_to_sea = _compute_coastal_once(province_map, land_ids, sea_ids)

    # definition.csv 延后到 states 构建完成后写（coastal 必须与 buildings 对齐）
    _write_continent(output_dir, continent_mgr=continent_mgr)
    # Adjacencies: 有用户数据用新 writer, 否则写仅含 header+sentinel
    if adjacency_mgr is not None and adjacency_mgr.count() > 0:
        from export.writers.map.adjacencies import write_adjacencies_csv
        write_adjacencies_csv(output_dir, adjacency_mgr=adjacency_mgr)
    else:
        _write_adjacencies(output_dir)

    # adjacency_rules.txt (A6, 海峡通行规则)
    from export.writers.map.adjacency_rules import write_adjacency_rules_txt
    write_adjacency_rules_txt(output_dir, rule_mgr=adjacency_rule_mgr)

    # === 预计算质心（一次性，供后续所有 writer 共用）===
    flat_pm_g = province_map.ravel()
    n_g = province_count + 1
    pid_count_g = np.bincount(flat_pm_g, minlength=n_g)
    h_g, w_g = province_map.shape
    ys_g, xs_g = np.mgrid[0:h_g, 0:w_g]
    sum_y_g = np.bincount(flat_pm_g, weights=ys_g.ravel().astype(np.float64), minlength=n_g)
    sum_x_g = np.bincount(flat_pm_g, weights=xs_g.ravel().astype(np.float64), minlength=n_g)
    del ys_g, xs_g  # 释放 ~175MB

    # === 先 finalize states + 孤儿 land 省份补领养 ===
    # HOI4 要求每个 land province 都属于一个 state，否则 MAP_ERROR "land province has no state"
    land_id_set = set(land_ids)
    if state_mgr and state_mgr.states:
        states = {}
        for sid, s in state_mgr.states.items():
            land_provs = [p for p in s.provinces if p in land_id_set]
            if land_provs:
                states[sid] = land_provs

        # 孤儿领养：把 _classify_provinces_fast 视为 land 但没在任何 state 的省份
        # 分配到地理上最近的 state
        all_in_states = set()
        for provs in states.values():
            all_in_states.update(provs)
        orphans = [p for p in land_ids if p not in all_in_states]
        if orphans:
            state_centers = {}
            for sid, provs in states.items():
                tx = ty = tw = 0.0
                for p in provs:
                    if p < n_g and pid_count_g[p] > 0:
                        tx += sum_x_g[p]; ty += sum_y_g[p]; tw += pid_count_g[p]
                if tw > 0:
                    state_centers[sid] = (ty / tw, tx / tw)
            for orphan in orphans:
                if orphan >= n_g or pid_count_g[orphan] == 0:
                    continue
                ocy = sum_y_g[orphan] / pid_count_g[orphan]
                ocx = sum_x_g[orphan] / pid_count_g[orphan]
                best_sid = min(
                    state_centers,
                    key=lambda s: (state_centers[s][0]-ocy)**2 + (state_centers[s][1]-ocx)**2,
                )
                states[best_sid].append(orphan)
                if state_mgr.get_state(best_sid):
                    state_mgr.get_state(best_sid).provinces.append(orphan)
            print(f"  [orphan adoption] 领养了 {len(orphans)} 个孤儿陆地省份")
    else:
        states = None  # 稍后用 region 拆 state

    # === 过滤 coastal：只保留确实在 states 里的省份 ===
    # buildings.txt 只为 pid_to_state 里的 coastal 省份写 naval_base_spawn，
    # definition.csv 的 coastal 必须与之完全对齐，否则 HOI4 崩溃：
    # "Province X is setup as coastal but has no port building"
    if states is not None:
        all_state_pids = set()
        for provs in states.values():
            all_state_pids.update(provs)
        # **孤儿 coastal 陆地省份转为海** — HOI4 的 coastal 判定靠 CSV 里
        # land-adjacent-to-sea, 所以这些没 state 的陆地省份必须变海, 不然
        # HOI4 会把它们识别为 coastal 但 buildings.txt 没港口 → 崩溃
        orphan_coastal = {p for p in coastal_set if p not in all_state_pids}
        if orphan_coastal:
            land_ids = [p for p in land_ids if p not in orphan_coastal]
            sea_ids = sorted(set(sea_ids) | orphan_coastal)
            coastal_set -= orphan_coastal
            print(f"  [coastal] 转换 {len(orphan_coastal)} 个无 state 的 coastal 省份为 sea 类型")
        land_to_sea = {p: s for p, s in land_to_sea.items() if p in coastal_set}

    # definition.csv 延后到 buildings 之后写（需要 buildings 的坐标验证结果）

    # === 战略区域 ===
    region_list = None
    if _enabled("strategic_regions"):
        if strategic_region_mgr is not None and strategic_region_mgr.count() > 0:
            from export.writers.map.strategic_regions import (
                write_strategic_regions_from_mgr, write_weatherpositions,
            )
            region_list = write_strategic_regions_from_mgr(strategic_region_mgr, output_dir)
            write_weatherpositions(region_list, province_map, output_dir)
        else:
            region_list = _write_strategic_regions(
                province_map, tile_map, output_dir, states_dict=states
            )
            _write_weatherpositions(region_list, province_map, output_dir)

    # === 写 state 文件 ===
    if _enabled("states"):
        if state_mgr and state_mgr.states:
            _write_states_from_mgr(state_mgr, country_mgr, province_map, output_dir, tile_map,
                                   land_id_set=land_id_set, coastal_set=coastal_set)
        else:
            if region_list is not None:
                states = _split_states_by_region(region_list, set(land_ids))
            if states is not None:
                _write_states(states, tag, province_map, output_dir)

    # === 补给系统 ===
    if _enabled("supply") and states is not None:
        if supply_mgr is not None and supply_mgr.count() > 0:
            from export.writers.map.supply_nodes import write_supply_nodes_txt
            write_supply_nodes_txt(output_dir, supply_mgr=supply_mgr)
        else:
            _write_supply_nodes(states, province_map, output_dir)

        if railway_mgr is not None and railway_mgr.count() > 0:
            from export.writers.map.railways import write_railways_txt
            write_railways_txt(output_dir, railway_mgr=railway_mgr, province_map=province_map)
        else:
            _write_railways(states, province_map, output_dir)
        _write_supply_areas(states, output_dir)

    # === map 文件（BMP 已写，这里写剩余的 map 配置）===
    if _enabled("map"):
        failed_coastal = _write_buildings(states, province_map, tile_map, output_dir, sea_ids,
                         land_to_sea=land_to_sea,
                         pid_count=pid_count_g, sum_x=sum_x_g, sum_y=sum_y_g)
        if failed_coastal:
            # 这些坐标不可靠的 coastal 省份必须从 CSV 的 land 改成 sea,
            # 否则 HOI4 会重新检测出 coastal 但 buildings.txt 没 port → 崩溃
            coastal_set -= failed_coastal
            land_ids = [p for p in land_ids if p not in failed_coastal]
            sea_ids = sorted(set(sea_ids) | failed_coastal)
            print(f"  [coastal] 转换 {len(failed_coastal)} 个坐标不可靠的 coastal 省份为 sea 类型")

        _write_definition_csv(province_count, colors, province_map, tile_map, output_dir,
                              land_ids, sea_ids, lake_ids, continent_mgr=continent_mgr,
                              terrain_map=terrain_map,
                              provincial_terrain=provincial_terrain,
                              coastal_set=coastal_set)
        _write_empty_unitstacks(output_dir)
        _write_positions(province_map, tile_map, output_dir,
                         pid_count=pid_count_g, sum_x=sum_x_g, sum_y=sum_y_g)

    # === 国家 ===
    if _enabled("countries"):
        if country_mgr and country_mgr.countries:
            _write_countries_from_mgr(country_mgr, output_dir, states)
        else:
            first_state_id = min(states.keys()) if states else 1
            _write_country(tag, first_state_id, output_dir)

    # === 国旗 ===
    if _enabled("gfx"):
        all_tags = list(country_mgr.countries.keys()) if country_mgr and country_mgr.countries else [tag]
        _write_country_flags(all_tags, output_dir, country_mgr)

    # === 本地化 ===
    if _enabled("localisation"):
        region_count = len(region_list) if region_list else 24
        _write_localisation_full(mod_name, state_mgr, country_mgr, states, output_dir,
                                 region_count=region_count,
                                 region_mgr=strategic_region_mgr)

    # === Bookmark ===
    if _enabled("countries"):
        country_tags = list(country_mgr.countries.keys()) if country_mgr and country_mgr.countries else [tag]
        _write_bookmark(mod_name, country_tags, output_dir)

    # === NDefines 覆盖（防止 AI 除零崩溃）===
    from export.writers.common.defines import write_defines_lua
    write_defines_lua(output_dir, province_count=province_count)

    # === descriptor (独立开关 — 已有自己 MOD 框架的用户可关掉, 只取内容文件) ===
    if _enabled("descriptor"):
        _write_descriptor(mod_name, output_dir)

    # === replace_path 清洗目录 + tutorial 屏蔽 ===
    if _enabled("replace_path"):
        from export.writers.replace_path.scrubber import write_replace_path_dirs
        write_replace_path_dirs(output_dir)

        # tutorial 屏蔽（属于 replace_path 范畴）
        tut_dir = os.path.join(output_dir, "tutorial")
        os.makedirs(tut_dir, exist_ok=True)
        with open(os.path.join(tut_dir, "tutorial.txt"), "w", encoding="utf-8") as f:
            f.write("tutorial = { }\n")

    # === 导出后校验（只检查已启用模块的文件）===
    if _enabled("map"):
        _verify_non_empty(output_dir, scope)


def _verify_non_empty(output_dir, scope=None):
    """校验关键文件存在且非空。只检查已启用模块的文件。"""
    _s = scope or {}
    def _on(key): return _s.get(key, True)

    critical_files = [
        "map/definition.csv",
        "map/provinces.bmp",
        "map/heightmap.bmp",
        "map/terrain.bmp",
        "map/rivers.bmp",
        "map/trees.bmp",
        "map/continent.txt",
        "map/buildings.txt",
    ]
    if _on("supply"):
        critical_files += ["map/supply_nodes.txt", "map/railways.txt"]
    missing = []
    for rel in critical_files:
        p = os.path.join(output_dir, rel)
        if not os.path.isfile(p) or os.path.getsize(p) == 0:
            missing.append(rel)
    if missing:
        raise RuntimeError(
            "MOD 导出后校验失败：下列关键文件缺失或为空（会导致 HOI4 崩溃）：\n  - "
            + "\n  - ".join(missing)
        )

    # 至少一个 strategicregion 和一个 state
    sr_dir = os.path.join(output_dir, "map", "strategicregions")
    if not os.path.isdir(sr_dir) or not any(
        f.endswith(".txt") for f in os.listdir(sr_dir)
    ):
        raise RuntimeError("map/strategicregions/ 为空 — 至少需要一个战略区域")
    st_dir = os.path.join(output_dir, "history", "states")
    if not os.path.isdir(st_dir) or not any(
        f.endswith(".txt") for f in os.listdir(st_dir)
    ):
        raise RuntimeError("history/states/ 为空 — 至少需要一个 State")


def _compute_coastal_province_level(province_map, land_ids, sea_ids):
    """用省份级邻接计算 coastal land province 集合（与 HOI4 内部一致）。
    任何 land province 只要在像素图上与某个 sea province 像素相邻，即为 coastal。
    """
    n = int(province_map.max()) + 1
    is_land = np.zeros(n, dtype=bool)
    is_sea = np.zeros(n, dtype=bool)
    for lp in land_ids:
        if lp < n:
            is_land[int(lp)] = True
    for sp in sea_ids:
        if sp < n:
            is_sea[int(sp)] = True

    coastal = set()
    # 水平邻接
    left = province_map[:, :-1].ravel()
    right = province_map[:, 1:].ravel()
    m1 = is_land[left] & is_sea[right]
    m2 = is_sea[left] & is_land[right]
    if m1.any():
        coastal.update(int(x) for x in np.unique(left[m1]))
    if m2.any():
        coastal.update(int(x) for x in np.unique(right[m2]))
    # 垂直邻接
    up = province_map[:-1, :].ravel()
    down = province_map[1:, :].ravel()
    m3 = is_land[up] & is_sea[down]
    m4 = is_sea[up] & is_land[down]
    if m3.any():
        coastal.update(int(x) for x in np.unique(up[m3]))
    if m4.any():
        coastal.update(int(x) for x in np.unique(down[m4]))
    return coastal


def _compute_coastal_once(province_map, land_ids, sea_ids):
    """一次性计算海岸线数据，返回 (coastal_set, land_to_sea)。
    coastal_set: 沿海陆地省份 ID 集合
    land_to_sea: {land_pid: sea_pid} 每个沿海陆地省份对应的一个相邻海洋省份
    供 definition.csv (coastal 字段) 和 buildings.txt (naval_base_spawn) 共享。
    """
    n = int(province_map.max()) + 1
    is_land = np.zeros(n, dtype=bool)
    is_sea = np.zeros(n, dtype=bool)
    for lp in land_ids:
        if lp < n:
            is_land[int(lp)] = True
    for sp in sea_ids:
        if sp < n:
            is_sea[int(sp)] = True

    coastal_set: set[int] = set()
    land_to_sea: dict[int, int] = {}

    def _scan_dir(land_pm, sea_pm):
        """扫描一个方向的 land-sea 邻接，纯 numpy 无 Python 循环。"""
        land_arr = land_pm.ravel()
        sea_arr = sea_pm.ravel()
        m = is_land[land_arr] & is_sea[sea_arr]
        if not m.any():
            return
        lp_hits = land_arr[m]
        sp_hits = sea_arr[m]
        # 用 unique 只取每个 land_pid 的第一个 sea_pid
        _, first_idx = np.unique(lp_hits, return_index=True)
        for i in first_idx:
            lp = int(lp_hits[i])
            coastal_set.add(lp)
            if lp not in land_to_sea:
                land_to_sea[lp] = int(sp_hits[i])

    # 4 个方向
    _scan_dir(province_map[:, :-1], province_map[:, 1:])   # 右
    _scan_dir(province_map[:, 1:], province_map[:, :-1])   # 左
    _scan_dir(province_map[:-1, :], province_map[1:, :])   # 下
    _scan_dir(province_map[1:, :], province_map[:-1, :])   # 上

    return coastal_set, land_to_sea


# ────────────────── definition.csv ──────────────────

def _write_definition_csv(count, colors, pm, tm, output_dir,
                          land_ids=None, sea_ids=None, lake_ids=None,
                          continent_mgr=None, terrain_map=None,
                          provincial_terrain=None,
                          coastal_set=None):
    """写 definition.csv。"""
    d = os.path.join(output_dir, "map")
    os.makedirs(d, exist_ok=True)

    # 预建类型查找表
    type_map = {}
    if land_ids is not None and sea_ids is not None and lake_ids is not None:
        for pid in land_ids:
            type_map[pid] = "land"
        for pid in sea_ids:
            type_map[pid] = "sea"
        for pid in lake_ids:
            type_map[pid] = "lake"

    if coastal_set is None:
        coastal_set = set()

    # 批量预计算所有省份的主要地形类型（一次 pass，不逐省份扫描）
    dominant_terrain = _batch_resolve_terrain(
        count, pm, terrain_map, provincial_terrain)

    with open(os.path.join(d, "definition.csv"), "w", encoding="utf-8") as f:
        f.write("0;0;0;0;sea;false;ocean;0\n")
        for pid in range(1, count + 1):
            r, g, b = colors.get(pid, (1, 1, 1))
            ptype = type_map.get(pid, "sea")
            if ptype == "land":
                terrain = dominant_terrain[pid]
                if continent_mgr is not None:
                    cont = continent_mgr.get_province_continent_hoi4_id(pid, True)
                    if cont <= 0:
                        cont = 1
                else:
                    cont = 1
                coastal = "true" if pid in coastal_set else "false"
            elif ptype == "lake":
                terrain = "lakes"
                cont = 0
                coastal = "false"
            else:
                terrain = "ocean"
                cont = 0
                coastal = "false"
            f.write(f"{pid};{r};{g};{b};{ptype};{coastal};{terrain};{cont}\n")


def _batch_resolve_terrain(province_count, province_map, terrain_map,
                           provincial_terrain=None):
    """批量计算所有省份的主要地形类型。
    返回 list，索引=省份ID，值=地形字符串。
    一次 np.add.at pass，替代之前的逐省份全图扫描。"""
    from data.terrain_types import PALETTE_TO_TYPE

    result = ["plains"] * (province_count + 1)

    # 显式设定的优先
    if provincial_terrain:
        for pid, ttype in provincial_terrain.items():
            if pid <= province_count:
                result[pid] = ttype

    if terrain_map is None:
        return result

    # 单次 pass 计算 (province_id, terrain_index) 的像素数直方图
    flat_pid = province_map.ravel()
    flat_ter = terrain_map.ravel()
    n_ter = int(terrain_map.max()) + 1
    n_pid = province_count + 1

    # 编码为 pid * n_ter + ter_idx，一次 bincount
    combined = flat_pid.astype(np.int64) * n_ter + flat_ter.astype(np.int64)
    hist = np.bincount(combined, minlength=n_pid * n_ter).reshape(n_pid, n_ter)

    # 每个省份取出现最多的地形索引
    dominant_idx = hist.argmax(axis=1)  # shape (n_pid,)

    for pid in range(1, n_pid):
        # 跳过已由 provincial_terrain 设定的
        if provincial_terrain and pid in provincial_terrain:
            continue
        if hist[pid].sum() == 0:
            continue
        result[pid] = PALETTE_TO_TYPE.get(int(dominant_idx[pid]), "plains")

    return result


# 注意：不再生成 default.map — 用原版的（EaW 验证做法）
# 我们的 BMP/CSV 文件会按文件名自动覆盖原版对应文件


# ────────────────── continent.txt ──────────────────

def _write_continent(output_dir, continent_mgr=None):
    d = os.path.join(output_dir, "map")
    os.makedirs(d, exist_ok=True)
    # vanilla 的 portraits / 国家文件 / 部分 modifier 硬编码引用这 7 个大陆名,
    # MOD 不写就会触发 "unknown continent" → portraitdatabase 空 bucket → 除零崩溃.
    # 即使用户自定义大陆, 也必须把 vanilla 名字保留, 否则 vanilla 资源加载就崩.
    VANILLA_CONTINENTS = [
        "europe", "north_america", "south_america",
        "australia", "africa", "asia", "middle_east",
    ]
    user_names = list(continent_mgr.names) if continent_mgr is not None and continent_mgr.count() > 0 else []
    # 合并并去重, vanilla 7 个先写以保证它们的 ID (1..7) 与 vanilla 一致
    seen = set()
    names = []
    for n in VANILLA_CONTINENTS + user_names:
        if n not in seen:
            seen.add(n)
            names.append(n)
    with open(os.path.join(d, "continent.txt"), "w", encoding="utf-8") as f:
        f.write("continents = {\n")
        for n in names:
            f.write(f"\t{n}\n")
        f.write("}\n")


# ────────────────── adjacencies ──────────────────

def _write_adjacencies(output_dir):
    d = os.path.join(output_dir, "map")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "adjacencies.csv"), "w", encoding="utf-8") as f:
        f.write("From;To;Type;Through;start_x;start_y;stop_x;stop_y;adjacency_rule_name;Comment\n")
        # vanilla 末行格式：-1;-1;;-1;-1;-1;-1;-1;-1
        f.write("-1;-1;;-1;-1;-1;-1;-1;-1\n")


def _write_seasons_txt(output_dir):
    """写 map/seasons.txt — 季节视觉（颜色/树叶变化）。用 vanilla 默认值。"""
    d = os.path.join(output_dir, "map")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "seasons.txt"), "w", encoding="utf-8") as f:
        f.write("""winter = {
\tstart_date=00.12.01
\tend_date=00.02.10
\thsv_north= { 0 0.1 1 }
\tcolorbalance_north= { 0.9 0.9 1 }
\thsv_center= { 0.0 1.0 1.0 }
\tcolorbalance_center= { 1.0 1.0 1.0 }
\thsv_south= { 0.0 1.0 1.0 }
\tcolorbalance_south= { 1.0 1.0 1.0 }
}
spring = {
\tstart_date=00.03.10
\tend_date=00.04.22
\thsv_north= { 0 0.1 1 }
\tcolorbalance_north= { 0.9 0.9 1 }
\thsv_center= { 0.0 1.0 1.0 }
\tcolorbalance_center= { 1.0 1.0 1.0 }
\thsv_south= { 0.0 1.0 1.0 }
\tcolorbalance_south= { 1.0 1.0 1.0 }
}
summer = {
\tstart_date=00.05.20
\tend_date=00.09.10
\thsv_north= { 0 0.1 1 }
\tcolorbalance_north= { 0.9 0.9 1 }
\thsv_center= { 0.0 1.0 1.0 }
\tcolorbalance_center= { 1.0 1.0 1.0 }
\thsv_south= { 0.0 1.0 1.0 }
\tcolorbalance_south= { 1.0 1.0 1.0 }
}
autumn = {
\tstart_date=00.10.10
\tend_date=00.10.31
\thsv_north= { 0 0.1 1 }
\tcolorbalance_north= { 0.9 0.9 1 }
\thsv_center= { 0.0 1.0 1.0 }
\tcolorbalance_center= { 1.0 1.0 1.0 }
\thsv_south= { 0.0 1.0 1.0 }
\tcolorbalance_south= { 1.0 1.0 1.0 }
}
tree_winter = { start_date=00.11.15 end_date=00.12.01 }
tree_winter2 = { start_date=00.12.20 end_date=00.01.20 }
tree_spring = { start_date=00.02.20 end_date=00.03.01 }
tree_spring2 = { start_date=00.03.20 end_date=00.04.20 }
tree_summer = { start_date=00.05.20 end_date=00.06.01 }
tree_summer2 = { start_date=00.06.20 end_date=00.09.10 }
tree_autumn = { start_date=00.10.01 end_date=00.10.10 }
tree_autumn2 = { start_date=00.10.25 end_date=00.11.01 }
""")


# 注意：不再生成 adjacency_rules/ambient_object/weatherpositions/unitstacks/rocket_sites


# ────────────────── State 拆分 ──────────────────

def _auto_split_states(land_ids, province_map, per_state=15):
    if not land_ids:
        return {}
    # 向量化计算质心
    flat_pm = province_map.ravel()
    n = int(province_map.max()) + 1
    pid_count = np.bincount(flat_pm, minlength=n)
    ys_grid, xs_grid = np.mgrid[0:MAP_HEIGHT, 0:MAP_WIDTH]
    sum_y = np.bincount(flat_pm, weights=ys_grid.ravel().astype(np.float64), minlength=n)
    sum_x = np.bincount(flat_pm, weights=xs_grid.ravel().astype(np.float64), minlength=n)

    centers = {}
    for pid in land_ids:
        if pid_count[pid] > 0:
            centers[pid] = (sum_y[pid] / pid_count[pid], sum_x[pid] / pid_count[pid])
    sorted_ids = sorted(centers.keys(), key=lambda p: (centers[p][0] // 100, centers[p][1]))
    states = {}
    for i in range(0, len(sorted_ids), per_state):
        sid = i // per_state + 1
        states[sid] = sorted_ids[i:i + per_state]
    return states


def _split_states_by_region(region_list, land_id_set, max_per_state=15):
    """
    从 region_list 按地区拆分 State。
    每个 state 的省份必须完全在同一个 strategic region 内（HOI4 强制要求）。

    参数:
        region_list: _write_strategic_regions 返回的 [(region_id, [pid...])] 列表
        land_id_set: 所有陆地省份的集合
        max_per_state: 每个 state 最多多少省份（太大的话拆分）

    返回:
        {state_id: [land_pid, ...]}
    """
    states = {}
    sid = 1
    for region_id, region_provs in region_list:
        # 只取这个 region 里的陆地省份
        region_land = [p for p in region_provs if p in land_id_set]
        if not region_land:
            continue
        # 如果太多则拆成多个 state，都在同一个 region 内
        for i in range(0, len(region_land), max_per_state):
            states[sid] = region_land[i:i + max_per_state]
            sid += 1
    return states


def _write_states(states, tag, province_map, output_dir):
    from export.writers.history.states import write_states_fallback
    write_states_fallback(states, tag, province_map, output_dir)


# ────────────────── 补给系统 ──────────────────

def _write_supply_nodes(states, province_map, output_dir):
    from export.writers.map.supply import write_supply_nodes
    return write_supply_nodes(states, province_map, output_dir)


def _write_railways(states, province_map, output_dir):
    from export.writers.map.supply import write_railways
    return write_railways(states, province_map, output_dir)


def _write_buildings(states, province_map, tile_map, output_dir, sea_ids=None,
                     land_to_sea=None, pid_count=None, sum_x=None, sum_y=None):
    from export.writers.map.buildings import write_buildings
    return write_buildings(states, province_map, tile_map, output_dir, sea_ids,
                           land_to_sea=land_to_sea,
                           pid_count=pid_count, sum_x=sum_x, sum_y=sum_y)


def _write_empty_unitstacks(output_dir):
    from export.writers.map.buildings import write_empty_unitstacks
    return write_empty_unitstacks(output_dir)


def _write_supply_areas(states, output_dir):
    from export.writers.map.supply import write_supply_areas
    return write_supply_areas(states, output_dir)


# ────────────────── 战略区域（多区域自动拆分）──────────────────

def _write_weatherpositions(region_list, province_map, output_dir):
    from export.writers.map.strategic_regions import write_weatherpositions
    return write_weatherpositions(region_list, province_map, output_dir)


def _write_strategic_regions(province_map, tile_map, output_dir,
                             grid_cols=6, grid_rows=4, states_dict=None):
    from export.writers.map.strategic_regions import write_strategic_regions
    return write_strategic_regions(province_map, tile_map, output_dir, grid_cols, grid_rows, states_dict)


def _write_positions(province_map, tile_map, output_dir,
                     pid_count=None, sum_x=None, sum_y=None):
    from export.writers.map.positions import write_positions_txt
    return write_positions_txt(province_map, tile_map, output_dir,
                               pid_count=pid_count, sum_x=sum_x, sum_y=sum_y)


# ────────────────── 国家 ──────────────────

def _write_country_flags(tags, output_dir, country_mgr=None):
    from export.writers.gfx.flags import write_country_flags
    return write_country_flags(tags, output_dir, country_mgr)


def _write_country_portraits(tag, output_dir):
    from export.writers.gfx.portraits import write_country_portraits
    return write_country_portraits(tag, output_dir)


def _write_country_colors(tag, rgb, output_dir):
    from export.writers.common.countries import write_country_colors
    return write_country_colors(tag, rgb, output_dir)


def _write_country_names(tag, output_dir, country_name="Fantasy"):
    from export.writers.common.countries import write_country_names
    return write_country_names(tag, output_dir, country_name)


def _write_country_characters(tag, output_dir, country_name="Fantasy"):
    from export.writers.common.countries import write_country_characters
    return write_country_characters(tag, output_dir, country_name)


def _write_dynamic_countries(output_dir, count=75):
    from export.writers.common.countries import write_dynamic_countries
    return write_dynamic_countries(output_dir, count)


def _write_country(tag, capital_state_id, output_dir):
    from export.writers.common.countries import write_country
    return write_country(tag, capital_state_id, output_dir)


# ────────────────── 本地化 ──────────────────

def _write_localisation(mod_name, tag, states, output_dir, region_count=24):
    from export.writers.localisation.yml import write_localisation_simple
    return write_localisation_simple(mod_name, tag, states, output_dir, region_count)


# ────────────────── descriptor.mod + 空目录 ──────────────────

def _write_descriptor(mod_name, output_dir):
    from export.writers.map.descriptor import write_descriptor
    return write_descriptor(mod_name, output_dir)



def _write_bookmark(mod_name, country_tags, output_dir):
    from export.writers.common.countries import write_bookmark
    return write_bookmark(mod_name, country_tags, output_dir)


# 注意：不再生成 ideologies 和 state_category — 用原版的（EaW 验证做法）
# 原版的 common/ideologies 和 common/state_category 已经足够完整


# ────────────────── 使用管理器数据导出 ──────────────────

def _write_states_from_mgr(state_mgr, country_mgr, province_map, output_dir, tile_map=None,
                           land_id_set=None, coastal_set=None):
    from export.writers.history.states import write_states_from_mgr
    write_states_from_mgr(state_mgr, country_mgr, province_map, output_dir, tile_map,
                          land_id_set=land_id_set, coastal_set=coastal_set)


def _write_countries_from_mgr(country_mgr, output_dir, states):
    from export.writers.common.countries import write_countries_from_mgr
    return write_countries_from_mgr(country_mgr, output_dir, states)


def _write_dynamic_country_oobs(output_dir, count=75):
    from export.writers.common.countries import write_dynamic_country_oobs
    return write_dynamic_country_oobs(output_dir, count)


def _write_country_ideas(country_mgr, output_dir):
    from export.writers.common.countries import write_country_ideas
    return write_country_ideas(country_mgr, output_dir)


def _write_localisation_full(mod_name, state_mgr, country_mgr, states, output_dir,
                             region_count=24, region_mgr=None):
    from export.writers.localisation.yml import write_localisation_full
    return write_localisation_full(mod_name, state_mgr, country_mgr, states, output_dir,
                                    region_count=region_count, region_mgr=region_mgr)


# ────────────────── 辅助函数 ──────────────────

def _is_land(pid, pm, tm):
    """与 _classify_provinces_fast 保持一致：land_n >= sea_n AND land_n >= lake_n"""
    mask = pm == pid
    if not np.any(mask):
        return False
    tiles = tm[mask]
    l = int(np.sum(tiles == TILE_LAND))
    s = int(np.sum(tiles == TILE_SEA))
    k = int(np.sum(tiles == TILE_LAKE))
    return l >= s and l >= k


def _get_province_type(pid, pm, tm):
    """返回省份类型: 'land', 'sea', 'lake'"""
    mask = pm == pid
    if not np.any(mask):
        return "sea"
    tiles = tm[mask]
    land_n = int(np.sum(tiles == TILE_LAND))
    sea_n = int(np.sum(tiles == TILE_SEA))
    lake_n = int(np.sum(tiles == TILE_LAKE))
    if land_n >= sea_n and land_n >= lake_n:
        return "land"
    elif lake_n > sea_n:
        return "lake"
    return "sea"


def _merge_tiny_provinces(province_map: np.ndarray, min_pixels: int = 8) -> np.ndarray:
    """将面积 < min_pixels 的碎屑省份合并到最大相邻省份。

    返回新数组，不修改原始 province_map。
    使用 numpy 向量化：bincount 统计面积，边界像素批量提取邻居。
    """
    pm = province_map.copy()
    h, w = pm.shape

    # 统计每个省份的像素数
    max_id = int(pm.max())
    areas = np.bincount(pm.ravel(), minlength=max_id + 1)

    # 找出所有 < min_pixels 的省份（跳过 ID 0 = 未分配）
    tiny_ids = np.where((areas > 0) & (areas < min_pixels))[0]
    tiny_ids = tiny_ids[tiny_ids > 0]
    if len(tiny_ids) == 0:
        return pm

    # 按面积从小到大处理（最小的先合并，避免两个碎块互相指向）
    tiny_ids = tiny_ids[np.argsort(areas[tiny_ids])]

    for pid in tiny_ids:
        # 该省份可能已被前一轮合并消灭
        mask = (pm == pid)
        if not np.any(mask):
            continue

        # 找边界像素的坐标
        ys, xs = np.where(mask)

        # 收集所有相邻像素的省份 ID（上下左右四方向）
        neighbor_ids = []
        for dy, dx in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            ny = ys + dy
            nx = xs + dx
            valid = (ny >= 0) & (ny < h) & (nx >= 0) & (nx < w)
            if np.any(valid):
                n_vals = pm[ny[valid], nx[valid]]
                # 排除自身和 ID 0
                n_vals = n_vals[(n_vals != pid) & (n_vals != 0)]
                if len(n_vals) > 0:
                    neighbor_ids.append(n_vals)

        if not neighbor_ids:
            continue

        all_neighbors = np.concatenate(neighbor_ids)
        # 统计每个邻居出现次数，再按邻居面积选最大的
        unique_neighbors, counts = np.unique(all_neighbors, return_counts=True)
        # 用邻居面积作为主排序键（选最大邻居）
        neighbor_areas = areas[unique_neighbors]
        best_idx = int(np.argmax(neighbor_areas))
        target = unique_neighbors[best_idx]

        # 把碎块像素改为目标省份
        pm[mask] = target
        # 更新面积缓存
        areas[target] += areas[pid]
        areas[pid] = 0

    return pm


def _classify_provinces_fast(province_count, province_map, tile_map):
    """向量化批量分类所有省份，避免逐省份全图扫描"""
    flat_pm = province_map.ravel()
    flat_tm = tile_map.ravel()

    # 用 bincount 一次性统计每个省份中各地块类型的像素数
    n = province_count + 1
    land_counts = np.bincount(flat_pm, weights=(flat_tm == TILE_LAND), minlength=n)
    sea_counts = np.bincount(flat_pm, weights=(flat_tm == TILE_SEA), minlength=n)
    lake_counts = np.bincount(flat_pm, weights=(flat_tm == TILE_LAKE), minlength=n)

    land_ids = []
    sea_ids = []
    lake_ids = []
    total_counts = land_counts + sea_counts + lake_counts
    for pid in range(1, province_count + 1):
        if total_counts[pid] == 0:
            # 0像素的幽灵省份 — 归入海洋（不需要State/战略区域）
            sea_ids.append(pid)
            continue
        l, s, k = land_counts[pid], sea_counts[pid], lake_counts[pid]
        if l >= s and l >= k:
            land_ids.append(pid)
        elif k > s:
            lake_ids.append(pid)
        else:
            sea_ids.append(pid)

    return land_ids, sea_ids, lake_ids


def _sync_tile_with_province_class(
    tile_map: np.ndarray,
    province_map: np.ndarray,
    land_ids: list[int],
    sea_ids: list[int],
    lake_ids: list[int],
) -> None:
    """就地同步 tile_map，使每个像素的 tile 类型 = 该像素所属 province 的类型。

    _classify_provinces_fast 按像素多数表决分类 province：一个 60% LAND / 40% SEA
    的 province 被归为 land，但那 40% SEA 像素在 tile_map 里仍是 SEA。这些"少数派"
    像素会导致:
      - HOI4 按 definition.csv 判该 province coastal 但 buildings writer 在 tile_map
        里找不到 LAND 像素 → naval_base 坐标写到 SEA 上 → HOI4 "not over the land"
        → port 被忽略 → coastal but no port → 崩溃
    同步后保证 tile_map、provinces.bmp、definition.csv 三者一致。
    """
    n = int(province_map.max()) + 1
    new_tile = np.zeros(n, dtype=np.uint8)
    for pid in land_ids:
        if 0 < pid < n:
            new_tile[pid] = TILE_LAND
    for pid in sea_ids:
        if 0 < pid < n:
            new_tile[pid] = TILE_SEA
    for pid in lake_ids:
        if 0 < pid < n:
            new_tile[pid] = TILE_LAKE
    # pid==0 是背景，保持原值
    new_tile[0] = tile_map.ravel()[0] if tile_map.size else TILE_SEA
    np.copyto(tile_map, new_tile[province_map])


def _sync_terrain_with_tile(terrain_map: np.ndarray, tile_map: np.ndarray) -> None:
    """同步 terrain_map 与 tile_map，就地修改 terrain_map。

    - 陆地像素上 terrain==ocean(15) → 改为 plains(0)
    - 海洋像素上 terrain!=ocean(15) → 改为 ocean(15)
    - 湖泊像素上 terrain!=lakes(14) → 改为 lakes(14)

    注意：这里直接修改 terrain_map（mutation），因为是导出前的一次性修正，
    不影响用户编辑器里的数据（导出器拿到的是独立 array）。
    """
    ocean_idx = TERRAIN_PALETTE_INDEX["ocean"]   # 15
    plains_idx = TERRAIN_PALETTE_INDEX["plains"]  # 0
    lakes_idx = TERRAIN_PALETTE_INDEX["lakes"]    # 14

    # 陆地上不应有 ocean 地形
    land_bad = (tile_map == TILE_LAND) & (terrain_map == ocean_idx)
    count_land = int(np.sum(land_bad))
    if count_land > 0:
        terrain_map[land_bad] = plains_idx
        print(f"  [terrain sync] {count_land:,} 个陆地像素的地形从 ocean 改为 plains")

    # 海洋上不应有陆地地形
    sea_bad = (tile_map == TILE_SEA) & (terrain_map != ocean_idx)
    count_sea = int(np.sum(sea_bad))
    if count_sea > 0:
        terrain_map[sea_bad] = ocean_idx
        print(f"  [terrain sync] {count_sea:,} 个海洋像素的地形改为 ocean")

    # 湖泊上地形应为 lakes
    lake_bad = (tile_map == TILE_LAKE) & (terrain_map != lakes_idx)
    count_lake = int(np.sum(lake_bad))
    if count_lake > 0:
        terrain_map[lake_bad] = lakes_idx
        print(f"  [terrain sync] {count_lake:,} 个湖泊像素的地形改为 lakes")


def _gen_heightmap(tm):
    """基于距离场生成自然渐变的 heightmap（接近 vanilla）。

    旧算法：固定值 + 高斯模糊 + 强制拉回 → 海岸像悬崖（80-110 过渡带几乎为 0）
    新算法：用距离场让高度随到对方的距离平滑变化
        - 陆地：距海越远越高（海岸 96 → 内陆 130+）
        - 海洋：距陆越远越深（浅海 94 → 深海 70-83）
    预期效果：80-110 过渡带占 70%+，接近 vanilla 的 85%
    """
    from scipy.ndimage import distance_transform_edt, gaussian_filter

    is_land = (tm == TILE_LAND)
    is_sea = (tm == TILE_SEA)
    is_lake = (tm == TILE_LAKE)

    # 距离场：每个像素到最近"对方"的像素距离
    dist_to_land = distance_transform_edt(~is_land)  # 海洋像素到最近陆地的距离
    dist_to_sea = distance_transform_edt(~is_sea)    # 陆地像素到最近海洋的距离

    hm = np.full((MAP_HEIGHT, MAP_WIDTH), SEA_LEVEL, dtype=np.float32)

    # 陆地高度：海岸 96 → 内陆最高 160
    # 系数 1.5/像素，封顶 +65（即最高 95+65=160）
    hm[is_land] = SEA_LEVEL + np.clip(dist_to_sea[is_land] * 1.5, 1, 65)

    # 海洋高度：浅海 94 → 深海最低 70
    # 系数 0.8/像素，封顶 -25（即最深 95-25=70）
    hm[is_sea] = SEA_LEVEL - np.clip(dist_to_land[is_sea] * 0.8, 1, 25)

    # 陆地加随机起伏让山地不那么平坦（±20 范围）
    rng = np.random.RandomState(42)
    noise = gaussian_filter(rng.rand(MAP_HEIGHT, MAP_WIDTH), sigma=30) * 40
    hm[is_land] += noise[is_land] - 20

    # 小尺度柔化（避免锯齿断阶）
    hm = gaussian_filter(hm, sigma=1.5)

    # 守底线（保证 HOI4 海陆判定正确）
    hm[is_land] = np.maximum(hm[is_land], SEA_LEVEL + 1)  # 陆地至少 96
    hm[is_sea] = np.minimum(hm[is_sea], SEA_LEVEL - 1)    # 海至少 94
    hm[is_lake] = SEA_LEVEL - 3

    return np.clip(hm, 30, 255).astype(np.uint8)


def _gen_terrain(tm):
    """生成 terrain.bmp。陆地海岸 1-2 像素用 desert（黄沙色）模拟沙滩。

    HOI4 的 desert 地形渲染颜色就是沙黄色，铺在海岸 1-2 像素上视觉效果
    类似 vanilla 的沙滩带。只影响视觉（渲染），不影响 gameplay（因为
    province 的主导地形是几十上百像素的 plains/forest，不会变沙漠）。
    """
    from scipy.ndimage import distance_transform_edt

    t = np.zeros((MAP_HEIGHT, MAP_WIDTH), dtype=np.uint8)
    for tile_type, name in DEFAULT_TERRAIN_FOR_TILE.items():
        t[tm == tile_type] = TERRAIN_PALETTE_INDEX[name]

    # 海岸沙滩：距海 ≤ 2 像素的陆地用 desert（索引 3 = 沙黄色）
    is_land = (tm == TILE_LAND)
    is_sea = (tm == TILE_SEA)
    dist_to_sea = distance_transform_edt(~is_sea)
    beach_mask = is_land & (dist_to_sea <= 2)
    t[beach_mask] = TERRAIN_PALETTE_INDEX["desert"]  # vanilla desert 渲染为沙黄色

    return t


def _write_normal_map(hm, output_dir):
    """写 world_normal.bmp 光照法线图（半尺寸）。
    先缩小到半尺寸再计算法线，省4倍计算量，视觉差异忽略不计。
    """
    d = os.path.join(output_dir, "map")
    os.makedirs(d, exist_ok=True)

    full_h, full_w = hm.shape
    NW, NH = full_w // 2, full_h // 2

    # 先缩到半尺寸再算法线（而不是算完再缩）
    h_small = hm.reshape(NH, 2, NW, 2).mean(axis=(1, 3)).astype(np.float32) / 255.0

    # 用 scipy.sobel 算梯度（标准做法，比中心差分平滑）
    # 新 heightmap 渐变范围更大，strength 降到 6（旧的 12 会过度起伏）
    from scipy.ndimage import sobel
    strength = 6.0
    dx = sobel(h_small, axis=1) * strength
    dy = -sobel(h_small, axis=0) * strength

    nx, ny, nz = -dx, -dy, np.ones_like(h_small)
    L = np.sqrt(nx**2 + ny**2 + nz**2)
    L[L == 0] = 1
    nx /= L; ny /= L; nz /= L

    r = ((nx + 1) * 127.5).clip(0, 255).astype(np.uint8)
    g = ((ny + 1) * 127.5).clip(0, 255).astype(np.uint8)
    b = ((nz + 1) * 127.5).clip(0, 255).astype(np.uint8)

    # 整块写入 BMP
    row = NW * 3
    pad = (4 - (row % 4)) % 4
    pix = (row + pad) * NH
    bgr = np.stack([b[::-1], g[::-1], r[::-1]], axis=2)  # (NH, NW, 3) bottom-up
    with open(os.path.join(d, "world_normal.bmp"), "wb") as f:
        f.write(b"BM")
        f.write(struct.pack("<I", 54 + pix))
        f.write(struct.pack("<HH", 0, 0))
        f.write(struct.pack("<I", 54))
        f.write(struct.pack("<I", 40))
        f.write(struct.pack("<ii", NW, NH))
        f.write(struct.pack("<HH", 1, 24))
        f.write(struct.pack("<I", 0))
        f.write(struct.pack("<I", pix))
        f.write(struct.pack("<ii", 2835, 2835))
        f.write(struct.pack("<II", 0, 0))
        if pad == 0:
            f.write(bgr.tobytes())
        else:
            pb = b"\x00" * pad
            for y in range(NH):
                f.write(bgr[y].tobytes())
                f.write(pb)
