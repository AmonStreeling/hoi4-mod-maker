"""LandController — 大陆编辑模式控制器。

处理画笔/橡皮/填充工具绘制 tile_map（陆地/海洋/湖泊）。
支持密度画笔子模式：在 density_map 上涂抹省份密度。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from controllers.base import BaseController
from commands.map.paint_tile import PaintTileCommand
from commands.map.fill_tile import FillTileCommand

if TYPE_CHECKING:
    from model.project import Project
    from commands.history import CommandHistory


class LandController(BaseController):
    """大陆编辑模式：画笔/橡皮/填充/变换 + 密度画笔。"""

    def __init__(self, project: "Project", command_history: "CommandHistory") -> None:
        super().__init__(project, command_history)
        self.current_tool: str = "brush"  # brush / eraser / fill / transform / new_land
        self.current_tile_type: int = 1  # TILE_LAND=1 default
        self.brush_size: int = 5
        self._stroke_changes: dict[tuple[int, int], int] = {}
        self._is_painting: bool = False
        # 密度画笔子模式
        self.density_mode: bool = False
        self.density_value: float = 1.0  # 0.0~1.0
        # 新大陆画笔：记录画了哪些像素
        h, w = project.map_data.tile_map.shape
        self.new_land_mask: np.ndarray = np.zeros((h, w), dtype=bool)

    def reset_mask_size(self) -> None:
        """地图尺寸变化后重置 mask。"""
        h, w = self.project.map_data.tile_map.shape
        self.new_land_mask = np.zeros((h, w), dtype=bool)

    def activate(self) -> None:
        """进入大陆模式，默认画笔工具。有省份时提醒。"""
        self.current_tool = "brush"
        self._stroke_changes.clear()
        self._is_painting = False
        has_provinces = int(self.project.map_data.province_map.max()) > 0
        if has_provinces:
            self._emit_status(
                "⚠ 已有省份 — 画新陆地后切到「省份」模式点生成，选「Yes」= 只给新区域生成"
            )
        else:
            self._emit_status("大陆编辑模式")

    def deactivate(self) -> None:
        """离开大陆模式，结束未完成笔触。"""
        if self._is_painting:
            self._commit_stroke()
        self.density_mode = False

    def on_press(self, x: int, y: int, pid: int, button: str, modifiers: set) -> bool:
        """鼠标按下开始画笔或填充。"""
        if button != "left":
            return False

        # 密度画笔模式
        if self.density_mode:
            self._is_painting = True
            self._apply_density_brush(x, y)
            return True

        if self.current_tool == "fill":
            self._do_fill(x, y)
            return True

        if self.current_tool in ("brush", "eraser", "new_land"):
            self._is_painting = True
            self._stroke_changes.clear()
            self._apply_brush(x, y)
            return True

        return False

    def on_drag(self, x: int, y: int) -> bool:
        """鼠标拖拽继续画笔。"""
        if not self._is_painting:
            return False
        if self.density_mode:
            self._apply_density_brush(x, y)
        else:
            self._apply_brush(x, y)
        return True

    def on_release(self, x: int, y: int) -> bool:
        """鼠标释放结束画笔笔触。"""
        if not self._is_painting:
            return False
        if self.density_mode:
            self._is_painting = False
            self._emit_render(full=True)
        else:
            self._commit_stroke()
        return True

    # ── 新大陆画笔 ──

    @property
    def new_land_pixel_count(self) -> int:
        return int(self.new_land_mask.sum())

    def clear_new_land_mask(self) -> None:
        """生成省份后清空 mask，新大陆变旧大陆。"""
        self.new_land_mask[:] = False

    # ── 密度画笔 ──

    def _apply_density_brush(self, x: int, y: int) -> None:
        """在密度图上涂抹。"""
        map_data = self.project.map_data
        if map_data.density_map is None:
            from data.constants import MAP_WIDTH, MAP_HEIGHT
            map_data.density_map = np.full(
                (MAP_HEIGHT, MAP_WIDTH), 0.5, dtype=np.float32
            )

        dm = map_data.density_map
        h, w = dm.shape
        r = self.brush_size // 2
        y0, y1 = max(0, y - r), min(h, y + r + 1)
        x0, x1 = max(0, x - r), min(w, x + r + 1)
        yy, xx = np.ogrid[y0:y1, x0:x1]
        circle = (yy - y) ** 2 + (xx - x) ** 2 <= r * r
        dm[y0:y1, x0:x1][circle] = self.density_value

    # ── 普通画笔 ──

    def _apply_brush(self, x: int, y: int) -> None:
        """在 (x, y) 处应用圆形画笔/橡皮/新大陆画笔。"""
        from data.constants import TILE_SEA, TILE_LAND
        map_data = self.project.map_data
        tile_map = map_data.tile_map
        h, w = tile_map.shape
        r = self.brush_size // 2
        r_sq = r * r

        if self.current_tool == "new_land":
            tile_value = TILE_LAND
        elif self.current_tool == "eraser":
            tile_value = TILE_SEA
        else:
            tile_value = self.current_tile_type

        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if r >= 2 and dy * dy + dx * dx > r_sq:
                    continue
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w:
                    if int(tile_map[ny, nx]) != tile_value:
                        self._stroke_changes[(ny, nx)] = tile_value
                        # 新大陆画笔：只记录真正从海/湖变陆地的像素，旧陆地不记
                        if self.current_tool == "new_land":
                            self.new_land_mask[ny, nx] = True

    def _commit_stroke(self) -> None:
        """提交笔触为一个 Command。"""
        self._is_painting = False
        if self._stroke_changes:
            cmd = PaintTileCommand(self.project.map_data, self._stroke_changes)
            self.history.execute(cmd)
            self._stroke_changes = {}
            self.project.mark_dirty()
            # 陆海划分变了 → colormap / fow / world_normal / cities 需要重生
            self._invalidate_art_assets(
                "map/terrain/colormap_rgb_cityemissivemask_a.dds",
                "map/terrain/colormap_water_0.dds",
                "map/terrain/colormap_water_1.dds",
                "map/terrain/colormap_water_2.dds",
                "map/terrain/fow_rgb_waterspec_a.dds",
                "map/world_normal.bmp",
            )
            self._emit_render(full=True)

    def _do_fill(self, x: int, y: int) -> None:
        """洪水填充。"""
        from scipy.ndimage import label

        map_data = self.project.map_data
        tile_map = map_data.tile_map
        h, w = tile_map.shape
        if not (0 <= y < h and 0 <= x < w):
            return

        old_val = int(tile_map[y, x])
        new_val = self.current_tile_type
        if old_val == new_val:
            return

        mask = tile_map == old_val
        labeled, _ = label(mask)
        region_id = labeled[y, x]
        fill_mask = labeled == region_id

        cmd = FillTileCommand(map_data, fill_mask, new_val)
        self.history.execute(cmd)
        self.project.mark_dirty()
        self._invalidate_art_assets(
            "map/terrain/colormap_rgb_cityemissivemask_a.dds",
            "map/terrain/colormap_water_0.dds",
            "map/terrain/colormap_water_1.dds",
            "map/terrain/colormap_water_2.dds",
            "map/terrain/fow_rgb_waterspec_a.dds",
            "map/world_normal.bmp",
        )
        self._emit_render(full=True)
