"""
State 管理器 — State 数据结构、自动分组、手动编辑
"""
import numpy as np
from dataclasses import dataclass, field
from scipy.ndimage import label
from data.constants import MAP_WIDTH, MAP_HEIGHT, TILE_LAND


@dataclass
class StateData:
    """一个 State 的数据"""
    id: int
    name: str = ""                      # 主显示名（任何语言，可中文）— 导出到 simp_chinese yml
    name_en: str = ""                   # 可选英文名 — 导出到 english yml；空则用 "State {id}"
    provinces: list[int] = field(default_factory=list)
    manpower: int = 100000
    category: str = "town"  # wasteland/pastoral/tiny/small/town/large_town/city/large_city/megalopolis
    owner_tag: str = ""
    victory_points: dict[int, int] = field(default_factory=dict)  # {province_id: vp_value}
    vp_names: dict[int, str] = field(default_factory=dict)  # {province_id: city_name 主显示名}
    vp_names_en: dict[int, str] = field(default_factory=dict)  # {province_id: city_name 英文}

    # ── 进阶字段 (State modding 规范) ──
    impassable: bool = False  # 不可通行 state, 不能部署单位/建楼
    controller_tag: str = ""  # 初始控制者 (≠ owner 时用于战争开局)
    local_supplies: float = 0.0  # 本地补给加成
    # 资源: oil/aluminium/rubber/tungsten/steel/chromium (值=0 不写)
    resources: dict[str, int] = field(default_factory=dict)
    # state 级建筑: infrastructure/arms_factory/industrial_complex/dockyard/
    # air_base/anti_air_building/radar_station/synthetic_refinery/fuel_silo/
    # nuclear_reactor/rocket_site/mass_transit/supply_node (值=0 不写)
    buildings: dict[str, int] = field(default_factory=dict)
    # 省份级建筑: {province_id: {building_name: level}}
    # 用于 bunker / coastal_bunker / naval_base 按省份写
    province_buildings: dict[int, dict[str, int]] = field(default_factory=dict)
    # 额外 core TAG 列表 (owner_tag 会自动 add_core_of)
    extra_cores: list[str] = field(default_factory=list)
    # 宣称 TAG 列表
    claims: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.name:
            self.name = f"STATE_{self.id}"


