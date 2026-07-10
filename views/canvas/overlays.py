"""
叠加层 Mixin — 省份边界/VP标记/变换框/套索/画笔光标
从 canvas_widget.py 拆分而来
"""
import numpy as np
from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import (
    QImage, QPixmap, QPainter, QColor, QPen, QPainterPath, QBrush,
)

# 国家/州归属 overlay 允许显示的模式（基础视图本身不按国家/州染色的那些）。
# 允许"国家色 + 州边界"叠加层的模式
# state/country 自身已按归属染色 → overlay 在这两个模式下只画边界不再填色
CS_OVERLAY_ALLOWED_MODES = frozenset({
    "land", "terrain", "height", "river", "province",
    "logistics", "colormap", "default_map", "province_terrain",
    "state", "country",
})

class OverlayMixin:
    """叠加层相关方法。假设 self 拥有:
    - _province_pixmap_item, _province_map, _selected_province_id
    - _show_provinces, _display_mode
    - _vp_overlay_item, _vp_data, _map_data
    - _transform_border, _transform_handles, _transform_box, _zoom
    - _lasso_path_item, _lasso_overlay, _framework_ctx
    - _brush_cursor, _current_tool, _brush_size
    """

    def _rebuild_border_cache(self) -> None:
        """重建省份边界缓存 + base QPixmap（只在省份数据变化时调用）。"""
        if self._province_map.max() == 0:
            self._border_cache = None
            self._border_base_pixmap = None
            return
        h, w = self._province_map.shape
        borders = np.zeros((h, w), dtype=bool)
        borders[:-1, :] |= self._province_map[:-1, :] != self._province_map[1:, :]
        borders[:, :-1] |= self._province_map[:, :-1] != self._province_map[:, 1:]
        self._border_cache = borders
        # 生成 base pixmap（只做一次，不用每次 copy 46MB）
        rgba = np.zeros((h, w, 4), dtype=np.uint8)
        rgba[borders, 3] = 180
        img = QImage(rgba.data, w, h,
                     w * 4, QImage.Format.Format_ARGB32)
        img._ref = rgba
        self._border_base_pixmap = QPixmap.fromImage(img)

    def _render_province_overlay(self) -> None:
        """渲染省份边界叠加层（base pixmap + 高亮用 QPainter 画）"""
        if not self._show_provinces or self._province_map.max() == 0:
            self._province_pixmap_item.setVisible(False)
            return

        if not hasattr(self, '_border_cache') or self._border_cache is None:
            self._rebuild_border_cache()
        if not hasattr(self, '_border_base_pixmap') or self._border_base_pixmap is None:
            self._rebuild_border_cache()

        # 从 base pixmap 复制（QPixmap copy 很快，不涉及 numpy）
        result = QPixmap(self._border_base_pixmap)

        # 高亮选中省份（用 QPainter 画黄色边框，不操作 numpy 数组）
        sel = self._selected_province_id
        if sel > 0:
            ys, xs = np.where(self._province_map == sel)
            if len(ys) > 0:
                y0 = max(0, int(ys.min()) - 1)
                y1 = min(self.map_h, int(ys.max()) + 2)
                x0 = max(0, int(xs.min()) - 1)
                x1 = min(self.map_w, int(xs.max()) + 2)

                # 在小区域内算高亮边界
                sub = self._province_map[y0:y1, x0:x1]
                sel_mask = sub == sel
                sel_border = np.zeros_like(sel_mask)
                sel_border[:-1, :] |= sel_mask[:-1, :] != sel_mask[1:, :]
                sel_border[1:, :]  |= sel_mask[:-1, :] != sel_mask[1:, :]
                sel_border[:, :-1] |= sel_mask[:, :-1] != sel_mask[:, 1:]
                sel_border[:, 1:]  |= sel_mask[:, :-1] != sel_mask[:, 1:]

                # 画黄色高亮到小区域
                h_rgba = np.zeros((y1 - y0, x1 - x0, 4), dtype=np.uint8)
                h_rgba[sel_border] = (0, 230, 255, 255)  # BGRA: yellow
                h_img = QImage(h_rgba.data, x1 - x0, y1 - y0,
                              (x1 - x0) * 4, QImage.Format.Format_ARGB32)
                h_img._ref = h_rgba

                painter = QPainter(result)
                painter.drawImage(x0, y0, h_img)
                painter.end()
        self._province_pixmap_item.setPixmap(result)
        self._province_pixmap_item.setVisible(True)

    def show_state_borders(self, visible: bool, state_mgr=None) -> None:
        """显示/隐藏 State 着色 + 边界叠加层（用于战略区域选州模式）。

        半透明 State 颜色填充 + 白色边界线，确保能清楚看到每个 State。
        """
        overlay = getattr(self, '_state_border_overlay', None)
        if overlay is None:
            return
        if not visible:
            overlay.setVisible(False)
            return
        if state_mgr is None or self._province_map.max() == 0:
            overlay.setVisible(False)
            return

        # 构建省份→州 ID 映射表
        max_pid = int(self._province_map.max())
        pid_to_sid = np.zeros(max_pid + 1, dtype=np.int32)
        for sid, state in state_mgr._states.items():
            for pid in state.provinces:
                if 0 < pid <= max_pid:
                    pid_to_sid[pid] = sid

        # 通过 LUT 把 province_map 转成 state_map
        pm = np.clip(self._province_map, 0, max_pid)
        state_map = pid_to_sid[pm]

        h, w = state_map.shape

        # 为每个 state 生成确定性颜色（半透明填充）
        max_sid = int(state_map.max()) + 1
        # 用黄金比例散列生成区分度高的颜色
        color_lut = np.zeros((max_sid, 4), dtype=np.uint8)
        for sid in range(1, max_sid):
            hue = (sid * 137) % 360  # 黄金角散列
            # 简易 HSV→RGB (S=0.5, V=0.9)
            h_i = hue // 60
            f = (hue % 60) / 60.0
            v, s = 230, 0.5
            p = int(v * (1 - s))
            q = int(v * (1 - s * f))
            t = int(v * (1 - s * (1 - f)))
            v = int(v)
            if h_i == 0:   r, g, b = v, t, p
            elif h_i == 1: r, g, b = q, v, p
            elif h_i == 2: r, g, b = p, v, t
            elif h_i == 3: r, g, b = p, q, v
            elif h_i == 4: r, g, b = t, p, v
            else:          r, g, b = v, p, q
            color_lut[sid] = (b, g, r, 90)  # BGRA, alpha=90 半透明

        # 填充 state 颜色
        rgba = color_lut[state_map]

        # 计算 state 边界（白色亮线）
        borders = np.zeros((h, w), dtype=bool)
        borders[:-1, :] |= state_map[:-1, :] != state_map[1:, :]
        borders[1:, :]  |= state_map[:-1, :] != state_map[1:, :]
        borders[:, :-1] |= state_map[:, :-1] != state_map[:, 1:]
        borders[:, 1:]  |= state_map[:, :-1] != state_map[:, 1:]
        rgba[borders] = (200, 200, 200, 110)  # 弱化白 (灰白半透明)

        img = QImage(rgba.data, w, h, w * 4, QImage.Format.Format_ARGB32)
        img._ref = rgba
        overlay.setPixmap(QPixmap.fromImage(img))
        overlay.setVisible(True)

    def refresh_terrain_underlay(self) -> None:
        """根据 source / display_mode 重建地形底图叠加层.

        source = 'height': 彩色高度图 LUT (深蓝/绿/黄/棕/白) — 看山脉/海岸
        source = 'terrain': 地形分类 LUT (HOI4 标准地形色) — 看 plains/forest/mountain 分布
        透明度滑块控制和 state/country 颜色的混合度.
        """
        from views.canvas.luts import _HEIGHT_COLOR_LUT, _TERRAIN_COLOR_LUT
        item = getattr(self, "_terrain_underlay_item", None)
        if item is None:
            return
        visible = getattr(self, "_terrain_underlay_visible", False)
        if not visible or self._display_mode not in ("state", "country"):
            item.setVisible(False)
            return

        source = getattr(self, "_terrain_underlay_source", "height")
        if source == "terrain":
            # 用省份属性 (provincial_terrain) 颜色 — 用户精挑细选的真实地形分类
            pt_rgb = getattr(self, "_provincial_terrain_color_rgb", None)
            if pt_rgb is None:
                item.setVisible(False)
                return
            h, w = pt_rgb.shape[:2]
            rgba = np.zeros((h, w, 4), dtype=np.uint8)
            rgba[:, :, 0] = pt_rgb[:, :, 2]  # B
            rgba[:, :, 1] = pt_rgb[:, :, 1]  # G
            rgba[:, :, 2] = pt_rgb[:, :, 0]  # R
            rgba[:, :, 3] = 255
        else:
            hm = getattr(self, "_height_map", None)
            if hm is None:
                item.setVisible(False)
                return
            rgba = np.ascontiguousarray(_HEIGHT_COLOR_LUT[hm])
            h, w = hm.shape

        img = QImage(rgba.data, w, h, w * 4, QImage.Format.Format_ARGB32)
        img._ref = rgba
        item.setPixmap(QPixmap.fromImage(img))
        item.setOpacity(getattr(self, "_terrain_underlay_opacity", 0.5))
        item.setVisible(True)

    def show_terrain_context_overlay(
        self, visible: bool, country_mgr=None, state_mgr=None,
    ) -> None:
        """开关"半透明国家色 + 白色州边界"叠加层（全局视图开关，非地形专属）。"""
        self._terrain_context_visible = bool(visible)
        if country_mgr is not None:
            self._terrain_ctx_country_mgr = country_mgr
        if state_mgr is not None:
            self._terrain_ctx_state_mgr = state_mgr
        self.refresh_terrain_context_overlay()

    def refresh_terrain_context_overlay(self) -> None:
        """根据缓存 mgrs 重建 overlay pixmap；不改 visible 开关，只按当前模式决定显隐。"""
        overlay = getattr(self, '_terrain_context_overlay', None)
        if overlay is None:
            return
        visible = getattr(self, '_terrain_context_visible', False)
        if not visible or self._display_mode not in CS_OVERLAY_ALLOWED_MODES:
            overlay.setVisible(False)
            return
        country_mgr = getattr(self, '_terrain_ctx_country_mgr', None)
        state_mgr = getattr(self, '_terrain_ctx_state_mgr', None)
        if country_mgr is None or state_mgr is None:
            overlay.setVisible(False)
            return
        pm_max = int(self._province_map.max()) if self._province_map is not None else 0
        if pm_max <= 0:
            overlay.setVisible(False)
            return

        h, w = self._province_map.shape
        max_pid = pm_max

        # state/country 模式下底图已经按归属染色，overlay 不再填国家色，只画边界
        borders_only = self._display_mode in ("state", "country")

        # pid → (state_id, bgra 颜色) 两张 LUT
        pid_to_sid = np.zeros(max_pid + 1, dtype=np.int32)
        pid_to_color = np.zeros((max_pid + 1, 4), dtype=np.uint8)  # BGRA
        countries = getattr(country_mgr, "countries", {}) or {}
        states = getattr(state_mgr, "states", {}) or {}
        get_owner = getattr(country_mgr, "get_owner_of_state", lambda _sid: "")
        for sid, state in states.items():
            if borders_only:
                bgra = (0, 0, 0, 0)  # 完全透明 — 只保留州边界线效果
            else:
                owner_tag = get_owner(sid)
                if owner_tag and owner_tag in countries:
                    c = countries[owner_tag].color
                    r, g, b = int(c[0]) & 0xFF, int(c[1]) & 0xFF, int(c[2]) & 0xFF
                    bgra = (b, g, r, 110)
                else:
                    bgra = (90, 90, 90, 55)  # 未分配国家：淡灰
            for pid in state.provinces:
                if 0 < pid <= max_pid:
                    pid_to_sid[pid] = sid
                    pid_to_color[pid] = bgra

        pm = np.clip(self._province_map, 0, max_pid)
        rgba = pid_to_color[pm]           # 填色 (H, W, 4) BGRA
        state_map = pid_to_sid[pm]        # (H, W) int32

        # 州边界（白色亮线）: 用 !=右 与 !=下 两个方向，覆盖到左右上下 4 边
        borders = np.zeros((h, w), dtype=bool)
        diff_v = state_map[:-1, :] != state_map[1:, :]
        diff_h = state_map[:, :-1] != state_map[:, 1:]
        borders[:-1, :] |= diff_v
        borders[1:, :]  |= diff_v
        borders[:, :-1] |= diff_h
        borders[:, 1:]  |= diff_h
        rgba[borders] = (255, 255, 255, 220)

        # ascontiguousarray 保证 QImage 拿到的 buffer 连续 (fancy-index 已经连续,这里是防御性)
        rgba = np.ascontiguousarray(rgba)
        img = QImage(rgba.data, w, h, w * 4, QImage.Format.Format_ARGB32)
        img._ref = rgba
        overlay.setPixmap(QPixmap.fromImage(img))
        overlay.setVisible(True)

    def set_vp_data(self, vp_dict: dict[int, int], name_dict: dict[int, str] | None = None) -> None:
        """设置 VP 数据 {province_id: vp_value} + 城市名 {province_id: name}"""
        self._vp_data = dict(vp_dict)
        self._vp_names = dict(name_dict) if name_dict else {}
        self._vp_cache_dirty = True
        self._update_vp_visibility()

    def _update_vp_visibility(self) -> None:
        """根据当前模式显示/隐藏 VP 叠加层，只在数据变化时重绘"""
        if self._display_mode not in ("state", "province") or not self._vp_data:
            self._vp_overlay_item.setVisible(False)
            return
        if getattr(self, '_vp_cache_dirty', True):
            # 确保质心缓存存在
            if self._map_data and not getattr(self._map_data, '_centroid_cache', None):
                self._map_data.build_centroid_cache()
            self._render_vp_overlay()
            self._vp_cache_dirty = False
        self._vp_overlay_item.setVisible(True)

    def _render_vp_overlay(self) -> None:
        """渲染 VP 标记叠加层（仅在 VP 数据变化时调用，结果缓存）"""
        if not self._vp_data:
            return

        # 创建透明画布
        img = QImage(self.map_w, self.map_h, QImage.Format.Format_ARGB32)
        img.fill(QColor(0, 0, 0, 0))
        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        from PyQt5.QtGui import QFont
        name_font = QFont("Microsoft YaHei")
        name_font.setPixelSize(12)
        name_font.setBold(True)
        painter.setFont(name_font)

        for pid, vp_val in self._vp_data.items():
            if vp_val <= 0:
                continue
            centroid = self._map_data.get_province_centroid(pid)
            if centroid is None:
                continue
            cx, cy = centroid

            # 极小红点（1px 圆）
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(220, 30, 30)))
            painter.drawEllipse(cx - 1, cy - 1, 3, 3)

            # 城市名: 红点右侧, 深色描边 + 白字 (放大画布才读得清, 和游戏一致)
            name = self._vp_names.get(pid, "")
            if name:
                painter.setPen(QColor(20, 20, 20, 200))
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    painter.drawText(cx + 5 + dx, cy + 4 + dy, name)
                painter.setPen(QColor(255, 255, 255, 235))
                painter.drawText(cx + 5, cy + 4, name)

        painter.end()
        self._vp_overlay_item.setPixmap(QPixmap.fromImage(img))

    def _update_transform_visuals(self) -> None:
        """根据 _transform_box 更新变换框和 handle 位置。"""
        if not self._transform_box:
            self._transform_border.setVisible(False)
            for h in self._transform_handles.values():
                h.setVisible(False)
            return

        x0, y0, x1, y1 = self._transform_box
        self._transform_border.setRect(QRectF(x0, y0, x1 - x0, y1 - y0))
        self._transform_border.setVisible(True)

        positions = {"tl": (x0, y0), "tr": (x1, y0), "bl": (x0, y1), "br": (x1, y1)}
        for hid, (hx, hy) in positions.items():
            self._transform_handles[hid].setPos(hx, hy)
            self._transform_handles[hid].setVisible(True)

    def _hit_test_transform(self, sx: float, sy: float) -> str | None:
        """判断点击位置在变换框的哪个部分。返回 "move"/"tl"/"tr"/"bl"/"br"/None."""
        if not self._transform_box:
            return None
        x0, y0, x1, y1 = self._transform_box
        handle_r = 10 / self._zoom  # handle 热区半径（屏幕像素转场景像素）

        # 检查 4 个角 handle
        for hid, (hx, hy) in [("tl", (x0, y0)), ("tr", (x1, y0)),
                               ("bl", (x0, y1)), ("br", (x1, y1))]:
            if abs(sx - hx) < handle_r and abs(sy - hy) < handle_r:
                return hid

        # 检查是否在框内（移动）
        if x0 <= sx <= x1 and y0 <= sy <= y1:
            return "move"

        # 框外附近 = 旋转（距离框边 < 30px）
        margin = 30 / self._zoom
        if (x0 - margin <= sx <= x1 + margin and y0 - margin <= sy <= y1 + margin):
            return "rotate"
        return None

    def _show_expand_overlay(self) -> None:
        """显示选中省份的 allowed 区域（半透明黄色）+ 进入扩张时变成绿色。"""
        if self._framework_ctx is None:
            return
        mask = self._framework_ctx.state.get("allowed_mask")
        if mask is None:
            return
        active = self._framework_ctx.state.get("active", False)
        # active 状态用绿色（提示"现在能画了"），未 active 用黄色（提示"再点一次进入"）
        color = (50, 220, 80, 70) if active else (255, 230, 0, 60)
        rgba = np.zeros((self.map_h, self.map_w, 4), dtype=np.uint8)
        rgba[mask] = color
        img = QImage(rgba.data, self.map_w, self.map_h,
                     self.map_w * 4, QImage.Format.Format_ARGB32)
        img._ref = rgba
        self._lasso_overlay.setPixmap(QPixmap.fromImage(img))
        self._lasso_overlay.setVisible(True)
        # 不显示路径线
        self._lasso_path_item.setVisible(False)

    def _clear_lasso_visual(self) -> None:
        """清除所有套索反馈元素。"""
        self._lasso_path_item.setPath(QPainterPath())
        self._lasso_path_item.setVisible(False)
        self._lasso_overlay.setVisible(False)

    def _update_brush_cursor(self, sx: int, sy: int) -> None:
        """更新画笔预览光标位置和大小。"""
        self._brush_cursor_pos = (sx, sy)  # 记住位置, 滑块调大小时就地刷新
        density_on = getattr(self, '_density_overlay_visible', False)
        terrain_brush_on = (self._display_mode == "terrain"
                            and self._terrain_brush_mode)
        height_brush_on = (self._display_mode == "height"
                           and getattr(self, '_height_brush_mode', 'off') != "off")
        show_brush = (
            (self._current_tool in ("brush", "eraser", "new_land")
             and self._display_mode in ("land", "river"))
            or density_on or terrain_brush_on or height_brush_on
        )

        if show_brush:
            # 各画笔模式用各自独立的尺寸
            if density_on:
                bs = getattr(self, '_density_brush_size', 30)
            elif terrain_brush_on:
                bs = self._terrain_brush_size
            elif height_brush_on:
                bs = self._height_brush_size
            else:
                bs = self._brush_size
            r = bs // 2
            self._brush_cursor.setRect(sx - r, sy - r, bs, bs)
            self._brush_cursor.setVisible(True)
        else:
            self._brush_cursor.setVisible(False)

    def _refresh_brush_cursor(self) -> None:
        """画笔大小滑块拖动时就地刷新预览圈, 不必等鼠标移动。"""
        pos = getattr(self, '_brush_cursor_pos', None)
        if pos is not None:
            self._update_brush_cursor(*pos)

    # ── 密度叠加层 ──

    def _render_density_overlay(self) -> None:
        """渲染密度图为半透明热力图叠加在地图上。"""
        density = getattr(self._map_data, 'density_map', None) if self._map_data else None
        overlay_item = getattr(self, '_density_overlay_item', None)
        if overlay_item is None:
            return

        if density is None or not getattr(self, '_density_overlay_visible', False):
            overlay_item.setVisible(False)
            return

        h, w = density.shape
        # 转 RGBA 热力图：低密度=蓝透明，高密度=红不透明
        rgba = np.zeros((h, w, 4), dtype=np.uint8)
        d = np.clip(density, 0, 1)
        rgba[:, :, 0] = (d * 255).astype(np.uint8)          # R: 高密度→红
        rgba[:, :, 2] = ((1 - d) * 200).astype(np.uint8)    # B: 低密度→蓝
        rgba[:, :, 3] = 100                                   # 半透明

        img = QImage(rgba.data, w, h, w * 4, QImage.Format.Format_RGBA8888)
        overlay_item.setPixmap(QPixmap.fromImage(img.copy()))
        overlay_item.setVisible(True)

    def set_density_overlay_visible(self, visible: bool) -> None:
        """开关密度叠加层。"""
        self._density_overlay_visible = visible
        if visible:
            # 确保 density_map 存在
            if self._map_data and self._map_data.density_map is None:
                self._map_data.density_map = np.full(
                    (self.map_h, self.map_w), 0.5, dtype=np.float32
                )
            self._render_density_overlay()
        else:
            overlay_item = getattr(self, '_density_overlay_item', None)
            if overlay_item:
                overlay_item.setVisible(False)
