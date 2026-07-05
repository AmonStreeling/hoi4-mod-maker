"""
输入事件路由 Mixin — 鼠标/键盘事件处理
从 canvas_widget.py 拆分而来
"""
from PyQt5.QtWidgets import QGraphicsView
from PyQt5.QtCore import Qt, QRectF, QTimer
from PyQt5.QtGui import QMouseEvent, QWheelEvent

from data.constants import (
    TILE_SEA, TILE_LAKE,
    ZOOM_MIN, ZOOM_MAX, ZOOM_STEP,
)
from data.terrain_types import TERRAIN_TYPES, PALETTE_TO_TYPE


class InputMixin:
    """鼠标/键盘事件处理方法。假设 self 拥有 MapCanvas 的全部状态属性。"""

    def _ensure_continuous_brush_timer(self):
        """懒初始化连续画笔 timer (按住鼠标不动也能持续画)."""
        if not hasattr(self, "_continuous_brush_timer"):
            self._continuous_brush_timer = QTimer(self)
            self._continuous_brush_timer.setInterval(50)  # 50ms ≈ 20Hz, 流畅且不卡
            self._continuous_brush_timer.timeout.connect(self._on_continuous_brush_tick)
            self._continuous_brush_pos: tuple[int, int] | None = None

    def _on_continuous_brush_tick(self):
        """timer 触发: 在最后记录的位置补画一笔 (鼠标不动时使用)."""
        pos = getattr(self, "_continuous_brush_pos", None)
        if pos is None or not self._is_drawing:
            return
        sx, sy = pos
        if 0 <= sx < self.map_w and 0 <= sy < self.map_h:
            self._paint_at(sx, sy)

    def _start_continuous_brush(self, sx: int, sy: int) -> None:
        """开始连续画笔 (按住时一直触发)."""
        self._ensure_continuous_brush_timer()
        self._continuous_brush_pos = (sx, sy)
        self._continuous_brush_timer.start()

    def _stop_continuous_brush(self) -> None:
        """停止连续画笔 (鼠标释放时调用)."""
        timer = getattr(self, "_continuous_brush_timer", None)
        if timer is not None:
            timer.stop()
        self._continuous_brush_pos = None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._is_panning = True
            self._pan_start = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return

        # 框选模式拦截
        if self._selection_mode and event.button() == Qt.MouseButton.LeftButton:
            sx, sy = self._scene_pos(event)
            self._selection_start = (int(sx), int(sy))
            self._selection_rect_item.setRect(QRectF(sx, sy, 0, 0))
            self._selection_rect_item.setVisible(True)
            event.accept()
            return

        # Ctrl+左键：拖拽移动参考图
        if (event.button() == Qt.MouseButton.LeftButton
                and event.modifiers() & Qt.ControlModifier):
            self._ref_dragging = True
            self._ref_drag_start = event.pos()
            self.setCursor(Qt.CursorShape.SizeAllCursor)
            event.accept()
            return

        # 框架工具分发（新规范）
        if (event.button() == Qt.MouseButton.LeftButton
                and self._framework_tool is not None
                and not self._space_pressed):
            sx, sy = self._scene_pos(event)
            if 0 <= sx < self.map_w and 0 <= sy < self.map_h:
                self._framework_ctx.dirty_bbox = None
                self._framework_tool.begin_undo(self._framework_ctx)
                self._framework_tool.on_press(self._framework_ctx, sx, sy)
                self._is_drawing = True

                # 扩张工具可视反馈：选中省份后显示 allowed 区域 overlay
                if self._framework_ctx.state.get("pid"):
                    self._show_expand_overlay()

                self.stroke_started.emit()
                self._render_province_overlay()
                event.accept()
                return

        if event.button() == Qt.MouseButton.LeftButton:
            if self._space_pressed or self._current_tool == "pan":
                self._is_panning = True
                self._pan_start = event.pos()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                event.accept()
                return

            # 变换工具
            if self._current_tool == "transform" and self._display_mode == "land":
                sx, sy = self._scene_pos(event)

                if self._transform_active:
                    # 已有变换框 — 判断点击位置
                    hit = self._hit_test_transform(sx, sy)
                    if hit:
                        self._transform_drag = hit
                        self._transform_drag_start = (sx, sy)
                        self._transform_box_start = tuple(self._transform_box)
                        self._transform_angle_start = self._transform_angle
                        if hit == "move":
                            self.setCursor(Qt.CursorShape.SizeAllCursor)
                        elif hit == "rotate":
                            self.setCursor(Qt.CursorShape.CrossCursor)
                        else:
                            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
                        event.accept()
                        return
                    else:
                        # 点击远处框外 = 确认变换
                        self._apply_transform()
                        self.stroke_ended.emit()
                        self._end_transform()
                        event.accept()
                        return

                # 没有变换框 — 开始框选
                self._transform_selecting = True
                self._selection_start = (int(sx), int(sy))
                self._selection_rect_item.setRect(QRectF(sx, sy, 0, 0))
                self._selection_rect_item.setVisible(True)
                self.stroke_started.emit()
                event.accept()
                return

            # 高度模式 + 山脉画线：拖拽收集点（但高度画笔优先级更高 — 用户点了画笔说明不想画山脉）
            if (self._display_mode == "height"
                    and getattr(self, '_ridge_mode', False)
                    and getattr(self, '_height_brush_mode', 'off') == "off"):
                sx, sy = self._scene_pos(event)
                if 0 <= sx < self.map_w and 0 <= sy < self.map_h:
                    self._is_drawing = True
                    self._ridge_drawing = True
                    self._ridge_path = [(int(sy), int(sx))]
                    # 初始化红线路径预览
                    from PyQt5.QtGui import QPainterPath
                    path = QPainterPath()
                    path.moveTo(sx, sy)
                    self._ridge_path_item.setPath(path)
                    self._ridge_path_item.setVisible(True)
                    self.stroke_started.emit()
                event.accept()
                return

            # 高度/地形模式 + 套索（精修 or 选区降级）: 拖拽收集闭合多边形
            # 两种模式共享同一套 drawing 代码, 只在 release 时走不同信号
            _active_lasso = None
            if (self._display_mode == "height"
                    and getattr(self, '_refine_lasso_mode', False)
                    and getattr(self, '_height_brush_mode', 'off') == "off"):
                _active_lasso = "refine"
            elif (self._display_mode == "terrain"
                    and getattr(self, '_downgrade_lasso_mode', False)):
                _active_lasso = "downgrade"
            if _active_lasso is not None:
                sx, sy = self._scene_pos(event)
                if 0 <= sx < self.map_w and 0 <= sy < self.map_h:
                    self._is_drawing = True
                    self._refine_lasso_drawing = True
                    self._active_lasso_kind = _active_lasso
                    self._refine_lasso_path = [(int(sy), int(sx))]
                    from PyQt5.QtGui import QPainterPath
                    path = QPainterPath()
                    path.moveTo(sx, sy)
                    self._refine_lasso_item.setPath(path)
                    self._refine_lasso_item.setVisible(True)
                    self.stroke_started.emit()
                event.accept()
                return

            # 地形/高度/State/Country/后勤/战略区/属性地形 模式：点击省份 → 委托 controller 处理
            if self._display_mode in ("terrain", "height", "state", "country",
                                       "province_terrain", "logistics", "strategic_region",
                                       "continent"):
                sx, sy = self._scene_pos(event)
                if 0 <= sx < self.map_w and 0 <= sy < self.map_h:
                    pid = int(self._province_map[sy, sx])
                    # 高度画笔模式：逐像素抬升/下沉/平滑（即使落在 pid=0 也处理，例如新陆地）
                    if (self._display_mode == "height"
                            and getattr(self, '_height_brush_mode', 'off') != "off"):
                        self._is_drawing = True
                        self.stroke_started.emit()
                        self._paint_at(sx, sy)
                        event.accept()
                        return
                    if pid > 0:
                        # 地形画笔模式：逐像素绘制 + 按住鼠标不动持续画
                        if self._display_mode == "terrain" and self._terrain_brush_mode:
                            self._is_drawing = True
                            self.stroke_started.emit()
                            self._paint_at(sx, sy)
                            self._start_continuous_brush(sx, sy)
                            event.accept()
                            return
                        self.province_clicked.emit(pid)
                        # 可拖拽分配的模式: 开始拖拽 (controller 内部按 assign_mode 决定要不要写)
                        if self._display_mode in (
                            "state", "country", "strategic_region", "continent",
                            "province_terrain",
                        ):
                            self._assign_dragging = True
                            self._assign_drag_seen = {pid}
                event.accept()
                return

            # 省份模式 + 切割模式：旋转线切割
            if self._display_mode == "province" and getattr(self, '_split_mode', False):
                sx, sy = self._scene_pos(event)
                if 0 <= sx < self.map_w and 0 <= sy < self.map_h:
                    pid = int(self._province_map[int(sy), int(sx)])
                    if pid > 0:
                        if getattr(self, '_split_ready', False):
                            # 点击确认切割 — 传质心、方向、鼠标点击位置
                            import math
                            self._split_ready = False
                            self._split_line_item.setVisible(False)
                            angle = getattr(self, '_split_angle', 0.0)
                            self.split_line_drawn.emit(self._split_pid, [
                                (self._split_cy, self._split_cx),
                                (int(self._split_cy + 9999 * math.sin(angle)),
                                 int(self._split_cx + 9999 * math.cos(angle))),
                                (int(sy), int(sx)),  # 鼠标点击位置 → 这一侧切出去
                            ])
                        else:
                            # 点击省份 → 初始化切割预览
                            self._init_split_preview(pid)
                event.accept()
                return

            # 省份模式：左键只做选中 (扩张需走 lasso 框架工具, 不允许直接拖动改边界)
            if self._display_mode == "province":
                sx, sy = self._scene_pos(event)
                if 0 <= sx < self.map_w and 0 <= sy < self.map_h:
                    pid = int(self._province_map[int(sy), int(sx)])
                    if pid > 0:
                        self._selected_province_id = pid
                        self._selected_province_tile = int(self._tile_map[int(sy), int(sx)])
                        self.province_clicked.emit(pid)
                        self._render_province_overlay()
                event.accept()
                return

            # 河流模式：画笔绘制
            if self._display_mode == "river":
                if self._current_tool in ("brush", "eraser"):
                    self._is_drawing = True
                    self.stroke_started.emit()
                    sx, sy = self._scene_pos(event)
                    # 河流自动源头：brush 模式下，若起笔点不是在已有河道上，
                    # 自动在起点放一个源头标记（0=绿色），保证画出来的河合法。
                    # HOI4 规则：没有源头的河引擎不渲染（Paradox wiki Map modding §721）
                    if (self._current_tool == "brush"
                        and self._current_river_type not in (0, 1, 2)
                        and 0 <= sx < self.map_w and 0 <= sy < self.map_h):
                        from domain.managers.river import VALID_RIVER_VALUES
                        val = int(self._river_map[sy, sx])
                        if val not in VALID_RIVER_VALUES:
                            # 临时切 source 画一下，再切回原宽度
                            orig_type = self._current_river_type
                            self._current_river_type = 0
                            self._stamp_brush(sx, sy)
                            self._current_river_type = orig_type
                            # 避免下一步与源头之间出对角，_last_draw_pos 设为源头位置
                            self._last_draw_pos = (sx, sy)
                            event.accept()
                            return
                    self._paint_at(sx, sy)
                    event.accept()
                    return

            if self._current_tool in ("brush", "eraser", "new_land"):
                self._is_drawing = True
                self.stroke_started.emit()
                sx, sy = self._scene_pos(event)
                self._paint_at(sx, sy)
                event.accept()
                return

            if self._current_tool == "fill":
                self.stroke_started.emit()
                sx, sy = self._scene_pos(event)
                self._flood_fill(sx, sy)
                self.stroke_ended.emit()
                event.accept()
                return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        sx, sy = self._scene_pos(event)
        if 0 <= sx < self.map_w and 0 <= sy < self.map_h:
            self.mouse_moved.emit(sx, sy)
            self._update_brush_cursor(sx, sy)
            # 更新连续画笔的位置 (鼠标动了就用最新位置, 鼠标停了 timer 用记住的位置补画)
            if getattr(self, "_continuous_brush_pos", None) is not None:
                self._continuous_brush_pos = (sx, sy)
        else:
            self._brush_cursor.setVisible(False)

        # 变换工具框选拖拽
        if self._transform_selecting and self._selection_start:
            x0, y0 = self._selection_start
            x1 = max(0, min(self.map_w, int(sx)))
            y1 = max(0, min(self.map_h, int(sy)))
            rx0, ry0 = min(x0, x1), min(y0, y1)
            rx1, ry1 = max(x0, x1), max(y0, y1)
            self._selection_rect = (rx0, ry0, rx1, ry1)
            self._selection_rect_item.setRect(QRectF(rx0, ry0, rx1 - rx0, ry1 - ry0))
            event.accept()
            return

        # 变换工具拖拽（移动/缩放）
        if self._transform_drag and self._transform_box:
            dx = sx - self._transform_drag_start[0]
            dy = sy - self._transform_drag_start[1]
            bx0, by0, bx1, by1 = self._transform_box_start

            if self._transform_drag == "move":
                self._transform_box = (bx0 + dx, by0 + dy, bx1 + dx, by1 + dy)
            elif self._transform_drag == "rotate":
                # 以框中心为原点，计算起始角和当前角的差
                import math
                cx = (bx0 + bx1) / 2
                cy = (by0 + by1) / 2
                start_angle = math.atan2(
                    self._transform_drag_start[1] - cy,
                    self._transform_drag_start[0] - cx,
                )
                cur_angle = math.atan2(sy - cy, sx - cx)
                delta_deg = math.degrees(cur_angle - start_angle)
                self._transform_angle = self._transform_angle_start + delta_deg
            elif self._transform_drag == "tl":
                self._transform_box = (bx0 + dx, by0 + dy, bx1, by1)
            elif self._transform_drag == "tr":
                self._transform_box = (bx0, by0 + dy, bx1 + dx, by1)
            elif self._transform_drag == "bl":
                self._transform_box = (bx0 + dx, by0, bx1, by1 + dy)
            elif self._transform_drag == "br":
                self._transform_box = (bx0, by0, bx1 + dx, by1 + dy)

            self._update_transform_visuals()

            # 实时预览
            self._apply_transform()

            event.accept()
            return

        # 框选模式拖拽
        if self._selection_mode and self._selection_start:
            x0, y0 = self._selection_start
            x1, y1 = max(0, min(self.map_w, int(sx))), max(0, min(self.map_h, int(sy)))
            rx0, ry0 = min(x0, x1), min(y0, y1)
            rx1, ry1 = max(x0, x1), max(y0, y1)
            self._selection_rect = (rx0, ry0, rx1, ry1)
            self._selection_rect_item.setRect(QRectF(rx0, ry0, rx1 - rx0, ry1 - ry0))
            event.accept()
            return

        # Ctrl+拖拽：移动参考图
        if getattr(self, '_ref_dragging', False):
            delta = event.pos() - self._ref_drag_start
            self._ref_drag_start = event.pos()
            # 屏幕像素转场景像素（考虑缩放）
            scene_dx = delta.x() / self._zoom
            scene_dy = delta.y() / self._zoom
            self.move_ref_image(scene_dx, scene_dy)
            event.accept()
            return

        if self._is_panning:
            delta = event.pos() - self._pan_start
            self._pan_start = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return

        # 拖拽分配模式（大陆/州/国家/战略区）
        if getattr(self, '_assign_dragging', False):
            if 0 <= sx < self.map_w and 0 <= sy < self.map_h:
                pid = int(self._province_map[int(sy), int(sx)])
                if pid > 0 and pid not in self._assign_drag_seen:
                    self._assign_drag_seen.add(pid)
                    self.province_clicked.emit(pid)
            event.accept()
            return

        # 框架工具分发
        if self._is_drawing and self._framework_tool is not None:
            if 0 <= sx < self.map_w and 0 <= sy < self.map_h:
                self._framework_tool.on_drag(self._framework_ctx, sx, sy)
                # 拖动期间持续刷新画布，让用户看到扩张效果
                if self._framework_ctx.state.get("painting"):
                    self._mark_dirty(
                        max(0, sx - 10), max(0, sy - 10),
                        min(self.map_w, sx + 11), min(self.map_h, sy + 11),
                    )
                    self._flush_dirty()
                    self._render_province_overlay()
                event.accept()
                return

        # 山脉画线拖拽中
        if getattr(self, '_ridge_drawing', False) and self._is_drawing:
            if 0 <= sx < self.map_w and 0 <= sy < self.map_h:
                self._ridge_path.append((int(sy), int(sx)))
                # 实时扩展红线预览
                current_path = self._ridge_path_item.path()
                current_path.lineTo(sx, sy)
                self._ridge_path_item.setPath(current_path)
            event.accept()
            return

        # 局部精修套索拖拽中
        if getattr(self, '_refine_lasso_drawing', False) and self._is_drawing:
            if 0 <= sx < self.map_w and 0 <= sy < self.map_h:
                self._refine_lasso_path.append((int(sy), int(sx)))
                current_path = self._refine_lasso_item.path()
                current_path.lineTo(sx, sy)
                self._refine_lasso_item.setPath(current_path)
            event.accept()
            return

        # 切割旋转线 — 鼠标移动更新角度
        if getattr(self, '_split_ready', False):
            import math
            cx, cy = self._split_cx, self._split_cy
            angle = math.atan2(sy - cy, sx - cx)
            self._split_angle = angle
            self._update_split_rotate_preview()
            event.accept()
            return

        # 高度画笔拖拽
        if (self._is_drawing and self._display_mode == "height"
                and getattr(self, '_height_brush_mode', 'off') != "off"):
            if 0 <= sx < self.map_w and 0 <= sy < self.map_h:
                self._paint_at(sx, sy)
            event.accept()
            return

        if self._is_drawing and self._current_tool in ("brush", "eraser", "new_land"):
            self._paint_at(sx, sy)
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        # 变换工具框选完成 — 激活变换框
        if self._transform_selecting and self._selection_start:
            self._transform_selecting = False
            self._selection_start = None
            self._selection_rect_item.setVisible(False)
            if self._selection_rect:
                x0, y0, x1, y1 = self._selection_rect
                if x1 - x0 > 5 and y1 - y0 > 5:
                    # 剪切选区内容
                    from data.constants import TILE_SEA
                    self._transform_snippet = self._tile_map[y0:y1, x0:x1].copy()
                    self._transform_orig_box = (x0, y0, x1, y1)
                    self._transform_box = (float(x0), float(y0), float(x1), float(y1))
                    # 清除原位置
                    self._tile_map[y0:y1, x0:x1] = TILE_SEA
                    self._full_render()
                    self._transform_active = True
                    self._update_transform_visuals()
            self._selection_rect = None
            event.accept()
            return

        # 变换工具拖拽释放
        if self._transform_drag:
            self._transform_drag = None
            self.setCursor(Qt.CursorShape.CrossCursor)
            event.accept()
            return

        # 框选完成
        if self._selection_mode and self._selection_start:
            self._selection_start = None
            self._finish_selection()
            event.accept()
            return

        # 结束参考图拖拽
        if getattr(self, '_ref_dragging', False):
            self._ref_dragging = False
            self.setCursor(Qt.CursorShape.CrossCursor)
            event.accept()
            return

        # 结束拖拽分配
        if getattr(self, '_assign_dragging', False):
            self._assign_dragging = False
            self._assign_drag_seen = set()
            event.accept()
            return

        if event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.LeftButton):
            if self._is_panning:
                self._is_panning = False
                self.setCursor(Qt.CursorShape.CrossCursor if self._current_tool != "pan"
                              else Qt.CursorShape.OpenHandCursor)
                event.accept()
                return
            if self._is_drawing:
                self._is_drawing = False
                self._last_draw_pos = None  # 清除插值起点
                self._stop_continuous_brush()  # 鼠标释放停掉连续画笔 timer

                # 山脉画线释放 → 发射信号给 MainWindow 处理
                if getattr(self, '_ridge_drawing', False):
                    self._ridge_drawing = False
                    path = getattr(self, '_ridge_path', [])
                    # 隐藏红线（接下来显示预览山脉）
                    self._ridge_path_item.setVisible(False)
                    if len(path) >= 2:
                        self.ridge_drawn.emit(path)
                    self._ridge_path = []
                    self.stroke_ended.emit()
                    event.accept()
                    return

                # 套索释放 → 闭合多边形 → 按 _active_lasso_kind 发对应信号
                if getattr(self, '_refine_lasso_drawing', False):
                    self._refine_lasso_drawing = False
                    kind = getattr(self, '_active_lasso_kind', 'refine')
                    path = getattr(self, '_refine_lasso_path', [])
                    # 闭合：把最后一点连回起点
                    if len(path) >= 3:
                        current_path = self._refine_lasso_item.path()
                        current_path.lineTo(path[0][1], path[0][0])
                        self._refine_lasso_item.setPath(current_path)
                    self._refine_lasso_item.setVisible(False)
                    if len(path) >= 3:
                        if kind == "downgrade":
                            self.downgrade_lasso_drawn.emit(path)
                        else:
                            self.refine_lasso_drawn.emit(path)
                    self._refine_lasso_path = []
                    self._active_lasso_kind = None
                    self.stroke_ended.emit()
                    event.accept()
                    return

                # (切割模式用点击确认，不用释放)

                # 框架工具：先 release，再清理，再 end_undo，最后刷新
                if self._framework_tool is not None:
                    sx, sy = self._scene_pos(event)
                    self._framework_tool.on_release(self._framework_ctx, sx, sy)
                    self._framework_tool.run_cleanup(self._framework_ctx)
                    self._framework_tool.end_undo(self._framework_ctx)
                    # 同步选中状态到 canvas
                    self._selected_province_id = self._framework_ctx.selected_province_id
                    # overlay 跟随：还有 pid 就保留显示，否则清掉
                    if self._framework_ctx.state.get("pid"):
                        self._show_expand_overlay()
                    else:
                        self._clear_lasso_visual()
                    # 清边界缓存 + 全量刷新
                    self._border_cache = None
                    if hasattr(self, '_border_base_pixmap'):
                        self._border_base_pixmap = None
                    self._full_render()
                    if self._display_mode == "province":
                        self._render_province_overlay()
                    # 检测省份 ID 空洞（扩张可能吞掉整个邻居）
                    import numpy as np
                    pm = self._province_map
                    max_id = int(pm.max())
                    existing = set(np.unique(pm)) - {0}
                    gap_ids = sorted(set(range(1, max_id + 1)) - existing)
                    self.province_gaps_detected.emit(gap_ids)
                    self.stroke_ended.emit()
                    event.accept()
                    return

                self._flush_dirty()
                # 省份模式拖动结束后：只刷新边界，不做重清理
                if self._display_mode == "province":
                    self._render_province_overlay()
                # 密度画笔结束后刷新叠加层
                if getattr(self, '_density_overlay_visible', False):
                    self._render_density_overlay()
                self.stroke_ended.emit()
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """双击省份 → 设置 VP（所有模式，但不触发画笔）"""
        if event.button() == Qt.MouseButton.LeftButton:
            # 阻止双击触发画笔
            self._is_drawing = False
            self._last_draw_pos = None
            sx, sy = self._scene_pos(event)
            if 0 <= sx < self.map_w and 0 <= sy < self.map_h:
                pid = int(self._province_map[sy, sx])
                if pid > 0:
                    self.province_double_clicked.emit(pid)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event) -> None:
        """右键省份 → 弹出上下文菜单（所有模式）"""
        pos = self.mapToScene(event.pos())
        sx, sy = int(pos.x()), int(pos.y())
        if 0 <= sx < self.map_w and 0 <= sy < self.map_h:
            pid = int(self._province_map[sy, sx])
            if pid > 0:
                self.province_right_clicked.emit(pid)
                # 传递屏幕坐标，供弹出菜单定位
                global_pos = self.mapToGlobal(event.pos())
                self.province_right_clicked_at.emit(pid, global_pos.x(), global_pos.y())
                return
        super().contextMenuEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        # Ctrl+滚轮：缩放参考图
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            scale_step = 0.1 if delta > 0 else -0.1
            new_scale = self._ref_layers[self.REF_CUSTOM].scale + scale_step
            self.set_ref_scale(new_scale)
            event.accept()
            return

        factor = ZOOM_STEP if event.angleDelta().y() > 0 else 1.0 / ZOOM_STEP
        new_zoom = self._zoom * factor
        if ZOOM_MIN <= new_zoom <= ZOOM_MAX:
            self._zoom = new_zoom
            self.scale(factor, factor)
            self.zoom_changed.emit(self._zoom)
        event.accept()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Space:
            self._space_pressed = True
            if not self._is_drawing:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
        # ESC：取消正在进行的套索/框架工具操作
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            # Enter 确认变换
            if self._transform_active:
                self._apply_transform()
                self.stroke_ended.emit()
                self._end_transform()
                return
        elif event.key() == Qt.Key.Key_Escape:
            # ESC 取消变换
            if self._transform_active:
                self._cancel_transform()
                self.stroke_ended.emit()
                return
            if self._is_drawing and self._framework_tool is not None:
                self._framework_tool.on_cancel(self._framework_ctx)
                self._is_drawing = False
                self._clear_lasso_visual()
                # 不入撤销栈（因为是取消，pending 直接丢弃）
                self._framework_ctx.undo_mgr._pending = None
                self.stroke_ended.emit()
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Space:
            self._space_pressed = False
            if not self._is_panning:
                self.setCursor(Qt.CursorShape.CrossCursor if self._current_tool != "pan"
                              else Qt.CursorShape.OpenHandCursor)
        super().keyReleaseEvent(event)

    def _init_split_preview(self, pid: int) -> None:
        """初始化切割预览：计算省份质心和 bbox，显示线。"""
        import numpy as np
        mask = self._province_map == pid
        ys, xs = np.where(mask)
        if len(ys) == 0:
            return
        self._split_pid = pid
        self._split_cy = int(np.mean(ys))
        self._split_cx = int(np.mean(xs))
        self._split_bbox = (int(ys.min()), int(xs.min()),
                            int(ys.max()), int(xs.max()))
        self._split_angle = 0.0
        self._split_ready = True
        self._update_split_rotate_preview()

    def _update_split_rotate_preview(self) -> None:
        """实时更新切割旋转线预览。线穿过省份质心，长度覆盖 bbox。"""
        import math
        from PyQt5.QtGui import QPainterPath

        cx = self._split_cx
        cy = self._split_cy
        angle = getattr(self, '_split_angle', 0.0)
        y0, x0, y1, x1 = self._split_bbox

        # 线长 = bbox 对角线，确保完全穿过省份
        diag = math.sqrt((y1 - y0) ** 2 + (x1 - x0) ** 2) / 2 + 10
        dx = diag * math.cos(angle)
        dy = diag * math.sin(angle)

        pp = QPainterPath()
        pp.moveTo(cx - dx, cy - dy)
        pp.lineTo(cx + dx, cy + dy)
        self._split_line_item.setPath(pp)
        self._split_line_item.setVisible(True)
