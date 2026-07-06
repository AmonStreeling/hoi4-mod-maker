"""
MOD 导出服务 — 导出前校验 + 自动修复 + 调 export_full_mod.

UI 层 (MainWindow) 只负责目录选择 + 错误显示, 业务规则都在这里.
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ExportReport:
    """导出结果报告"""
    warnings: list[str] = field(default_factory=list)
    fixed: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)


def validate_before_export(canvas, state_mgr, country_mgr) -> list[str]:
    """返回警告列表. 空列表 = 可以安全导出."""
    warnings: list[str] = []
    pm = canvas.province_map
    if int(pm.max()) == 0:
        warnings.append("没有省份数据，请先生成省份")
        return warnings

    if not state_mgr.states:
        warnings.append("没有 State，请先自动分组或手动创建")

    if not country_mgr.countries:
        warnings.append("没有国家，请先创建至少一个国家")

    unowned = []
    for sid, state in state_mgr.states.items():
        owner = country_mgr.get_owner_of_state(sid)
        if not owner:
            unowned.append(str(sid))
    if unowned:
        warnings.append(
            f"{len(unowned)} 个 State 未分配国家: {', '.join(unowned[:5])}..."
        )

    for tag, country in country_mgr.countries.items():
        if country.capital <= 0:
            warnings.append(f"国家 {tag} 没有设首都")

    # ── 河流合法性（显示级问题: 不会崩游戏, 但会断流/不显示）──
    from domain.managers.river import validate_rivers, VALID_RIVER_VALUES
    rm = getattr(canvas, "river_map", None)
    if rm is not None and bool(np.isin(rm, list(VALID_RIVER_VALUES)).any()):
        issues = [
            w for w in validate_rivers(rm)
            if "没有河流数据" not in w and "验证通过" not in w
        ]
        for w in issues[:5]:
            warnings.append(f"河流: {w}")
        if len(issues) > 5:
            warnings.append(f"河流: 还有 {len(issues) - 5} 个问题, 详见河流页的「验证河流」")

    return warnings


def pre_export_check_and_fix(
    tile_map: np.ndarray,
    province_map: np.ndarray,
    terrain_map: np.ndarray | None,
    state_mgr,
    country_mgr,
    continent_mgr=None,
    strategic_region_mgr=None,
) -> ExportReport:
    """导出前自动检测和修复已知问题。

    返回 ExportReport，包含修复信息和无法自动修复的警告。
    """
    warnings: list[str] = []
    fixed: list[str] = []

    province_count = int(province_map.max())
    if province_count == 0:
        return ExportReport(warnings=["没有省份数据"], fixed=[], stats={})

    # ── 1. 同步 terrain_map 与 tile_map ──
    if terrain_map is not None:
        from data.terrain_types import TERRAIN_PALETTE_INDEX
        from data.constants import TILE_LAND, TILE_SEA, TILE_LAKE
        ocean_idx = TERRAIN_PALETTE_INDEX["ocean"]
        plains_idx = TERRAIN_PALETTE_INDEX["plains"]
        lakes_idx = TERRAIN_PALETTE_INDEX["lakes"]

        land_bad = (tile_map == TILE_LAND) & (terrain_map == ocean_idx)
        sea_bad = (tile_map == TILE_SEA) & (terrain_map != ocean_idx)
        lake_bad = (tile_map == TILE_LAKE) & (terrain_map != lakes_idx)

        count_lb = int(np.sum(land_bad))
        count_sb = int(np.sum(sea_bad))
        count_lk = int(np.sum(lake_bad))

        if count_lb > 0:
            terrain_map[land_bad] = plains_idx
            fixed.append(f"修正 {count_lb:,} 个陆地像素的地形 ocean→plains")
        if count_sb > 0:
            terrain_map[sea_bad] = ocean_idx
            fixed.append(f"修正 {count_sb:,} 个海洋像素的地形→ocean")
        if count_lk > 0:
            terrain_map[lake_bad] = lakes_idx
            fixed.append(f"修正 {count_lk:,} 个湖泊像素的地形→lakes")

    # ── 2. 省份颜色碰撞检测 ──
    from domain.generators.province import generate_province_colors
    colors = generate_province_colors(province_count)
    color_to_pids: dict[tuple[int, int, int], list[int]] = {}
    for pid, color in colors.items():
        color_to_pids.setdefault(color, []).append(pid)
    collisions = {c: pids for c, pids in color_to_pids.items() if len(pids) > 1}
    if collisions:
        # 自动修复：给碰撞的省份重新生成颜色
        used_colors = set(colors.values())
        used_colors.add((0, 0, 0))
        rng = np.random.default_rng(9999)
        for color_rgb, pids in collisions.items():
            # 保留第一个, 其余重新生成
            for pid in pids[1:]:
                while True:
                    new_color = (
                        int(rng.integers(1, 256)),
                        int(rng.integers(0, 256)),
                        int(rng.integers(0, 256)),
                    )
                    if new_color not in used_colors:
                        used_colors.add(new_color)
                        colors[pid] = new_color
                        break
        total_collisions = sum(len(pids) - 1 for pids in collisions.values())
        fixed.append(f"修正 {total_collisions} 个省份颜色碰撞")

    # ── 2.5 删除空 State + 压实 ID 连续 ──
    # 合并 province 留下的空 state 必须删, 删完后 ID 还有 gap → HOI4 statetemplate.cpp:651
    # 报 'Missing State ID' → AI tick 阶段除零 → 崩溃 (实测 2026-04-25 16:30 案例).
    # 所以删完必须把剩余 state 重新编号 1..N, 并同步更新 country_mgr 里的 state owner 引用.
    if state_mgr:
        empty_sids = state_mgr.find_empty_state_ids()
        if empty_sids:
            for sid in empty_sids:
                state_mgr.delete_state(sid)
            preview = ", ".join(str(s) for s in empty_sids[:10])
            more = f" 等共 {len(empty_sids)} 个" if len(empty_sids) > 10 else ""
            fixed.append(f"删除 {len(empty_sids)} 个空 State (合并省份留下的): {preview}{more}")
        mapping = state_mgr.compact_ids()
        if mapping:
            if country_mgr is not None:
                country_mgr.remap_state_ids(mapping)
            fixed.append(f"重新编号 {len(mapping)} 个 State 为连续 ID (HOI4 要求 ID 无 gap)")

    # ── 3. 验证所有陆地省份属于 State ──
    if state_mgr and state_mgr.states:
        from data.constants import TILE_LAND
        flat_pm = province_map.ravel()
        flat_tm = tile_map.ravel()
        n = province_count + 1
        land_counts = np.bincount(flat_pm, weights=(flat_tm == TILE_LAND), minlength=n)
        total_counts = np.bincount(flat_pm, minlength=n)

        land_pids = set()
        for pid in range(1, province_count + 1):
            if total_counts[pid] > 0 and land_counts[pid] > total_counts[pid] / 2:
                land_pids.add(pid)

        assigned_pids = set()
        for sid, state in state_mgr.states.items():
            assigned_pids.update(state.provinces)

        orphan_pids = land_pids - assigned_pids
        if orphan_pids:
            # 自动领养：分配到最近的 State（导出器会再做一次，但这里先提示）
            warnings.append(
                f"{len(orphan_pids)} 个陆地省份未分配到 State（导出时自动领养）"
            )

    # ── 4. 验证所有 State 有 owner ──
    if state_mgr and country_mgr:
        unowned = []
        for sid in state_mgr.states:
            owner = country_mgr.get_owner_of_state(sid)
            if not owner:
                unowned.append(sid)
        if unowned:
            if country_mgr.countries:
                # 自动修复：分配给第一个国家
                first_tag = next(iter(country_mgr.countries))
                for sid in unowned:
                    country_mgr.assign_state(sid, first_tag)
                    state = state_mgr.get_state(sid)
                    if state:
                        state.owner_tag = first_tag
                fixed.append(
                    f"{len(unowned)} 个无主 State 自动分配给 {first_tag}"
                )
            else:
                warnings.append(
                    f"{len(unowned)} 个 State 没有所有者，且没有可分配的国家"
                )

    # ── 5. 验证省份属于大陆 ──
    if continent_mgr is not None:
        # continent_mgr 默认所有陆地省份归 index 0，所以一般没问题
        if continent_mgr.count() == 0:
            warnings.append("没有大陆定义，导出时使用默认大陆")

    # ── 5.5 拆分地理不连通的 strategic region ──
    # HOI4 引擎要求每个 strategic region 内的省份**地理相连** (像素级 4-邻接).
    # 用户在 UI 手动画 region 或老版本数据可能产生不连通的 region (一个 region
    # 跨越分离的两块地). HOI4 加载这种 region → 引擎死循环 / 除零崩溃 (实测案例).
    # 这里强制按连通性拆开, 不连通的部分各自变成独立 region.
    if strategic_region_mgr is not None and strategic_region_mgr.regions:
        from domain.managers.strategic_region import _split_connected
        split_count = 0
        new_regions_added = 0
        for old_region in list(strategic_region_mgr.regions.values()):
            provs = [p for p in old_region.province_ids if 0 < p <= province_count]
            if len(provs) < 2:
                continue
            groups = _split_connected(province_map, set(provs))
            if len(groups) <= 1:
                continue  # 已经连通, 不动
            # 不连通: 第一组留在原 region, 其余组拆成新 region
            split_count += 1
            old_region.province_ids = list(groups[0])
            for extra_group in groups[1:]:
                new_r = strategic_region_mgr.create_region()
                new_r.province_ids = list(extra_group)
                new_r.naval_terrain = old_region.naval_terrain
                new_r.weather_preset = old_region.weather_preset
                new_regions_added += 1
        if split_count > 0:
            fixed.append(
                f"拆分 {split_count} 个地理不连通的战略区域 → 新增 {new_regions_added} 个连通区域 "
                f"(HOI4 要求 region 内省份必须像素相连, 否则崩溃)"
            )

    # ── 6. 验证国家首都 ──
    if country_mgr and country_mgr.countries:
        for tag, country in country_mgr.countries.items():
            if country.capital <= 0:
                # 自动修复：使用该国家第一个 State 的第一个省份
                owned_states = country_mgr.get_states_of_country(tag)
                if owned_states and state_mgr:
                    first_state = state_mgr.get_state(owned_states[0])
                    if first_state and first_state.provinces:
                        country.capital = first_state.provinces[0]
                        fixed.append(f"国家 {tag} 自动设首都为省份 {country.capital}")
                    else:
                        warnings.append(f"国家 {tag} 没有首都且无法自动设置")
                else:
                    warnings.append(f"国家 {tag} 没有首都且没有领土")

    # ── 统计 ──
    stats = {
        "provinces": province_count,
        "states": len(state_mgr.states) if state_mgr else 0,
        "countries": len(country_mgr.countries) if country_mgr else 0,
    }

    return ExportReport(warnings=warnings, fixed=fixed, stats=stats)


def fill_default_state_data(
    state_mgr,
    terrain_map: np.ndarray | None,
    province_map: np.ndarray,
    tile_map: np.ndarray,
) -> int:
    """为没有资源/建筑的 State 填充基于地形的默认数据。

    只填充空数据，不覆盖用户已设置的值。
    返回填充了默认数据的 State 数量。
    """
    if not state_mgr or not state_mgr.states:
        return 0

    from data.constants import TILE_LAND
    from data.terrain_types import PALETTE_TO_TYPE

    filled_count = 0
    rng = np.random.RandomState(42)

    # 向量化预计算：每个省份的陆地像素数 + 地形分布（一次全图扫描代替 N 次）
    max_pid = int(province_map.max())
    flat_pm = province_map.ravel()
    flat_tm = tile_map.ravel()
    flat_land = (flat_tm == TILE_LAND).astype(np.int32)
    pid_land_count = np.bincount(flat_pm, weights=flat_land, minlength=max_pid + 1)

    # 每个 (province_id, terrain_index) 的像素数
    pid_terrain_count: dict[int, dict[int, int]] = {}
    if terrain_map is not None:
        flat_ter = terrain_map.ravel()
        land_mask_flat = flat_land.astype(bool)
        land_pids = flat_pm[land_mask_flat]
        land_ters = flat_ter[land_mask_flat]
        # 用 (pid * 256 + terrain_idx) 编码为单一键做 bincount
        combined = land_pids.astype(np.int64) * 256 + land_ters.astype(np.int64)
        combined_counts = np.bincount(combined)
        for code in np.nonzero(combined_counts)[0]:
            pid_code = int(code // 256)
            ter_code = int(code % 256)
            if pid_code not in pid_terrain_count:
                pid_terrain_count[pid_code] = {}
            pid_terrain_count[pid_code][ter_code] = int(combined_counts[code])

    for sid, state in state_mgr.states.items():
        has_resources = bool(state.resources and any(v > 0 for v in state.resources.values()))
        has_buildings = bool(state.buildings and any(v > 0 for v in state.buildings.values()))

        if has_resources and has_buildings:
            continue

        # 用预计算数据汇总 state 的地形组成
        terrain_counts: dict[str, int] = {}
        total_land_pixels = 0
        for pid in state.provinces:
            if pid > max_pid:
                continue
            land_px = int(pid_land_count[pid])
            total_land_pixels += land_px
            if land_px > 0 and pid in pid_terrain_count:
                for ter_idx, count in pid_terrain_count[pid].items():
                    ttype = PALETTE_TO_TYPE.get(ter_idx, "plains")
                    terrain_counts[ttype] = terrain_counts.get(ttype, 0) + count

        if total_land_pixels == 0:
            continue

        filled_count += 1

        # 确定主要地形
        dominant = max(terrain_counts, key=terrain_counts.get) if terrain_counts else "plains"

        # 基于 state_category 设置基础设施
        cat_infra = {
            "wasteland": 0, "pastoral": 1, "tiny": 1, "small": 1,
            "town": 2, "large_town": 2, "city": 3,
            "large_city": 4, "megalopolis": 5,
        }

        # ── 填充资源 ──
        if not has_resources:
            resources: dict[str, int] = {}
            if dominant in ("mountain", "hills"):
                # 山地/丘陵：钢铁/铬
                resources["steel"] = rng.randint(4, 20)
                if rng.random() > 0.5:
                    resources["chromium"] = rng.randint(2, 12)
            elif dominant == "desert":
                # 沙漠：石油概率
                if rng.random() > 0.4:
                    resources["oil"] = rng.randint(2, 16)
            elif dominant in ("jungle",):
                # 丛林：橡胶
                resources["rubber"] = rng.randint(2, 10)
            elif dominant in ("forest",):
                # 森林：钨
                if rng.random() > 0.5:
                    resources["tungsten"] = rng.randint(2, 8)
            elif dominant == "urban":
                # 城市：铝
                resources["aluminium"] = rng.randint(4, 16)

            if resources:
                state.resources = resources

        # ── 填充建筑 ──
        if not has_buildings:
            infra = cat_infra.get(state.category, 1)
            buildings: dict[str, int] = {}
            if infra > 0:
                buildings["infrastructure"] = infra
            state.buildings = buildings

        # ── 填充 manpower ──
        if state.manpower <= 0:
            # 按省份数量和类别估算
            province_count = len(state.provinces)
            base = province_count * 50000
            cat_multiplier = {
                "wasteland": 0, "pastoral": 0.5, "tiny": 0.8, "small": 1.0,
                "town": 1.5, "large_town": 2.0, "city": 3.0,
                "large_city": 5.0, "megalopolis": 10.0,
            }
            state.manpower = int(base * cat_multiplier.get(state.category, 1.0))

    return filled_count


def export_mod(
    output_dir: str,
    canvas,
    state_mgr,
    country_mgr,
    continent_mgr,
    adjacency_mgr=None,
    railway_mgr=None,
    supply_mgr=None,
    colormap_settings=None,
    default_map_settings=None,
    adjacency_rule_mgr=None,
    strategic_region_mgr=None,
    scope: dict[str, bool] | None = None,
    assets: dict[str, bytes] | None = None,
    dirty_assets: set[str] | None = None,
) -> ExportReport:
    """调用完整导出管线. 失败抛异常. 返回 ExportReport."""
    # ── 导出前自动检测和修复 ──
    report = pre_export_check_and_fix(
        tile_map=canvas.tile_map,
        province_map=canvas.province_map,
        terrain_map=canvas.terrain_map,
        state_mgr=state_mgr,
        country_mgr=country_mgr,
        continent_mgr=continent_mgr,
    )

    # ── 填充 State 默认资源/建筑 ──
    filled = fill_default_state_data(
        state_mgr=state_mgr,
        terrain_map=canvas.terrain_map,
        province_map=canvas.province_map,
        tile_map=canvas.tile_map,
    )
    if filled > 0:
        report = ExportReport(
            warnings=report.warnings,
            fixed=list(report.fixed) + [f"为 {filled} 个 State 填充了默认资源/建筑"],
            stats=report.stats,
        )

    # ── 省份编号空洞提示 ──
    # 合并省份留下的 ID 空洞由导出器在导出副本上自动压实, 项目数据不变
    if scope is None or scope.get("compact_ids", True):
        _ids = np.unique(canvas.province_map)
        _nonzero = _ids[_ids > 0]
        _gap_count = int(_nonzero[-1]) - len(_nonzero) if len(_nonzero) else 0
        if _gap_count > 0:
            report = ExportReport(
                warnings=report.warnings,
                fixed=list(report.fixed) + [
                    f"检测到 {_gap_count} 个省份编号空洞 (合并省份留下的), "
                    f"导出文件已自动压实为连续编号, 项目数据保持不变"
                ],
                stats=report.stats,
            )

    # ── 执行导出 ──
    from export.mod_exporter import export_full_mod
    export_full_mod(
        canvas.tile_map,
        canvas.province_map,
        output_dir,
        state_mgr=state_mgr,
        country_mgr=country_mgr,
        river_map=canvas.river_map,
        terrain_map=canvas.terrain_map,
        height_map=canvas.height_map,
        continent_mgr=continent_mgr,
        adjacency_mgr=adjacency_mgr,
        railway_mgr=railway_mgr,
        supply_mgr=supply_mgr,
        colormap_settings=colormap_settings,
        default_map_settings=default_map_settings,
        adjacency_rule_mgr=adjacency_rule_mgr,
        strategic_region_mgr=strategic_region_mgr,
        provincial_terrain=canvas.map_data.provincial_terrain,
        scope=scope,
        assets=assets,
        dirty_assets=dirty_assets,
    )

    # ── 统计导出文件 ──
    import os
    file_count = sum(len(files) for _, _, files in os.walk(output_dir))
    stats = dict(report.stats)
    stats["files"] = file_count

    return ExportReport(
        warnings=report.warnings,
        fixed=report.fixed,
        stats=stats,
    )
