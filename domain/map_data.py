"""
MapData — 地图数据中心。

把所有 numpy 图层 (tile_map / province_map / terrain_map / height_map / river_map)
集中到一个对象里，提供高级查询和修改方法。

设计原则：
1. **直接数组访问仍然工作**：MapData.tile_map 返回 numpy 数组，旧代码不用改
2. **高级方法作为补充**：get_neighbors / get_province_mask 等避免在多处重复实现
3. **不持有 UI 引用**：MapData 是纯数据层，不知道 canvas/widget 存在
4. **不做撤销/渲染**：那是上层的责任

迁移策略：
- 第一步：MapData 作为容器存在，canvas/main_window 通过 canvas.map_data.tile_map 访问
- 第二步：逐步把分散的辅助函数（get_neighbors 等）迁过来
- 第三步：高频读写过 MapData 方法，便于将来加钩子
"""

from __future__ import annotations

import numpy as np

from data.constants import MAP_WIDTH, MAP_HEIGHT, TILE_LAND, TILE_SEA, TILE_LAKE


class MapData:
    """地图全部图层 + 高级查询接口。"""

    def __init__(self) -> None:
        # 运行时读取当前尺寸（set_map_size 可能已修改）
        import data.constants as _c
        h, w = _c.MAP_HEIGHT, _c.MAP_WIDTH
        self.tile_map = np.full((h, w), TILE_SEA, dtype=np.uint8)
        self.province_map = np.zeros((h, w), dtype=np.int32)
        self.terrain_map = np.zeros((h, w), dtype=np.uint8)
        self.height_map = np.full((h, w), 40, dtype=np.uint8)
        self.river_map = np.full((h, w), 255, dtype=np.uint8)  # 255=白色背景，0=源头！
        self.density_map: np.ndarray | None = None  # (H,W) float32 0~1, None=均匀
        # 省份生成时的 tile_map 快照，用于检测"新画的陆地"
        self.tile_snapshot: np.ndarray | None = None
        # 省份级地形：province_id → terrain type 字符串
        # 独立于 terrain_map (graphical terrain)，用于 definition.csv 的战斗属性
        self.provincial_terrain: dict[int, str] = {}

    # ───────────── 重置/替换 ─────────────

    def reset(self) -> None:
        """所有图层恢复到初始状态。"""
        self.tile_map[:] = TILE_SEA
        self.province_map[:] = 0
        self.terrain_map[:] = 0
        self.height_map[:] = 40
        self.river_map[:] = 255  # 白色背景
        self.density_map = None
        self.tile_snapshot = None
        self.provincial_terrain.clear()

    def replace_all(
        self,
        tile_map: np.ndarray | None = None,
        province_map: np.ndarray | None = None,
        terrain_map: np.ndarray | None = None,
        height_map: np.ndarray | None = None,
        river_map: np.ndarray | None = None,
    ) -> None:
        """从外部数据（加载工程时用）批量替换图层。原地写入以保持引用稳定。"""
        if tile_map is not None:
            self.tile_map[:] = tile_map
        if province_map is not None:
            self.province_map[:] = province_map
        if terrain_map is not None:
            self.terrain_map[:] = terrain_map
        if height_map is not None:
            self.height_map[:] = height_map
        if river_map is not None:
            self.river_map[:] = river_map

    # ───────────── 字典接口（给 undo/serialize 用）─────────────

    def as_dict(self) -> dict[str, np.ndarray]:
        return {
            "tile_map": self.tile_map,
            "province_map": self.province_map,
            "terrain_map": self.terrain_map,
            "height_map": self.height_map,
            "river_map": self.river_map,
        }

    def apply_dict(self, data: dict[str, np.ndarray]) -> None:
        """从字典恢复（撤销时用）。原地写以保持引用。"""
        for k, v in data.items():
            arr = getattr(self, k, None)
            if arr is not None and v is not None:
                arr[:] = v

    # ───────────── 省份查询 ─────────────

    @property
    def province_count(self) -> int:
        return int(self.province_map.max())

    def get_province_mask(self, pid: int) -> np.ndarray:
        """返回布尔 mask，True 的地方就是这个省份的像素。"""
        return self.province_map == pid

    def get_province_pixel_count(self, pid: int) -> int:
        return int((self.province_map == pid).sum())

    def get_province_bbox(self, pid: int) -> tuple[int, int, int, int] | None:
        """返回 (x_min, y_min, x_max, y_max)，省份不存在返回 None。"""
        ys, xs = np.where(self.province_map == pid)
        if len(ys) == 0:
            return None
        return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())

    def get_province_centroid(self, pid: int) -> tuple[int, int] | None:
        """返回省份重心 (x, y)，不存在返回 None。优先用缓存。"""
        cache = getattr(self, '_centroid_cache', None)
        if cache is not None and pid in cache:
            return cache[pid]
        ys, xs = np.where(self.province_map == pid)
        if len(ys) == 0:
            return None
        result = (int(xs.mean()), int(ys.mean()))
        if cache is not None:
            cache[pid] = result
        return result

    def build_centroid_cache(self) -> None:
        """一次性计算所有省份质心，O(像素数) 而非 O(省份数×像素数)。"""
        pm = self.province_map
        max_pid = int(pm.max())
        if max_pid <= 0:
            self._centroid_cache = {}
            return
        h, w = pm.shape
        flat = pm.ravel()
        ys, xs = np.mgrid[0:h, 0:w]
        count = np.bincount(flat, minlength=max_pid + 1)
        sum_x = np.bincount(flat, weights=xs.ravel().astype(np.float64), minlength=max_pid + 1)
        sum_y = np.bincount(flat, weights=ys.ravel().astype(np.float64), minlength=max_pid + 1)
        cache: dict[int, tuple[int, int]] = {}
        for pid in range(1, max_pid + 1):
            if count[pid] > 0:
                cache[pid] = (int(sum_x[pid] / count[pid]), int(sum_y[pid] / count[pid]))
        self._centroid_cache = cache

    def invalidate_centroid_cache(self) -> None:
        """省份变化后清缓存。"""
        self._centroid_cache = None

    def get_province_tile_type(self, pid: int) -> int:
        """返回省份的地块类型（land/sea/lake）。
        实现：取省份内任意一个像素的 tile_map 值。"""
        ys, xs = np.where(self.province_map == pid)
        if len(ys) == 0:
            return 0
        return int(self.tile_map[ys[0], xs[0]])

    def get_province_neighbors(self, pid: int) -> set[int]:
        """返回省份 pid 的所有直接邻居 ID 集合。
        用 4 邻接膨胀检测。考虑横向 wrap。"""
        from scipy.ndimage import binary_dilation
        if pid <= 0:
            return set()
        mask = self.province_map == pid
        if not mask.any():
            return set()
        # 4 连通膨胀 1 像素
        struct = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=bool)
        dilated = binary_dilation(mask, structure=struct)
        # 横向 wrap：把右边缘和左边缘合并考虑
        # 简化处理：直接对边界邻居做 union（极少情况下不影响功能）
        border = dilated & ~mask
        neighbor_ids = set(int(x) for x in np.unique(self.province_map[border]))
        neighbor_ids.discard(0)
        neighbor_ids.discard(pid)
        return neighbor_ids

    def get_neighborhood_mask(self, pid: int) -> np.ndarray:
        """返回 pid 自己 + 所有直接邻居的合并 mask。
        套索/边界编辑用——限定操作的最大范围。"""
        neighbors = self.get_province_neighbors(pid)
        mask = self.province_map == pid
        for nid in neighbors:
            mask |= self.province_map == nid
        return mask

    # ───────────── 地块统计 ─────────────

    def compact_with_references(
        self,
        state_mgr=None,
        country_mgr=None,
        strategic_region_mgr=None,
        tracked_pids: list[int] | None = None,
        continent_mgr=None,
        adjacency_mgr=None,
        railway_mgr=None,
        supply_mgr=None,
        adjacency_rule_mgr=None,
    ) -> dict[int, int]:
        """压实 province_map 的 ID，并同步更新所有引用省份 ID 的地方。

        这是修改省份的"安全收尾"——任何会删除省份的操作（合并/扩张吃光邻居）
        结束后必须调这个，避免 ID gap 导致 HOI4 文档警告的属性串位灾难。

        self.provincial_terrain（省份级地形，按 pid 键控）也会同步重映射。

        参数：
            state_mgr: StateManager — 更新 state.provinces / victory_points / province_to_state
            country_mgr: CountryManager — 更新 country.capital
            strategic_region_mgr: StrategicRegionManager — 更新 region.province_ids
            tracked_pids: 调用方想追踪的额外 pid 列表（如选中的省份）
            continent_mgr: ContinentManager — 更新省份→大陆指派
            adjacency_mgr: AdjacencyManager — 更新邻接的 from/to/through
            railway_mgr: RailwayManager — 更新铁路经过的省份
            supply_mgr: SupplyNodeManager — 更新补给节点省份
            adjacency_rule_mgr: AdjacencyRuleManager — 更新规则的 required/icon 省份

        返回：
            {old_id: new_id} 映射，调用方用它更新自己持有的 pid 引用
        """
        from domain.generators.province import compact_province_ids

        # 压实前的旧 ID 列表
        old_unique = np.unique(self.province_map).tolist()

        # 压实
        compact_province_ids(self.province_map)

        # 压实后的新 ID 列表（顺序与 old_unique 一一对应）
        new_unique = np.unique(self.province_map).tolist()

        # 构建映射 {old: new}
        if len(old_unique) != len(new_unique):
            # 不应该发生（compact 是稳定排序）
            raise RuntimeError("compact_province_ids 产生了不一致的 ID 列表")
        mapping = dict(zip(old_unique, new_unique))

        # 更新 state_mgr
        # 注意：被删除的省份（不在 mapping 里）必须从 list/dict 中**完全丢弃**，
        # 不能保留死引用，否则 state 会指向不存在的省份
        if state_mgr is not None:
            for state in state_mgr.states.values():
                # 过滤掉死引用（被删除的省份），同时去重
                seen = set()
                new_provinces = []
                for p in state.provinces:
                    if p in mapping and mapping[p] != 0 and mapping[p] not in seen:
                        seen.add(mapping[p])
                        new_provinces.append(mapping[p])
                state.provinces = new_provinces

                # VP 字典：丢掉死引用
                new_vp = {}
                for old_pid, value in state.victory_points.items():
                    if old_pid in mapping and mapping[old_pid] != 0:
                        new_vp[mapping[old_pid]] = value
                state.victory_points = new_vp

            # 重建 province_to_state 索引
            new_p2s = {}
            for sid, state in state_mgr.states.items():
                for pid in state.provinces:
                    new_p2s[pid] = sid
            state_mgr._province_to_state = new_p2s

        # 更新 country_mgr
        if country_mgr is not None:
            for country in country_mgr.countries.values():
                if country.capital > 0:
                    if country.capital in mapping and mapping[country.capital] != 0:
                        country.capital = mapping[country.capital]
                    else:
                        # 首都被删了，清零
                        country.capital = 0

        # 更新 strategic_region_mgr
        if strategic_region_mgr is not None:
            for region in strategic_region_mgr._regions.values():
                seen = set()
                new_provs = []
                for p in region.province_ids:
                    if p in mapping and mapping[p] != 0 and mapping[p] not in seen:
                        seen.add(mapping[p])
                        new_provs.append(mapping[p])
                region.province_ids = new_provs

        # 更新 continent / adjacency / railway / supply / adjacency_rule
        # 它们的 remap_provinces 自带死引用清理：不在 mapping 里的省份被丢弃。
        # mapping 可能含 0:0（未分配像素），剔除后引用 0 号的脏数据也会被清掉
        ref_mapping = {o: n for o, n in mapping.items() if o != 0}
        for mgr in (continent_mgr, adjacency_mgr, railway_mgr,
                    supply_mgr, adjacency_rule_mgr):
            if mgr is not None:
                mgr.remap_provinces(ref_mapping)

        # 省份级地形（definition.csv 战斗属性）同样按 pid 键控
        if self.provincial_terrain:
            self.provincial_terrain = {
                mapping[pid]: t
                for pid, t in self.provincial_terrain.items()
                if mapping.get(pid, 0) != 0
            }

        return mapping

    def get_tile_counts(self) -> dict[str, int]:
        """统计陆/海/湖像素数。"""
        return {
            "land": int((self.tile_map == TILE_LAND).sum()),
            "sea":  int((self.tile_map == TILE_SEA).sum()),
            "lake": int((self.tile_map == TILE_LAKE).sum()),
        }
