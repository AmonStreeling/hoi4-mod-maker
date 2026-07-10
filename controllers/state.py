"""StateController — State 编辑模式控制器。

处理省份分配到 State、State 属性编辑、VP 设置、自动分组。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from controllers.base import BaseController
from commands.state.assign import AssignProvinceToStateCommand
from commands.state.delete import DeleteStateCommand
from commands.state.set_property import SetStatePropertyCommand
from commands.state.set_vp import SetVPCommand
from data.constants import TILE_LAND

if TYPE_CHECKING:
    from model.project import Project
    from commands.history import CommandHistory


class StateController(BaseController):
    """State 编辑模式。"""

    def __init__(self, project: "Project", command_history: "CommandHistory") -> None:
        super().__init__(project, command_history)
        self.selected_state_id: int = 0
        self.assign_mode: bool = False  # False=查看模式, True=分配模式
        # 始终监听省份重新生成（不管当前模式）
        self.event_bus.subscribe("province_map_regenerated", self._on_province_regen)

    def _is_land_province(self, pid: int) -> bool:
        """多数决判定陆地省份 — State 只能包含陆地省，不能吞并海洋/湖泊。"""
        if pid <= 0:
            return False
        map_data = self.project.map_data
        mask = (map_data.province_map == pid)
        total = int(mask.sum())
        if total == 0:
            return False
        land_count = int(((map_data.tile_map == TILE_LAND) & mask).sum())
        return land_count * 2 > total

    def _on_province_regen(self, event) -> None:
        """省份全量重新生成 → 清除所有 State 数据。"""
        if not event.data.get("incremental"):
            self.project.state_mgr.clear()
            self.selected_state_id = 0
            self.event_bus.emit("state_changed", state_id=0, action="refresh")

    def activate(self) -> None:
        """进入 State 模式，刷新颜色图。"""
        self._emit_status("State 编辑模式")
        self.event_bus.emit("state_changed", state_id=0, action="refresh")

    def deactivate(self) -> None:
        """离开 State 模式，清除高亮。"""
        self.assign_mode = False
        self.event_bus.emit("clear_batch_selection")

    def on_province_clicked(self, pid: int) -> None:
        """点击省份 → 查看该省份所属州的信息（不直接分配）。

        如果省份未分配到任何州 → 提示。
        如果 assign_mode=True → 分配到当前选中州。
        """
        if pid <= 0:
            return

        state_mgr = self.project.state_mgr
        sid = state_mgr.get_state_of_province(pid)

        # 分配模式：把省份加到选中的州
        if self.assign_mode and self.selected_state_id > 0:
            if sid == self.selected_state_id:
                return
            if not self._is_land_province(pid):
                self._emit_status(f"省份 {pid} 是海洋/湖泊，不能加入 State（State 只含陆地）")
                return
            cmd = AssignProvinceToStateCommand(
                state_mgr, pid, sid, self.selected_state_id,
            )
            self.history.execute(cmd)
            self.project.mark_dirty()
            self.event_bus.emit(
                "state_changed",
                state_id=self.selected_state_id,
                action="modified",
                property="assign",
            )
            self._emit_status(f"省份 {pid} 已分配到 State {self.selected_state_id}")
            # 刷新高亮（省份变了，选中州的范围也变了）
            updated = state_mgr.get_state(self.selected_state_id)
            if updated:
                self.event_bus.emit("state_changed", state_id=self.selected_state_id, action="selected")
            return

        # 查看模式：点击省份 → 选中其所属州 → 显示信息
        if sid > 0:
            self.selected_state_id = sid
            state = state_mgr.get_state(sid)
            name = state.name if state else f"STATE_{sid}"
            prov_count = len(state.provinces) if state else 0
            self._emit_status(f"州 #{sid} \"{name}\" ({prov_count} 省份)")
            self.event_bus.emit(
                "state_changed", state_id=sid, action="selected",
            )
        else:
            self._emit_status(f"省份 {pid} 未分配到任何州（红色高亮区域）")

    def on_province_double_clicked(self, pid: int) -> None:
        """双击省份设置 VP。通过事件通知 UI 弹对话框。"""
        if pid <= 0:
            return

        state_mgr = self.project.state_mgr
        sid = state_mgr.get_state_of_province(pid)
        if sid == 0:
            self._emit_status("该省份未分配到任何 State，请先分组")
            return

        # 通知 UI 弹 VP 对话框（controller 不直接弹 Qt 对话框）
        self.event_bus.emit("vp_dialog_requested", pid=pid, state_id=sid)

    def delete_state(self, sid: int) -> None:
        """删除指定 state, 同步清理 country owner 引用. 走 command 支持 undo."""
        state_mgr = self.project.state_mgr
        country_mgr = self.project.country_mgr
        if sid <= 0 or state_mgr.get_state(sid) is None:
            self._emit_status(f"State {sid} 不存在")
            return
        cmd = DeleteStateCommand(state_mgr, country_mgr, sid)
        self.history.execute(cmd)
        if self.selected_state_id == sid:
            self.selected_state_id = 0
        self.project.mark_dirty()
        self.event_bus.emit("state_changed", state_id=sid, action="deleted")
        self._emit_status(f"已删除 State {sid}")

    def set_vp(self, pid: int, value: int, name: str = "") -> None:
        """设置省份的 VP 值 + 城市名（由 UI 对话框回调调用）。"""
        state_mgr = self.project.state_mgr

        # 获取旧值
        sid = state_mgr.get_state_of_province(pid)
        state = state_mgr.get_state(sid) if sid > 0 else None
        old_vp = state.victory_points.get(pid) if state else None

        new_vp = value if value > 0 else None

        cmd = SetVPCommand(state_mgr, pid, old_vp, new_vp)
        self.history.execute(cmd)

        # 保存城市名 (对话框传空名字 = 清掉旧名)
        if new_vp:
            state_mgr.set_vp(pid, value, name)
            if not name and state is not None:
                state.vp_names[pid] = ""
        self.project.mark_dirty()

        if new_vp:
            label = f"省份 {pid} 设为 {value} VP"
            if name:
                label += f" ({name})"
            self._emit_status(label)
        else:
            self._emit_status(f"省份 {pid} VP 已移除")
        self.event_bus.emit("vp_changed", pid=pid, value=value)

    def auto_states(self, per_state: int) -> None:
        """自动分组省份为 State。"""
        state_mgr = self.project.state_mgr
        map_data = self.project.map_data

        state_mgr.auto_split(
            map_data.province_map,
            map_data.tile_map,
            per_state,
        )
        self.project.mark_dirty()

        count = len(state_mgr.states)
        self._emit_status(f"State 分组完成: {count} 个")
        self.event_bus.emit("state_changed", state_id=0, action="refresh")

    def select_state(self, state_id: int) -> None:
        """选中 State。"""
        self.selected_state_id = state_id
        state = self.project.state_mgr.get_state(state_id)
        if state:
            self.event_bus.emit(
                "state_changed",
                state_id=state_id,
                action="selected",
            )

    # ── 批量建州 ──

    def create_state_from_provinces(self, province_ids: list[int]) -> int:
        """从选中的省份列表创建新州。返回新州 ID。海洋/湖泊省份会被过滤掉。"""
        if not province_ids:
            return 0

        # 过滤掉非陆地省份（State 只能含陆地）
        land_pids = [p for p in province_ids if self._is_land_province(p)]
        skipped = len(province_ids) - len(land_pids)
        if not land_pids:
            self._emit_status("所选省份全部是海洋/湖泊，未创建 State")
            return 0
        if skipped > 0:
            self._emit_status(f"已跳过 {skipped} 个海洋/湖泊省份")
        province_ids = land_pids

        state_mgr = self.project.state_mgr

        # 从旧州移除这些省份
        for pid in province_ids:
            old_sid = state_mgr.get_state_of_province(pid)
            if old_sid > 0:
                old_state = state_mgr.get_state(old_sid)
                if old_state and pid in old_state.provinces:
                    old_state.provinces.remove(pid)
                    state_mgr._province_to_state.pop(pid, None)

        # 通过正规接口创建新州（自动分配 ID + 更新索引）
        new_state = state_mgr.create_state(provinces=list(province_ids))
        new_state.name = f"STATE_{new_state.id}"

        self.project.mark_dirty()
        self._emit_status(f"创建州 {new_state.id}（{len(province_ids)} 个省份）")
        self.event_bus.emit("state_changed", state_id=new_state.id, action="refresh")
        return new_state.id

    def change_property(self, state_id: int, prop: str, value: Any) -> None:
        """修改 State 属性（通过 Command 支持撤销）。"""
        state_mgr = self.project.state_mgr
        state = state_mgr.get_state(state_id)
        if not state:
            return

        old_value = getattr(state, prop, None)
        if old_value == value:
            return

        # 类型转换
        if prop == "manpower":
            value = int(value)
        else:
            value = str(value)

        cmd = SetStatePropertyCommand(state_mgr, state_id, prop, old_value, value)
        self.history.execute(cmd)
        self.project.mark_dirty()
        self.event_bus.emit(
            "state_changed", state_id=state_id, action="modified",
        )