class StateManager:
    """管理所有 State"""

    # State 类别选项
    CATEGORIES = [
        "wasteland", "pastoral", "tiny", "small", "town",
        "large_town", "city", "large_city", "megalopolis",
    ]

    def __init__(self):
        self._states: dict[int, StateData] = {}
        self._province_to_state: dict[int, int] = {}  # pid → state_id
        self._next_id = 1

    @property
    def states(self) -> dict[int, StateData]:
        return self._states

    def get_state(self, state_id: int) -> StateData | None:
        return self._states.get(state_id)

    def get_state_of_province(self, pid: int) -> int:
        """查询省份所属的 State ID，0=未分配"""
        return self._province_to_state.get(pid, 0)

    def create_state(self, provinces: list[int] | None = None) -> StateData:
        """创建新 State"""
        sid = self._next_id
        self._next_id += 1
        state = StateData(id=sid, provinces=provinces or [])
        self._states[sid] = state
        for pid in state.provinces:
            self._province_to_state[pid] = sid
        return state

    def assign_province(self, pid: int, state_id: int) -> None:
        """将省份移动到指定 State"""
        # 从旧 State 移除
        old_sid = self._province_to_state.get(pid, 0)
        if old_sid > 0 and old_sid in self._states:
            provs = self._states[old_sid].provinces
            if pid in provs:
                provs.remove(pid)

        # 加入新 State
        if state_id in self._states:
            if pid not in self._states[state_id].provinces:
                self._states[state_id].provinces.append(pid)
            self._province_to_state[pid] = state_id

    def set_vp(self, province_id: int, value: int, name: str = "") -> None:
        """设置胜利点 + 城市名"""
        sid = self._province_to_state.get(province_id, 0)
        if sid > 0 and sid in self._states:
            self._states[sid].victory_points[province_id] = value
            if name:
                self._states[sid].vp_names[province_id] = name
            elif province_id not in self._states[sid].vp_names:
                self._states[sid].vp_names[province_id] = ""

    def remove_vp(self, province_id: int) -> None:
        """移除胜利点"""
        sid = self._province_to_state.get(province_id, 0)
        if sid > 0 and sid in self._states:
            self._states[sid].victory_points.pop(province_id, None)
            self._states[sid].vp_names.pop(province_id, None)

    def clear(self) -> None:
        """清空所有数据"""
        self._states.clear()
        self._province_to_state.clear()
        self._next_id = 1

    def delete_state(self, state_id: int) -> bool:
        """删除一个 State; 返回是否实际删除. 反向索引里指向该 State 的省份也清掉."""
        if state_id not in self._states:
            return False
        for pid in list(self._states[state_id].provinces):
            if self._province_to_state.get(pid) == state_id:
                self._province_to_state.pop(pid, None)
        del self._states[state_id]
        return True

    def find_empty_state_ids(self) -> list[int]:
        """返回所有 provinces 列表为空的 State ID — 通常是合并省份后留下的孤儿."""
        return [sid for sid, st in self._states.items() if not st.provinces]

    def compact_ids(self) -> dict[int, int]:
        """把 state ID 重新编号为 1..N 连续 (按原 ID 升序保持相对顺序).

        HOI4 statetemplate.cpp 要求 state ID 连续, 任何 gap 都会触发 'Missing State ID'
        进而引发除零崩溃. 合并 province 删空 state 后必须调用这个方法压实 ID.

        返回 {old_id: new_id} 映射; 如果已经连续返回空 dict.
        StateData.id 字段同步更新; 默认名 'STATE_{old}' 会同步改成 'STATE_{new}'.
        """
        old_ids = sorted(self._states.keys())
        if not old_ids:
            return {}
        if old_ids == list(range(1, len(old_ids) + 1)):
            return {}

        mapping = {old: new for new, old in enumerate(old_ids, start=1)}
        new_states: dict[int, StateData] = {}
        for old, state in self._states.items():
            new_id = mapping[old]
            if state.name == f"STATE_{old}":
                state.name = f"STATE_{new_id}"
            state.id = new_id
            new_states[new_id] = state
        self._states = new_states
        self._province_to_state = {
            pid: mapping[old_sid]
            for pid, old_sid in self._province_to_state.items()
            if old_sid in mapping
        }
        self._next_id = len(self._states) + 1
        return mapping

    def auto_split(
        self,
        province_map: np.ndarray,
        tile_map: np.ndarray,
        per_state: int = 15,
    ) -> None:
        """
        自动按地理位置把陆地省份分成 State。
        先用连通分量找独立陆块，再在每个陆块内部按坐标分组，
        避免隔海的省份被分到同一个 State。
        """
        self.clear()

        max_pid = int(province_map.max())
        if max_pid == 0:
            return

        # 向量化：一次性计算所有省份的中心和类型
        # 用 bincount 批量统计，避免逐省份全图扫描
        flat_pm = province_map.ravel()
        flat_tm = tile_map.ravel()
        flat_land = (flat_tm == TILE_LAND).astype(np.int32)

        # 每个省份的像素数和陆地像素数
        pid_count = np.bincount(flat_pm, minlength=max_pid + 1)
        pid_land_count = np.bincount(flat_pm, weights=flat_land, minlength=max_pid + 1)

        # 陆地省份：陆地像素 > 总像素的一半
        land_ids = []
        for pid in range(1, max_pid + 1):
            if pid_count[pid] > 0 and pid_land_count[pid] > pid_count[pid] / 2:
                land_ids.append(pid)

        if not land_ids:
            return

        # 向量化计算省份质心 — 用 province_map 的真实 shape，
        # 不信模块级 MAP_WIDTH/MAP_HEIGHT（那是首次 import 时绑定的常量，
        # set_map_size 改不到这里；若项目非原版尺寸会 bincount 长度不匹配崩）
        map_h, map_w = province_map.shape
        ys_all, xs_all = np.mgrid[0:map_h, 0:map_w]
        flat_ys = ys_all.ravel().astype(np.float64)
        flat_xs = xs_all.ravel().astype(np.float64)

        sum_y = np.bincount(flat_pm, weights=flat_ys, minlength=max_pid + 1)
        sum_x = np.bincount(flat_pm, weights=flat_xs, minlength=max_pid + 1)

        centers = {}
        land_set = set(land_ids)
        for pid in land_ids:
            cnt = pid_count[pid]
            if cnt > 0:
                centers[pid] = (sum_y[pid] / cnt, sum_x[pid] / cnt)

        # 用连通分量找独立陆块
        land_binary = (tile_map == TILE_LAND).astype(np.int32)
        labeled_land, num_landmasses = label(land_binary)

        # 每个省份属于哪个陆块（用省份中心像素所在的连通分量）
        pid_to_landmass: dict[int, int] = {}
        for pid in land_ids:
            cy, cx = centers[pid]
            iy, ix = int(cy), int(cx)
            iy = min(max(iy, 0), map_h - 1)
            ix = min(max(ix, 0), map_w - 1)
            lm = int(labeled_land[iy, ix])
            if lm == 0:
                # 中心点不在陆地上（边缘情况），找该省份任意陆地像素
                mask = (province_map == pid) & (tile_map == TILE_LAND)
                pts = np.where(mask)
                if len(pts[0]) > 0:
                    lm = int(labeled_land[pts[0][0], pts[1][0]])
            pid_to_landmass[pid] = lm

        # 按陆块分组
        landmass_groups: dict[int, list[int]] = {}
        for pid in land_ids:
            lm = pid_to_landmass.get(pid, 0)
            if lm not in landmass_groups:
                landmass_groups[lm] = []
            landmass_groups[lm].append(pid)

        # 在每个陆块内部用 K-means 聚类质心 → 紧凑 blob，避免横向条带和跨海拉省
        from scipy.cluster.vq import kmeans2
        rng_seed = 42  # 固定种子保证同一项目重复生成结果一致
        for lm_id, group_pids in landmass_groups.items():
            n_pids = len(group_pids)
            if n_pids == 0:
                continue
            # 目标 state 数 = ceil(n_pids / per_state)；至少 1 个
            n_states = max(1, (n_pids + per_state - 1) // per_state)
            # 单 state 或 单点：直接成组
            if n_states == 1 or n_pids <= 2:
                state = self.create_state(group_pids)
                state.manpower = n_pids * 50000
                continue

            # 准备质心矩阵 (n_pids, 2): [y, x]
            pts = np.array(
                [[centers[p][0], centers[p][1]] for p in group_pids],
                dtype=np.float64,
            )
            # 'points' init = 从样本里随机挑 n_states 个点做种子。
            # 用 np.random.seed 固定种子，保证同一项目重复生成结果一致
            # （scipy 不同版本的 seed/rng 关键字名不同，这种方式最兼容）
            np.random.seed(rng_seed)
            try:
                _, labels = kmeans2(pts, n_states, iter=20, minit='points')
            except Exception:
                # 退化场景（如同点过多）—— 兜底为按顺序切块
                labels = np.array([i * n_states // n_pids for i in range(n_pids)])

            # 按 cluster 标签分组建 state
            cluster_to_pids: dict[int, list[int]] = {}
            for pid, lab in zip(group_pids, labels):
                cluster_to_pids.setdefault(int(lab), []).append(pid)
            for chunk in cluster_to_pids.values():
                if not chunk:
                    continue
                state = self.create_state(chunk)
                state.manpower = len(chunk) * 50000

    def build_state_color_map(
        self, province_map: np.ndarray,
        unassigned_highlight: bool = True,
    ) -> np.ndarray:
        """生成 State 颜色图（用于显示）。

        unassigned_highlight=True：未分配到 state 的 land province 高亮为**鲜红色**，
        让用户一眼看到还有哪些省份没分配。
        """
        # 为每个 State 分配确定性颜色
        rng = np.random.RandomState(123)
        colors = {}
        for sid in self._states:
            colors[sid] = (
                int(rng.randint(60, 220)),
                int(rng.randint(60, 220)),
                int(rng.randint(60, 220)),
            )

        # 构建 LUT: province_id → (R, G, B)
        max_pid = int(province_map.max())
        lut = np.zeros((max_pid + 1, 3), dtype=np.uint8)
        # 未分配：鲜红色（高亮）或深灰（不高亮）
        if unassigned_highlight:
            lut[:, :] = (220, 30, 30)  # 鲜红提示"未分配"
        else:
            lut[:, :] = 40  # 深灰

        # pid=0 保持为特殊值（用灰色，避免红色淹没海洋）
        lut[0] = (40, 40, 60)

        for pid, sid in self._province_to_state.items():
            if pid <= max_pid and sid in colors:
                lut[pid] = colors[sid]

        # 应用到整张图
        flat = province_map.ravel()
        flat_clipped = np.clip(flat, 0, max_pid)
        rgb = lut[flat_clipped].reshape(province_map.shape[0], province_map.shape[1], 3)
        return rgb

    def build_state_id_map(self, province_map: np.ndarray) -> np.ndarray:
        """省份图 → state id 图 (0=海洋/未分配), 供名字标签排版用。"""
        max_pid = int(province_map.max())
        lut = np.zeros(max_pid + 1, dtype=np.int32)
        for pid, sid in self._province_to_state.items():
            if pid <= max_pid:
                lut[pid] = sid
        return lut[np.clip(province_map, 0, max_pid)]

    def count_unassigned_provinces(self, all_land_pids: set[int]) -> int:
        """返回还没分配到任何 state 的 land province 数量。"""
        assigned = set(self._province_to_state.keys())
        return len(all_land_pids - assigned)
