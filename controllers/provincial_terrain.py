"""ProvincialTerrainController — 只改 province 的 gameplay terrain（不动视觉/高度）。

复用 PaintTerrainCommand（已支持只传 provincial_terrain_changes）。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from controllers.base import BaseController
from commands.map.paint_terrain import PaintTerrainCommand
from ui.i18n import tr

if TYPE_CHECKING:
    from model.project import Project
    from commands.history import CommandHistory


class ProvincialTerrainController(BaseController):
    """点 province → 改它的 provincial_terrain dict（不动 terrain.bmp / height_map）。

    默认是查看模式：点 province 只显示信息（走 app_controller 的省份查询）。
    开启分配模式后：点 province 改地形。
    """

    def __init__(self, project: "Project", command_history: "CommandHistory") -> None:
        super().__init__(project, command_history)
        self.current_type: str = "plains"
        self.assign_mode: bool = False  # 默认查看模式

    def activate(self) -> None:
        self._emit_status(tr("status_pterrain_view"))

    def deactivate(self) -> None:
        pass

    def set_type(self, type_name: str) -> None:
        self.current_type = type_name
        if self.assign_mode:
            self._emit_status(tr("status_pterrain_selected", type_name))
        else:
            self._emit_status(tr("status_pterrain_selected_view", type_name))

    def set_assign_mode(self, enabled: bool) -> None:
        self.assign_mode = enabled
        if enabled:
            self._emit_status(tr("status_pterrain_assign_on", self.current_type))
        else:
            self._emit_status(tr("status_pterrain_view_on"))

    def on_province_clicked(self, pid: int) -> None:
        if pid <= 0:
            return
        # 查看模式：不改数据，让 app_controller 的省份信息显示处理即可
        if not self.assign_mode:
            return

        map_data = self.project.map_data
        province_map = map_data.province_map
        tile_map = map_data.tile_map

        # 海洋/湖泊省份不能改
        from data.constants import TILE_SEA, TILE_LAKE
        ys, xs = np.where(province_map == pid)
        if len(ys) == 0:
            return
        tile_val = int(tile_map[ys[0], xs[0]])
        if tile_val in (TILE_SEA, TILE_LAKE):
            self._emit_status(tr("status_pterrain_sea_skip", pid))
            return

        # 复用 PaintTerrainCommand，只传 provincial_terrain_changes
        cmd = PaintTerrainCommand(
            map_data,
            terrain_changes={},
            height_changes=None,
            provincial_terrain_changes={pid: self.current_type},
        )
        self.history.execute(cmd)
        self.project.mark_dirty()
        self._emit_render(full=True)
        self._emit_status(tr("status_pterrain_applied", pid, self.current_type))

    def sync_from_visual(self) -> None:
        """从视觉地形 (terrain.bmp) 重新推断全部陆地省份的属性地形。

        效果: 每个陆地省份的属性 = 它在 terrain_map 上的多数地形, 覆盖手动设置。
        适用: 自动生成/重画视觉地形后, 想让属性层全量跟上时。
        调用: 属性地形 page 的同步按钮 (点击前 page 已弹二次确认); 可撤销。
        """
        from services.terrain_service import compute_provincial_terrain_from_bmp

        map_data = self.project.map_data
        inferred = compute_provincial_terrain_from_bmp(
            map_data.terrain_map, map_data.province_map, map_data.tile_map,
        )
        changes = {
            pid: terr for pid, terr in inferred.items()
            if map_data.provincial_terrain.get(pid) != terr
        }
        if not changes:
            self._emit_status(tr("status_pterrain_sync_nochange"))
            return

        cmd = PaintTerrainCommand(
            map_data,
            terrain_changes={},
            height_changes=None,
            provincial_terrain_changes=changes,
        )
        cmd.label = "同步属性地形"
        self.history.execute(cmd)
        self.project.mark_dirty()
        self._emit_render(full=True)
        self._emit_status(tr("status_pterrain_synced", len(changes)))
