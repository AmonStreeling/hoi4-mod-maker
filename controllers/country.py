"""CountryController — 国家编辑模式控制器。

处理国家创建、领土分配、首都设置、属性编辑。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from controllers.base import BaseController
from commands.country.assign import AssignStateToCountryCommand
from commands.country.create import CreateCountryCommand
from commands.country.delete import DeleteCountryCommand

if TYPE_CHECKING:
    from model.project import Project
    from commands.history import CommandHistory


class CountryController(BaseController):
    """国家编辑模式。"""

    def __init__(self, project: "Project", command_history: "CommandHistory") -> None:
        super().__init__(project, command_history)
        self.selected_country_tag: str = ""
        # False = 信息模式(默认): 点击地图查看该处国家, 不改归属
        # True  = 分配领土模式: 点击州分配给当前选中国家
        self.assign_mode: bool = False
        # 始终监听省份重新生成
        self.event_bus.subscribe("province_map_regenerated", self._on_province_regen)

    def _on_province_regen(self, event) -> None:
        """省份全量重新生成 → 清除所有国家数据。"""
        if not event.data.get("incremental"):
            self.project.country_mgr.clear()
            self.selected_country_tag = ""
            self.event_bus.emit("country_changed", tag="", action="refresh")

    def activate(self) -> None:
        """进入国家模式，刷新颜色图。"""
        self._emit_status("国家编辑模式")
        self.event_bus.emit("country_changed", tag="", action="refresh")

    def deactivate(self) -> None:
        """离开国家模式：退回信息模式, 防止回来时误点改归属。"""
        if self.assign_mode:
            self.assign_mode = False
            self.event_bus.emit(
                "country_changed", tag="", action="assign_mode_reset")

    def set_assign_mode(self, on: bool) -> None:
        """切换 分配领土 / 信息 模式（页面按钮回调）。"""
        self.assign_mode = bool(on)
        if on:
            self._emit_status(
                "分配领土模式：点击地图上的州分配给当前选中的国家（Ctrl+Z 撤销可归还原主）")
        else:
            self._emit_status("信息模式：点击地图查看该处的国家")

    def on_province_clicked(self, pid: int) -> None:
        """点击省份：信息模式查看该处国家; 分配模式把所在 State 分给选中国家。"""
        if pid <= 0:
            return
        if not self.assign_mode:
            self._show_country_at(pid)
            return
        if not self.selected_country_tag:
            self._emit_status("请先在国家列表选中一个国家，再分配领土")
            return

        state_mgr = self.project.state_mgr
        country_mgr = self.project.country_mgr

        state_id = state_mgr.get_state_of_province(pid)
        if state_id <= 0:
            self._emit_status("该省份未分配到任何 State")
            return

        # 获取旧的所有者 (undo 时归还给它)
        old_tag = country_mgr.get_owner_of_state(state_id)

        if old_tag == self.selected_country_tag:
            return  # 已属于此国家

        cmd = AssignStateToCountryCommand(
            country_mgr, state_id, old_tag, self.selected_country_tag,
        )
        self.history.execute(cmd)
        self.project.mark_dirty()

        self.event_bus.emit(
            "country_changed",
            tag=self.selected_country_tag,
            action="modified",
        )
        self._emit_status(
            f"State {state_id} 已分配给 {self.selected_country_tag}"
        )

    def _show_country_at(self, pid: int) -> None:
        """信息模式：查该省所在州属于哪个国家并选中它（面板显示可编辑信息）。"""
        state_id = self.project.state_mgr.get_state_of_province(pid)
        if state_id <= 0:
            self._emit_status("该省份未分配到任何 State")
            return
        tag = self.project.country_mgr.get_owner_of_state(state_id)
        if tag:
            country = self.project.country_mgr.get_country(tag)
            self.select_country(tag)
            self._emit_status(f"{tag}（{country.name}）— 左侧面板可编辑该国信息")
        else:
            self._emit_status(f"State {state_id} 尚未分配给任何国家")

    def on_province_right_clicked(self, pid: int, x: int, y: int) -> None:
        """右键省份：设为当前国家的首都。"""
        if pid <= 0 or not self.selected_country_tag:
            if not self.selected_country_tag:
                self._emit_status("请先在国家模式下选中一个国家")
            return

        tag = self.selected_country_tag
        country_mgr = self.project.country_mgr
        country_mgr.set_capital(tag, pid)
        self.project.mark_dirty()

        self.event_bus.emit("country_changed", tag=tag, action="modified")
        self._emit_status(f"{tag} 的首都已设为省份 {pid}")

    def create_country(
        self,
        tag: str,
        name: str,
        color: tuple[int, int, int],
        party: str = "neutrality",
    ) -> bool:
        """创建新国家。返回是否成功。"""
        tag = tag.upper().strip()[:3]
        if len(tag) != 3 or not tag.isalpha():
            self._emit_status("TAG 必须是 3 个英文字母")
            return False

        cmd = CreateCountryCommand(
            self.project.country_mgr,
            tag, name or tag, color, party,
        )
        try:
            self.history.execute(cmd)
        except ValueError as e:
            self._emit_status(f"创建国家失败: {e}")
            return False

        self.project.mark_dirty()
        self.selected_country_tag = tag
        self.event_bus.emit("country_changed", tag=tag, action="created")
        self._emit_status(f"国家 {tag} ({name}) 已创建")
        return True

    def select_country(self, tag: str) -> None:
        """选中国家。"""
        self.selected_country_tag = tag
        country = self.project.country_mgr.get_country(tag)
        if country:
            self.event_bus.emit(
                "country_changed", tag=tag, action="selected",
            )

    def delete_country(self, tag: str) -> None:
        """删除国家. 同时清理所有指向该国的 state owner. 走 command 支持 undo."""
        country_mgr = self.project.country_mgr
        if not tag or country_mgr.get_country(tag) is None:
            self._emit_status(f"国家 {tag} 不存在")
            return
        cmd = DeleteCountryCommand(country_mgr, tag)
        self.history.execute(cmd)
        if self.selected_country_tag == tag:
            self.selected_country_tag = ""
        self.project.mark_dirty()
        self.event_bus.emit("country_changed", tag=tag, action="deleted")
        self._emit_status(f"已删除国家 {tag}")

    def change_property(self, tag: str, prop: str, value: str) -> None:
        """修改国家属性。"""
        country_mgr = self.project.country_mgr
        country = country_mgr.get_country(tag)
        if not country:
            return

        if prop == "name":
            country.name = str(value)
        elif prop == "ruling_party":
            country_mgr.set_ruling_party(tag, str(value))

        self.project.mark_dirty()
        self.event_bus.emit("country_changed", tag=tag, action="modified")

    def change_color(self, tag: str, color: tuple[int, int, int]) -> None:
        """修改国家颜色。"""
        country = self.project.country_mgr.get_country(tag)
        if not country:
            return
        country.color = color
        self.project.mark_dirty()
        self.event_bus.emit("country_changed", tag=tag, action="modified")
        self._emit_status(f"{tag} 颜色已修改")
