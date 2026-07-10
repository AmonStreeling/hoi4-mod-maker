"""
右键省份弹出菜单 — 集中所有省份快捷操作。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt5.QtWidgets import QMenu, QApplication
from PyQt5.QtCore import QPoint

from data.terrain_types import (
    TERRAIN_TYPES, GRAPHICAL_TERRAIN_BY_INDEX,
    graphical_terrain_display_name,
)
from ui.i18n import tr

if TYPE_CHECKING:
    from model.project import Project
    from views.canvas.widget import MapCanvas


class ProvinceContextMenu:
    """右键省份弹出菜单。"""

    def __init__(
        self,
        project: "Project",
        controllers: dict[str, object],
        canvas: "MapCanvas",
        open_state_detail=None,
    ) -> None:
        self._project = project
        self._controllers = controllers
        self._canvas = canvas
        # 回调: (state_id) → 打开州详情对话框 (资源/建筑), 由 MainWindow 注入
        self._open_state_detail = open_state_detail

    def show(self, pid: int, screen_pos: QPoint) -> None:
        """在指定屏幕位置弹出菜单。"""
        if pid <= 0:
            return

        menu = QMenu()

        # ── 省份信息 ──
        info_action = menu.addAction(tr("context_province_info", pid))
        info_action.setEnabled(False)
        menu.addSeparator()

        # ── 地形设置 ──
        terrain_menu = menu.addMenu(tr("context_set_terrain"))
        terrain_actions: dict[object, int] = {}
        for gt in sorted(GRAPHICAL_TERRAIN_BY_INDEX.values(), key=lambda g: g.palette_index):
            if gt.type in ("ocean", "lakes"):
                continue
            act = terrain_menu.addAction(f"{graphical_terrain_display_name(gt)} ({gt.type})")
            terrain_actions[act] = gt.palette_index

        menu.addSeparator()

        # ── State 相关 ──
        state_id = self._project.state_mgr.get_state_of_province(pid)
        vp_action = None
        capital_action = None
        copy_action = None
        detail_action = None

        if state_id:
            state_info = menu.addAction(tr("context_belongs_state", state_id))
            state_info.setEnabled(False)

            detail_action = menu.addAction(tr("context_edit_state_detail"))
            vp_action = menu.addAction(tr("context_set_vp"))

            tag = self._project.country_mgr.get_owner_of_state(state_id)
            if tag:
                country_info = menu.addAction(tr("context_belongs_country", tag))
                country_info.setEnabled(False)

            capital_action = menu.addAction(tr("context_set_capital"))
        else:
            no_state = menu.addAction(tr("context_unassigned_state"))
            no_state.setEnabled(False)

        menu.addSeparator()
        copy_action = menu.addAction(tr("context_copy_province_id"))

        # ── 执行 ──
        chosen = menu.exec_(screen_pos)
        if chosen is None:
            return

        self._handle_action(
            chosen, pid, terrain_actions, vp_action, capital_action,
            copy_action, detail_action, state_id,
        )

    def _handle_action(
        self,
        action: object,
        pid: int,
        terrain_actions: dict[object, int],
        vp_action: object | None,
        capital_action: object | None,
        copy_action: object | None,
        detail_action: object | None = None,
        state_id: int = 0,
    ) -> None:
        # 州详情 (资源/建筑)
        if action is detail_action and detail_action is not None:
            if self._open_state_detail is not None and state_id:
                self._open_state_detail(state_id)
            return

        # 地形
        if action in terrain_actions:
            palette_idx = terrain_actions[action]
            self._set_terrain(pid, palette_idx)
            return

        # VP
        if action is vp_action:
            self._set_vp(pid)
            return

        # 首都
        if action is capital_action:
            self._set_capital(pid)
            return

        # 复制 ID
        if action is copy_action:
            clipboard = QApplication.clipboard()
            if clipboard is not None:
                clipboard.setText(str(pid))
            return

    def _set_terrain(self, pid: int, palette_idx: int) -> None:
        """整个省份设为指定地形。"""
        import numpy as np
        pm = self._canvas.province_map
        mask = pm == pid
        self._canvas.terrain_map[mask] = palette_idx

        from data.terrain_types import PALETTE_TO_TYPE, TERRAIN_TYPES as TT
        ptype = PALETTE_TO_TYPE.get(palette_idx)
        if ptype:
            self._canvas._map_data.provincial_terrain[pid] = ptype
            if ptype in TT:
                self._canvas.height_map[mask] = TT[ptype].height_base

        self._canvas.refresh_display()

    def _set_vp(self, pid: int) -> None:
        """弹出对话框设置胜利点数值 + 城市名。"""
        ctrl = self._controllers.get("state")
        if ctrl is None:
            return
        state_mgr = ctrl.project.state_mgr
        sid = state_mgr.get_state_of_province(pid)
        state = state_mgr.get_state(sid) if sid > 0 else None
        cur_vp = state.victory_points.get(pid, 0) if state else 0
        cur_name = state.vp_names.get(pid, "") if state else ""

        from views.vp_dialog import ask_vp
        value, name, ok = ask_vp(self._canvas.window(), pid, cur_vp, cur_name)
        if ok:
            ctrl.set_vp(pid, value, name)

    def _set_capital(self, pid: int) -> None:
        """设为国家首都。"""
        ctrl = self._controllers.get("country")
        if ctrl is not None:
            ctrl.on_province_right_clicked(pid, 0, 0)
