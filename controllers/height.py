"""HeightController — 高度编辑模式控制器。

处理按省份设置高度值。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from controllers.base import BaseController
from commands.map.set_height import SetHeightCommand

if TYPE_CHECKING:
    from model.project import Project
    from commands.history import CommandHistory


class HeightController(BaseController):
    """高度编辑模式：点击省份设置高度。"""

    def __init__(self, project: "Project", command_history: "CommandHistory") -> None:
        super().__init__(project, command_history)
        self.current_height_value: int = 100

    def activate(self) -> None:
        """进入高度模式。"""
        self._emit_status("高度编辑模式")

    def on_province_clicked(self, pid: int) -> None:
        """点击省份设置高度值。"""
        if pid <= 0:
            return

        map_data = self.project.map_data
        province_map = map_data.province_map
        mask = province_map == pid

        if not np.any(mask):
            return

        cmd = SetHeightCommand(map_data, mask, self.current_height_value)
        self.history.execute(cmd)
        self.project.mark_dirty()
        # 高度变了 → world_normal 必须重生（法线从高度图算）; colormap/fow 也略受影响
        self._invalidate_art_assets(
            "map/world_normal.bmp",
            "map/terrain/colormap_rgb_cityemissivemask_a.dds",
            "map/terrain/fow_rgb_waterspec_a.dds",
        )
        self._emit_render(full=True)
        self._emit_status(f"省份 {pid} 高度已设为 {self.current_height_value}")
