"""参考图层双图结构测试 — RefLayer + 通用接口 + 旧接口兼容。"""

import pytest
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QPixmap, QColor


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def canvas(qapp):
    """与 tests/views/test_render_registry.py 相同的尺寸对齐套路。"""
    import views.canvas.widget as widget_mod
    import data.constants as constants
    from data.constants import set_map_size

    old_w, old_h = constants.MAP_WIDTH, constants.MAP_HEIGHT
    set_map_size(widget_mod.MAP_WIDTH, widget_mod.MAP_HEIGHT)
    try:
        yield widget_mod.MapCanvas()
    finally:
        set_map_size(old_w, old_h)


def _make_png(tmp_path, w=64, h=32) -> str:
    px = QPixmap(w, h)
    px.fill(QColor(200, 100, 50))
    path = str(tmp_path / "ref.png")
    px.save(path, "PNG")
    return path


def test_load_custom_centers_at_original_size(canvas, tmp_path):
    path = _make_png(tmp_path, 64, 32)
    assert canvas.load_ref_layer("custom", path)
    layer = canvas._ref_layers["custom"]
    assert layer.scale == 1.0
    assert layer.item.pixmap().width() == 64
    # 默认居中
    assert layer.item.pos().x() == (canvas.map_w - 64) / 2
    assert layer.item.pos().y() == (canvas.map_h - 32) / 2


def test_load_vanilla_fit_fills_map(canvas, tmp_path):
    path = _make_png(tmp_path)
    assert canvas.load_ref_layer("vanilla", path, fit=True)
    layer = canvas._ref_layers["vanilla"]
    assert layer.item.pixmap().width() == canvas.map_w
    assert layer.item.pixmap().height() == canvas.map_h
    assert layer.item.pos().x() == 0


def test_scale_layers_independent(canvas, tmp_path):
    canvas.load_ref_layer("custom", _make_png(tmp_path, 64, 32))
    canvas.load_ref_layer("vanilla", _make_png(tmp_path, 64, 32))
    canvas.set_ref_layer_scale("custom", 2.0)
    assert canvas._ref_layers["custom"].scale == 2.0
    assert canvas._ref_layers["custom"].item.pixmap().width() == 128
    # vanilla 不受影响
    assert canvas._ref_layers["vanilla"].scale == 1.0


def test_move_and_fit_layer(canvas, tmp_path):
    canvas.load_ref_layer("vanilla", _make_png(tmp_path))
    canvas.move_ref_layer("vanilla", 10, -5)
    pos = canvas._ref_layers["vanilla"].item.pos()
    x0 = (canvas.map_w - 64) / 2
    y0 = (canvas.map_h - 32) / 2
    assert (pos.x(), pos.y()) == (x0 + 10, y0 - 5)
    canvas.fit_ref_layer("vanilla")
    assert canvas._ref_layers["vanilla"].item.pos().x() == 0


def test_legacy_wrappers_route_to_layers(canvas, tmp_path):
    path = _make_png(tmp_path)
    assert canvas.load_reference_image(path)          # → custom
    assert canvas.load_vanilla_reference(path)        # → vanilla + fit
    canvas.set_ref_scale(1.5)                         # → custom
    assert canvas._ref_layers["custom"].scale == 1.5
    canvas.set_vanilla_ref_opacity(0.7)
    assert canvas._ref_layers["vanilla"].item.opacity() == pytest.approx(0.7)
    canvas.toggle_ref_image(False)
    assert not canvas._ref_layers["custom"].item.isVisible()
    canvas.fit_ref_to_map()
    assert canvas._ref_layers["custom"].item.pixmap().width() == canvas.map_w


from PyQt5.QtCore import Qt, QEvent, QPointF, QPoint
from PyQt5.QtGui import QMouseEvent, QKeyEvent, QWheelEvent


def _left_press(x=50.0, y=50.0) -> QMouseEvent:
    return QMouseEvent(QEvent.MouseButtonPress, QPointF(x, y),
                       Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)


def test_adjust_mode_blocks_drawing(canvas, tmp_path):
    canvas.load_ref_layer("custom", _make_png(tmp_path))
    canvas.set_ref_adjust_mode("custom")
    canvas.mousePressEvent(_left_press())
    assert canvas._is_drawing is False          # 画笔没有启动
    assert canvas._ref_dragging is True         # 变成拖参考图
    assert canvas._ref_adjust_border.isVisible()


def test_adjust_mode_off_restores_drawing(canvas, tmp_path):
    canvas.load_ref_layer("custom", _make_png(tmp_path))
    canvas.set_ref_adjust_mode("custom")
    canvas.set_ref_adjust_mode(None)
    assert not canvas._ref_adjust_border.isVisible()
    canvas.mousePressEvent(_left_press())
    assert canvas._is_drawing is True           # 画笔恢复


def test_esc_exits_adjust_and_emits(canvas, tmp_path):
    canvas.load_ref_layer("vanilla", _make_png(tmp_path))
    canvas.set_ref_adjust_mode("vanilla")
    fired = []
    canvas.ref_adjust_exited.connect(lambda: fired.append(1))
    esc = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
    canvas.keyPressEvent(esc)
    assert canvas._ref_adjust_target is None
    assert fired == [1]


def test_wheel_scales_adjust_target(canvas, tmp_path):
    canvas.load_ref_layer("vanilla", _make_png(tmp_path))
    canvas.set_ref_adjust_mode("vanilla")
    canvas.set_ref_layer_scale("vanilla", 1.0)
    got = []
    canvas.ref_adjust_scale_changed.connect(lambda t, s: got.append((t, s)))
    ev = QWheelEvent(QPointF(50, 50), QPointF(50, 50), QPoint(0, 0),
                     QPoint(0, 120), Qt.NoButton, Qt.NoModifier,
                     Qt.NoScrollPhase, False)
    canvas.wheelEvent(ev)
    assert canvas._ref_layers["vanilla"].scale == pytest.approx(1.1)
    assert got == [("vanilla", pytest.approx(1.1))]
    # 自定义图不动
    assert canvas._ref_layers["custom"].scale == 1.0


def test_adjust_mode_blocks_double_click(canvas, tmp_path):
    canvas.load_ref_layer("custom", _make_png(tmp_path))
    canvas._province_map[50, 50] = 5
    fired = []
    canvas.province_double_clicked.connect(fired.append)
    canvas.set_ref_adjust_mode("custom")
    dbl = QMouseEvent(QEvent.MouseButtonDblClick, QPointF(50, 50),
                      Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    canvas.mouseDoubleClickEvent(dbl)
    assert fired == []                       # 调整模式下不触发
    canvas.set_ref_adjust_mode(None)
    canvas.mouseDoubleClickEvent(dbl)
    assert fired == [5]                      # 退出后恢复
