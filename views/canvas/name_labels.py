"""名字标签叠加层 Mixin — state/country 模式在地图上显示名字 (HOI4 风格).

效果: 文字沿区域主轴倾斜, 区域越大字越大, 矢量文字随画布缩放不发糊.
适用: state 模式显示州名, country 模式显示国家名.
调用: app_controller 推 provider → set_name_label_data(mode, provider);
     _full_render 里调 _update_name_labels_visibility() 控制显隐.
排版惰性执行: id 图构建 + 排版都推迟到"叠加层可见且 400ms 防抖到期",
编辑归属的每一笔只付一个 lambda 的成本, 不做全图计算.
"""
from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QColor, QPen, QBrush, QFont
from PyQt5.QtWidgets import QGraphicsItem, QGraphicsSimpleTextItem

# 有名字标签的显示模式
_LABEL_MODES = ("state", "country")
# 缩放后文字高度小于该像素数就不显示(反正读不出来, 还添乱)
_MIN_TEXT_HEIGHT = 4.0


class NameLabelsMixin:
    """假设 self 拥有: _scene, _display_mode"""

    def _init_name_labels(self) -> None:
        self._name_label_data: dict = {}    # mode → provider() → (id_map, {id: name})
        self._name_label_dirty: dict = {}   # mode → bool
        self._name_label_items: dict = {}   # mode → list[QGraphicsSimpleTextItem]
        self._name_labels_enabled: dict = {m: True for m in _LABEL_MODES}  # 页面开关
        self._name_label_timer = QTimer(self)
        self._name_label_timer.setSingleShot(True)
        self._name_label_timer.setInterval(400)
        self._name_label_timer.timeout.connect(self._update_name_labels_visibility)

    def set_name_label_data(self, mode: str, provider) -> None:
        """接收数据源 provider() → (id_map, names), 标脏并启动防抖重排。
        provider 只在防抖到期且模式可见时才被调用, 保证编辑时不卡。"""
        self._name_label_data[mode] = provider
        self._name_label_dirty[mode] = True
        self._name_label_timer.start()

    def set_name_labels_enabled(self, mode: str, on: bool) -> None:
        """页面"显示名字"开关。关掉只隐藏, 数据和排版缓存保留。"""
        self._name_labels_enabled[mode] = bool(on)
        self._update_name_labels_visibility()

    def clear_name_labels(self) -> None:
        """换地图数据时清空所有标签(旧坐标已无意义)。"""
        for items in self._name_label_items.values():
            for it in items:
                self._scene.removeItem(it)
        self._name_label_items.clear()
        self._name_label_data.clear()
        self._name_label_dirty.clear()

    def _update_name_labels_visibility(self) -> None:
        """当前模式匹配才显示; 脏数据且防抖到期才重排。"""
        for mode in _LABEL_MODES:
            visible = (
                self._display_mode == mode
                and self._name_labels_enabled.get(mode, True)
            )
            if visible and self._name_label_dirty.get(mode):
                if self._name_label_timer.isActive():
                    continue  # 还在防抖窗口内, 到点由 timer 再进来
                self._rebuild_name_labels(mode)
            for it in self._name_label_items.get(mode, []):
                it.setVisible(visible)

    def _rebuild_name_labels(self, mode: str) -> None:
        from domain.label_placement import compute_region_labels

        for it in self._name_label_items.get(mode, []):
            self._scene.removeItem(it)
        self._name_label_items[mode] = []
        self._name_label_dirty[mode] = False

        provider = self._name_label_data.get(mode)
        if provider is None:
            return
        id_map, names = provider()
        placements = compute_region_labels(id_map)

        font = QFont("Microsoft YaHei")
        font.setPixelSize(24)
        font.setBold(True)
        brush = QBrush(QColor(255, 255, 255, 235))
        pen = QPen(QColor(20, 20, 20, 170))
        pen.setWidthF(0.8)

        items = []
        for rid, (cx, cy, angle, length, width) in placements.items():
            text = names.get(rid, "")
            if not text:
                continue
            it = QGraphicsSimpleTextItem(text)
            it.setFont(font)
            it.setBrush(brush)
            it.setPen(pen)
            br = it.boundingRect()
            # 文字铺满长轴 ~70%, 且不超过短轴高度的 90%
            s = min(
                length * 0.7 / max(br.width(), 1.0),
                width * 0.9 / max(br.height(), 1.0),
            )
            if br.height() * s < _MIN_TEXT_HEIGHT:
                continue
            it.setTransformOriginPoint(br.center())
            it.setRotation(angle)
            it.setScale(s)
            it.setPos(cx - br.center().x(), cy - br.center().y())
            it.setZValue(6)
            # 缓存渲染结果: 拖动画布时贴缓存位图, 不逐帧重绘矢量文字
            it.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)
            it.setVisible(False)  # 显隐统一由 _update_name_labels_visibility 管
            self._scene.addItem(it)
            items.append(it)
        self._name_label_items[mode] = items
