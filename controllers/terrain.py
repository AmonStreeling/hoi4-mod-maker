"""TerrainController — 地形编辑模式控制器。

处理省份级地形指定和画笔模式地形绘制。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from controllers.base import BaseController
from commands.map.paint_terrain import PaintTerrainCommand

if TYPE_CHECKING:
    from model.project import Project
    from commands.history import CommandHistory


class TerrainController(BaseController):
    """地形编辑模式：省份指定 / 画笔绘制。"""

    def __init__(self, project: "Project", command_history: "CommandHistory") -> None:
        super().__init__(project, command_history)
        self.current_terrain_index: int = 0
        self.brush_mode: bool = False
        self.brush_size: int = 20
        self.soft_edge: bool = False
        self._stroke_changes: dict[tuple[int, int], int] = {}
        self._is_painting: bool = False

    def activate(self) -> None:
        """进入地形模式。"""
        self._stroke_changes.clear()
        self._is_painting = False
        self._emit_status("地形编辑模式")

    def deactivate(self) -> None:
        """离开地形模式，结束未完成笔触。"""
        if self._is_painting:
            self._commit_stroke()

    def on_province_clicked(self, pid: int) -> None:
        """省份模式下点击省份设置地形。"""
        if self.brush_mode or pid <= 0:
            return

        map_data = self.project.map_data
        province_map = map_data.province_map
        tile_map = map_data.tile_map
        mask = province_map == pid
        ys, xs = np.where(mask)
        if len(ys) == 0:
            return

        # 海洋/湖泊省份不可改地形
        from data.constants import TILE_SEA, TILE_LAKE
        tile_val = int(tile_map[ys[0], xs[0]])
        if tile_val in (TILE_SEA, TILE_LAKE):
            return

        # 收集地形变化
        terrain_map = map_data.terrain_map
        terrain_changes = {}
        for i in range(len(ys)):
            y, x = int(ys[i]), int(xs[i])
            if int(terrain_map[y, x]) != self.current_terrain_index:
                terrain_changes[(y, x)] = self.current_terrain_index

        if not terrain_changes:
            return

        # 不再自动改 provincial_terrain (省份属性是用户精挑细选的, 视觉绘画不该覆盖).
        # 高度也不再联动 — 高度独立于地形视觉, 用户用专门的"从地形反推高度"功能.
        # 想改省份属性 → 切到 provincial_terrain mode 手动指定.
        cmd = PaintTerrainCommand(
            map_data, terrain_changes,
            provincial_terrain_changes=None,
            height_changes=None,
        )
        self.history.execute(cmd)
        self.project.mark_dirty()
        # 视觉地形变了 → colormap 需要重生；改了 height 也触发 normal
        self._invalidate_art_assets(
            "map/terrain/colormap_rgb_cityemissivemask_a.dds",
            "map/world_normal.bmp",
        )
        self._emit_render(full=True)
        from data.terrain_types import PALETTE_TO_TYPE, TERRAIN_TYPES
        tkey = PALETTE_TO_TYPE.get(self.current_terrain_index)
        tname = TERRAIN_TYPES[tkey].name_cn if tkey in TERRAIN_TYPES else "未知"
        self._emit_status(f"省份 {pid} 地形已设为 {tname}")

    def on_press(self, x: int, y: int, pid: int, button: str, modifiers: set) -> bool:
        """画笔模式下鼠标按下。"""
        if not self.brush_mode or button != "left":
            return False
        self._is_painting = True
        self._stroke_changes.clear()
        self._apply_brush(x, y)
        return True

    def on_drag(self, x: int, y: int) -> bool:
        """画笔模式下鼠标拖拽。"""
        if not self._is_painting:
            return False
        self._apply_brush(x, y)
        return True

    def on_release(self, x: int, y: int) -> bool:
        """画笔模式下鼠标释放。"""
        if not self._is_painting:
            return False
        self._commit_stroke()
        return True

    def _apply_brush(self, x: int, y: int) -> None:
        """在 (x, y) 处应用圆形地形画笔 (NumPy 向量化)。"""
        map_data = self.project.map_data
        terrain_map = map_data.terrain_map
        tile_map = map_data.tile_map
        h, w = terrain_map.shape
        r = self.brush_size // 2
        if r < 1:
            r = 1

        # 计算影响区域边界
        y0 = max(0, y - r)
        y1 = min(h, y + r + 1)
        x0 = max(0, x - r)
        x1 = min(w, x + r + 1)

        # 构建子区域坐标网格
        ys = np.arange(y0, y1)
        xs = np.arange(x0, x1)
        yy, xx = np.meshgrid(ys, xs, indexing='ij')

        # 圆形判定
        dist_sq = (yy - y) ** 2 + (xx - x) ** 2
        r_sq = r * r
        circle = dist_sq <= r_sq

        # 软边缘: 外圈 30% 区域随机丢弃
        if self.soft_edge and r > 3:
            inner_r = r * 0.7
            inner_r_sq = inner_r * inner_r
            in_ring = dist_sq > inner_r_sq
            # 距离越远概率越低
            dist = np.sqrt(dist_sq.astype(np.float32))
            prob = 1.0 - (dist - inner_r) / (r - inner_r + 1e-6)
            prob = np.clip(prob, 0, 1)
            random_mask = np.random.random(dist_sq.shape) < prob
            circle = circle & (~in_ring | random_mask)

        # 海/湖保护
        from data.constants import TILE_SEA, TILE_LAKE
        sub_tile = tile_map[y0:y1, x0:x1]
        circle = circle & (sub_tile != TILE_SEA) & (sub_tile != TILE_LAKE)

        # 只改不同的像素
        sub_terrain = terrain_map[y0:y1, x0:x1]
        changed = circle & (sub_terrain != self.current_terrain_index)

        # 收集变化
        coords = np.argwhere(changed)
        for cy, cx in coords:
            self._stroke_changes[(y0 + int(cy), x0 + int(cx))] = self.current_terrain_index

    def _commit_stroke(self) -> None:
        """提交地形笔触 + 单向同步：被涂的 province 多数地形 → provincial_terrain dict。

        画笔涂完一笔后，统计每个被涂的 province 在 terrain_map 上的多数 graphical
        terrain → 推断 provincial type → 更新 dict。这样视觉是主，属性自动跟。
        """
        self._is_painting = False
        if not self._stroke_changes:
            return

        # 算被涂的每个 province 多数地形 → provincial_terrain
        from data.terrain_types import PALETTE_TO_TYPE
        from collections import Counter

        map_data = self.project.map_data
        province_map = map_data.province_map
        terrain_map = map_data.terrain_map

        # 收集被涂的所有 province 像素
        province_changes: dict[int, Counter] = {}
        for (y, x), new_terr_idx in self._stroke_changes.items():
            pid = int(province_map[y, x])
            if pid <= 0:
                continue
            if pid not in province_changes:
                province_changes[pid] = Counter()
            province_changes[pid][new_terr_idx] += 1

        # 不再根据 brush 涂的像素自动改 provincial_terrain
        # (用户的省份属性是精挑细选的, 视觉笔刷不该覆盖).
        # 想改省份属性 → 切到 provincial_terrain mode 手动指定.
        cmd = PaintTerrainCommand(
            map_data, self._stroke_changes,
            provincial_terrain_changes=None,
        )
        self.history.execute(cmd)
        self._stroke_changes = {}
        self.project.mark_dirty()
        self._invalidate_art_assets(
            "map/terrain/colormap_rgb_cityemissivemask_a.dds",
        )
        self._emit_render(full=True)
