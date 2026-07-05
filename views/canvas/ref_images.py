"""
参考图管理 Mixin — 用户参考图 + 原版地图参考层
两张图共用同一套"参考图层"结构, 各自独立: 加载/透明度/缩放/移动/铺满/显隐。
旧方法名保留为薄包装, main_window / input_router 的既有调用不受影响。
"""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QGraphicsPixmapItem


class RefLayer:
    """单张参考图层: 场景 item + 原始 pixmap + 当前缩放倍率。"""

    def __init__(self, item: QGraphicsPixmapItem):
        self.item = item
        self.original = QPixmap()
        self.scale = 1.0


class RefImageMixin:
    """参考图相关方法。假设 self 拥有:
    - _ref_layers: dict[str, RefLayer]  (键: REF_CUSTOM / REF_VANILLA)
    - map_w / map_h / _show_ref_image
    """

    REF_CUSTOM = "custom"
    REF_VANILLA = "vanilla"

    # ── 通用图层接口 ──────────────────────────────────

    def load_ref_layer(self, key: str, file_path: str, fit: bool = False) -> bool:
        """加载一张参考图。fit=True 时直接拉伸铺满地图。"""
        layer = self._ref_layers[key]
        pixmap = QPixmap(file_path)
        if pixmap.isNull():
            return False
        layer.original = pixmap
        if fit:
            self.fit_ref_layer(key)
        else:
            layer.scale = 1.0
            layer.item.setPixmap(pixmap)
            # 默认居中
            layer.item.setPos(
                (self.map_w - pixmap.width()) / 2,
                (self.map_h - pixmap.height()) / 2,
            )
        layer.item.setVisible(True)
        return True

    def set_ref_layer_opacity(self, key: str, opacity: float) -> None:
        self._ref_layers[key].item.setOpacity(max(0.0, min(1.0, opacity)))

    def set_ref_layer_scale(self, key: str, scale: float) -> None:
        """缩放参考图 (1.0 = 原始大小), 以原始 pixmap 为基准。"""
        layer = self._ref_layers[key]
        scale = max(0.1, min(10.0, scale))
        layer.scale = scale
        if not layer.original.isNull():
            scaled = layer.original.scaled(
                int(layer.original.width() * scale),
                int(layer.original.height() * scale),
                Qt.KeepAspectRatio, Qt.SmoothTransformation)
            layer.item.setPixmap(scaled)
        if getattr(self, '_ref_adjust_target', None) == key:
            self._update_ref_adjust_border()

    def move_ref_layer(self, key: str, dx: float, dy: float) -> None:
        item = self._ref_layers[key].item
        pos = item.pos()
        item.setPos(pos.x() + dx, pos.y() + dy)
        if getattr(self, '_ref_adjust_target', None) == key:
            self._update_ref_adjust_border()

    def fit_ref_layer(self, key: str) -> None:
        """拉伸铺满整张地图。"""
        layer = self._ref_layers[key]
        if layer.original.isNull():
            return
        scaled = layer.original.scaled(
            self.map_w, self.map_h,
            Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        layer.item.setPixmap(scaled)
        layer.item.setPos(0, 0)
        layer.scale = self.map_w / layer.original.width()
        if getattr(self, '_ref_adjust_target', None) == key:
            self._update_ref_adjust_border()
        # fit 改了 scale, 回写页面滑条（main_window 已接 ref_adjust_scale_changed）
        self.ref_adjust_scale_changed.emit(key, layer.scale)

    def toggle_ref_layer(self, key: str, visible: bool) -> None:
        self._ref_layers[key].item.setVisible(visible)

    # ── 兼容旧接口 (main_window / input_router / 旧测试) ──

    def load_reference_image(self, file_path: str) -> bool:
        ok = self.load_ref_layer(self.REF_CUSTOM, file_path)
        if ok:
            self._ref_layers[self.REF_CUSTOM].item.setVisible(self._show_ref_image)
        return ok

    def load_vanilla_reference(self, file_path: str) -> bool:
        """加载原版地图参考（独立于用户参考图, 默认铺满）。"""
        return self.load_ref_layer(self.REF_VANILLA, file_path, fit=True)

    def set_vanilla_ref_opacity(self, opacity: float) -> None:
        self.set_ref_layer_opacity(self.REF_VANILLA, opacity)

    def toggle_vanilla_ref(self, visible: bool) -> None:
        self.toggle_ref_layer(self.REF_VANILLA, visible)

    def set_ref_opacity(self, opacity: float) -> None:
        self.set_ref_layer_opacity(self.REF_CUSTOM, opacity)

    def set_ref_scale(self, scale: float) -> None:
        self.set_ref_layer_scale(self.REF_CUSTOM, scale)

    def fit_ref_to_map(self) -> None:
        self.fit_ref_layer(self.REF_CUSTOM)

    def move_ref_image(self, dx: int, dy: int) -> None:
        self.move_ref_layer(self.REF_CUSTOM, dx, dy)

    def toggle_ref_image(self, visible: bool) -> None:
        self._show_ref_image = visible
        self.toggle_ref_layer(self.REF_CUSTOM, visible)

    # ── 调整参考图模式 ────────────────────────────────

    def set_ref_adjust_mode(self, target: str | None) -> None:
        """进入/退出调整参考图模式。target=None 退出并恢复绘制。"""
        self._ref_adjust_target = target
        if target is None:
            self._ref_adjust_border.setVisible(False)
            self.setCursor(Qt.CursorShape.CrossCursor if self._current_tool != "pan"
                           else Qt.CursorShape.OpenHandCursor)
            # 退出调整模式必须清掉拖拽标记：否则 ESC 中断拖拽后 _ref_dragging
            # 仍是 True，下一次 mouseMoveEvent 会 fallback 到 REF_CUSTOM 错拖自定义图
            self._ref_dragging = False
        else:
            self._update_ref_adjust_border()
            self._ref_adjust_border.setVisible(True)
            self.setCursor(Qt.CursorShape.SizeAllCursor)

    def _update_ref_adjust_border(self) -> None:
        """虚线框贴住当前被调整的参考图。"""
        if self._ref_adjust_target is None:
            return
        item = self._ref_layers[self._ref_adjust_target].item
        self._ref_adjust_border.setRect(item.sceneBoundingRect())
