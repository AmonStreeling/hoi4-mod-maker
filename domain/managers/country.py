"""
国家管理器 — 创建/编辑国家、分配领土、设首都
"""
import numpy as np
from dataclasses import dataclass, field


@dataclass
class NationalSpirit:
    """民族精神 / 国家 idea"""
    id: str                       # idea ID（建议 TAG_xxx 格式）
    name: str                     # 显示名（本地化）
    desc: str = ""                # 描述（本地化）
    modifiers: dict[str, float] = field(default_factory=dict)  # {modifier_key: value}
    picture: str = "generic_pp_unaligned"


@dataclass
class CountryData:
    """一个国家的数据"""
    tag: str                     # 3字母代码，如 KAR
    name: str = ""               # 显示名称
    color: tuple[int, int, int] = (100, 100, 200)  # RGB 颜色
    capital: int = 0             # 首都省份 ID
    ruling_party: str = "neutrality"  # neutrality/democratic/fascism/communism
    popularities: dict[str, int] = field(default_factory=lambda: {
        "democratic": 10,
        "fascism": 5,
        "communism": 5,
        "neutrality": 80,
    })
    national_spirits: list[NationalSpirit] = field(default_factory=list)

    def __post_init__(self):
        if not self.name:
            self.name = self.tag


RULING_PARTIES = ["neutrality", "democratic", "fascism", "communism"]


