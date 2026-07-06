"""
ResplitStateCommand — 重新分割一个州内的省份。

效果: 清掉该州全部省份, 在州的原像素范围内按目标数量重新生成,
     新省份自动归回该州 (owner/国家领土不变)。
适用: 州模式"重新分割此州的省份"按钮。
调用: cmd = ResplitStateCommand(map_data, state_mgr, sid, target_count);
     cmd_history.execute(cmd) — 支持 undo/redo。

实现要点:
- 州外已有的未分配像素 (新画陆地等) 先临时标 -1 保护, 生成完恢复,
  保证增量生成器只在州内动土
- 首次 execute 跑生成并缓存结果 (zlib), redo 直接回放, 结果确定
- 州的 VP/省份级建筑随老省份 ID 一起清空 (undo 可恢复)
"""

from __future__ import annotations

import zlib

import numpy as np

from commands.base import Command


class ResplitStateCommand(Command):
    label = "重新分割州内省份"

    def __init__(self, map_data, state_mgr, state_id: int, target_count: int) -> None:
        self._map_data = map_data
        self._state_mgr = state_mgr
        self._sid = int(state_id)
        self._target = max(1, int(target_count))
        # execute 时填充
        self._old_pm: bytes = b""
        self._new_pm: bytes = b""
        self._shape: tuple[int, ...] = ()
        self._old_state_snap: dict | None = None
        self._new_state_snap: dict | None = None
        self._old_p2s: dict[int, int] = {}
        self._new_pids: list[int] = []

    # ── 状态快照工具 ──

    def _snap_state(self) -> dict:
        s = self._state_mgr.get_state(self._sid)
        return {
            "provinces": list(s.provinces),
            "victory_points": dict(s.victory_points),
            "vp_names": dict(s.vp_names),
            "vp_names_en": dict(getattr(s, "vp_names_en", {}) or {}),
            "province_buildings": {k: dict(v) for k, v in s.province_buildings.items()},
        }

    def _apply_state_snap(self, snap: dict, pids_in_map: list[int]) -> None:
        s = self._state_mgr.get_state(self._sid)
        s.provinces = list(snap["provinces"])
        s.victory_points = dict(snap["victory_points"])
        s.vp_names = dict(snap["vp_names"])
        s.vp_names_en = dict(snap["vp_names_en"])
        s.province_buildings = {k: dict(v) for k, v in snap["province_buildings"].items()}
        # province → state 反查表同步
        p2s = self._state_mgr._province_to_state
        for pid in pids_in_map:
            p2s.pop(pid, None)
        for pid in s.provinces:
            p2s[pid] = self._sid

    # ── Command 接口 ──

    def execute(self) -> None:
        pm = self._map_data.province_map
        if self._new_pm:
            # redo: 直接回放首次生成的结果
            pm[:] = self._decompress(self._new_pm)
            self._apply_state_snap(self._new_state_snap, self._old_state_snap["provinces"])
            return

        state = self._state_mgr.get_state(self._sid)
        old_pids = [p for p in state.provinces if p > 0]
        if not old_pids:
            return

        self._shape = pm.shape
        self._old_pm = zlib.compress(pm.tobytes(), level=1)
        self._old_state_snap = self._snap_state()

        mask = np.isin(pm, old_pids)
        n_pixels = int(mask.sum())
        if n_pixels == 0:
            return
        prev_max = int(pm.max())  # 清除前的全图最大 id, 新 id 必须排在其后

        # 保护州外已有的未分配像素, 只让生成器处理州内
        protect = pm == 0
        pm[mask] = 0
        if protect.any():
            pm[protect] = -1

        from domain.generators.province import generate_provinces_incremental
        density = max(1.0, n_pixels / self._target)
        new_pm, _total = generate_provinces_incremental(
            self._map_data.tile_map, pm,
            target_density=density, skip_mismatch_clear=True,
        )
        if protect.any():
            new_pm[protect] = 0
        pm[:] = new_pm

        # 州内新生成的 id 可能复用了刚删掉的旧编号 (生成器从当前 max+1 起编)
        # → 统一平移到清除前的全图最大 id 之后, 避免铁路/补给等旧引用错接
        gen_ids = sorted(int(i) for i in np.unique(pm[mask]) if i > 0)
        lut = np.arange(int(pm.max()) + 1, dtype=np.int32)
        for i, gid in enumerate(gen_ids):
            lut[gid] = prev_max + 1 + i
        pm[mask] = lut[pm[mask]]
        self._new_pids = [prev_max + 1 + i for i in range(len(gen_ids))]

        # 新省份归回该州; VP/省份级建筑随老 ID 作废
        state.provinces = list(self._new_pids)
        state.victory_points = {}
        state.vp_names = {}
        state.vp_names_en = {}
        state.province_buildings = {}
        p2s = self._state_mgr._province_to_state
        for pid in old_pids:
            p2s.pop(pid, None)
        for pid in self._new_pids:
            p2s[pid] = self._sid

        self._new_pm = zlib.compress(pm.tobytes(), level=1)
        self._new_state_snap = self._snap_state()

    def undo(self) -> None:
        if not self._old_pm:
            return
        self._map_data.province_map[:] = self._decompress(self._old_pm)
        self._apply_state_snap(self._old_state_snap, self._new_pids)

    def _decompress(self, blob: bytes) -> np.ndarray:
        raw = zlib.decompress(blob)
        return np.frombuffer(raw, dtype=np.int32).reshape(self._shape)