class CountryManager:
    """管理所有国家"""

    def __init__(self):
        self._countries: dict[str, CountryData] = {}
        self._state_owner: dict[int, str] = {}  # state_id → tag

    @property
    def countries(self) -> dict[str, CountryData]:
        return self._countries

    def get_country(self, tag: str) -> CountryData | None:
        return self._countries.get(tag)

    def get_owner_of_state(self, state_id: int) -> str:
        """获取 State 的所有者 TAG，空字符串=未分配"""
        return self._state_owner.get(state_id, "")

    def create_country(
        self, tag: str, name: str = "", color: tuple[int, int, int] = (100, 100, 200),
        allow_vanilla_tag: bool = False,
    ) -> CountryData:
        """创建国家。

        allow_vanilla_tag: 用户从零新建国家时必须为 False (vanilla TAG 撞车
        会被游戏数据覆盖); 导入 vanilla/MOD 时为 True — 导入的国家本来就是
        vanilla TAG, 拒绝它们会导致一个国家都建不出来。
        """
        tag = tag.upper()[:3]
        if len(tag) != 3:
            raise ValueError("TAG 必须是 3 个字符")
        if not tag.isalnum():
            raise ValueError("TAG 只能包含字母和数字")
        # BUG-6b: 拒绝 vanilla TAG (避免热那亚→Krakow 类撞车)
        if not allow_vanilla_tag:
            from data.constants import is_vanilla_tag
            if is_vanilla_tag(tag):
                raise ValueError(
                    f"TAG '{tag}' 与 vanilla 国家撞车，HOI4 会用 vanilla 数据覆盖你的国家"
                    f"（如名字、颜色、idea 等）。请改用其他 3 字符组合，"
                    f"建议含数字以避开 vanilla：例如 X01, K42, Z99 等。"
                )
        country = CountryData(tag=tag, name=name or tag, color=color)
        self._countries[tag] = country
        return country

    def remove_country(self, tag: str) -> None:
        """删除国家"""
        self._countries.pop(tag, None)
        # 清除该国家的领土
        to_remove = [sid for sid, t in self._state_owner.items() if t == tag]
        for sid in to_remove:
            del self._state_owner[sid]

    def assign_state(self, state_id: int, tag: str) -> None:
        """将 State 分配给国家"""
        if tag and tag in self._countries:
            self._state_owner[state_id] = tag
        elif not tag:
            self._state_owner.pop(state_id, None)

    def remap_state_ids(self, mapping: dict[int, int]) -> None:
        """配合 StateManager.compact_ids: 把 _state_owner 里的 state ID 按 mapping 替换.

        old → new 映射里没出现的 state ID 视为已被删除, 一起从 _state_owner 移除.
        """
        if not mapping:
            return
        new_owner: dict[int, str] = {}
        for old_sid, tag in self._state_owner.items():
            new_sid = mapping.get(old_sid)
            if new_sid is not None:
                new_owner[new_sid] = tag
        self._state_owner = new_owner

    def set_capital(self, tag: str, province_id: int) -> None:
        """设置首都"""
        if tag in self._countries:
            self._countries[tag].capital = province_id

    def set_ruling_party(self, tag: str, party: str) -> None:
        """设置执政党"""
        if tag in self._countries and party in RULING_PARTIES:
            self._countries[tag].ruling_party = party

    def set_popularity(self, tag: str, party: str, value: int) -> None:
        """设置某政党支持率"""
        if tag in self._countries:
            self._countries[tag].popularities[party] = max(0, min(100, value))

    def get_states_of_country(self, tag: str) -> list[int]:
        """获取某国家的所有 State ID"""
        return [sid for sid, t in self._state_owner.items() if t == tag]

    def clear(self) -> None:
        """清空所有数据"""
        self._countries.clear()
        self._state_owner.clear()

    def build_country_color_map(
        self,
        province_map: np.ndarray,
        state_manager,  # StateManager 实例
        tile_map: np.ndarray | None = None,
    ) -> np.ndarray:
        """生成国家颜色图（用于显示）。

        未分配到国家的 state 使用 state 自己的颜色（**去饱和 + 变暗**），
        避免和国家色混淆，同时让用户在国家模式下能看清 state 边界，
        一眼知道还有哪些 state 需要分配。
        """
        from data.constants import TILE_LAND

        max_pid = int(province_map.max())
        # 默认：海/未归 state 的省 = 深蓝（和大陆模式一致，避免跟灰色陆地混淆）
        lut = np.full((max_pid + 1, 3), (30, 40, 70), dtype=np.uint8)

        # 识别陆地省份（多数决，避免沾边像素误判）—— 只有陆地省才会被涂国家色/state 色
        is_land_arr: np.ndarray | None = None
        if tile_map is not None:
            pid_flat = province_map.ravel()
            land_flat = (tile_map == TILE_LAND).ravel()
            land_count = np.bincount(pid_flat, weights=land_flat, minlength=max_pid + 1)
            total_count = np.bincount(pid_flat, minlength=max_pid + 1)
            is_land_arr = land_count * 2 > total_count

        # 和 state manager 同种子，保证 state 颜色稳定
        rng = np.random.RandomState(123)
        state_colors: dict[int, tuple[int, int, int]] = {}
        for sid in state_manager.states:
            state_colors[sid] = (
                int(rng.randint(60, 220)),
                int(rng.randint(60, 220)),
                int(rng.randint(60, 220)),
            )

        # 标记 pid 是否属于"已分配国家"的 land province (供 country renderer 画白边时过滤)
        assigned_lut = np.zeros(max_pid + 1, dtype=bool)
        for sid, state in state_manager.states.items():
            tag = self._state_owner.get(sid, "")
            assigned = bool(tag and tag in self._countries)
            if assigned:
                color = self._countries[tag].color
            else:
                sr, sg, sb = state_colors.get(sid, (100, 100, 100))
                gray = (sr + sg + sb) // 3
                mix = 0.6
                color = (
                    int((sr * (1 - mix) + gray * mix) * 0.7),
                    int((sg * (1 - mix) + gray * mix) * 0.7),
                    int((sb * (1 - mix) + gray * mix) * 0.7),
                )
            for pid in state.provinces:
                if pid <= max_pid:
                    # 只涂真陆地省; 海洋省误加进 state 也保持蓝
                    if is_land_arr is None or is_land_arr[pid]:
                        lut[pid] = color
                        if assigned:
                            assigned_lut[pid] = True

        flat = province_map.ravel()
        flat_clipped = np.clip(flat, 0, max_pid)
        rgb = lut[flat_clipped].reshape(province_map.shape[0], province_map.shape[1], 3)
        # 第二个返回: assigned mask (H, W) — True 表示该像素是"已分配国家"的 land
        assigned_mask = assigned_lut[flat_clipped].reshape(rgb.shape[0], rgb.shape[1])
        return rgb, assigned_mask

    def build_country_index_map(
        self, province_map: np.ndarray, state_manager,
    ) -> tuple[np.ndarray, dict[int, str]]:
        """省份图 → 国家序号图 (0=未分配) + {序号: 国家名}, 供名字标签排版用。"""
        tags = sorted(self._countries)
        tag_idx = {t: i + 1 for i, t in enumerate(tags)}
        names = {i + 1: (self._countries[t].name or t) for i, t in enumerate(tags)}
        max_pid = int(province_map.max())
        lut = np.zeros(max_pid + 1, dtype=np.int32)
        for sid, state in state_manager.states.items():
            idx = tag_idx.get(self._state_owner.get(sid, ""), 0)
            if idx:
                for pid in state.provinces:
                    if pid <= max_pid:
                        lut[pid] = idx
        idx_map = lut[np.clip(province_map, 0, max_pid)]
        return idx_map, names

    def get_country_list(self) -> list[tuple[str, str, tuple[int, int, int]]]:
        """返回 [(tag, name, color), ...] 用于 UI 列表"""
        return [(c.tag, c.name, c.color) for c in self._countries.values()]
