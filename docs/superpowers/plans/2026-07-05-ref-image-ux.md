# 参考底图 UX 改版 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 陆地页"① 参考底图"卡片重排（导入置顶 + 打开原版参考按钮），原版/自定义两张参考图对称控制（透明度/缩放/拖拽/铺满），新增"调整参考图位置"模式（期间禁用一切绘制）。

**Architecture:** `ref_images.py` 重构为通用"参考图层"结构（RefLayer × 2，旧方法名保留为薄包装）；画布新增调整模式状态 + 橙色虚线框，`input_router.py` 顶部拦截；`LandPage` 卡片重排并发新信号，经 `ToolPanel` 转发到 `MainWindow` 接线。

**Tech Stack:** Python 3.10+ / PyQt5 / pytest（Qt offscreen，模式照抄 `tests/views/test_render_registry.py`）

**Spec:** `docs/superpowers/specs/2026-07-05-ref-image-ux-design.md`

## Global Constraints

- 每个文件 < 800 行；中文注释；type hints；snake_case 方法名。
- i18n：开发期**只写 zh 文案**，en/ru 留给发版前 audit 统一补翻（用户工作流）。
- 旧对外接口不许破坏：`load_reference_image` / `load_vanilla_reference` / `set_vanilla_ref_opacity` / `toggle_vanilla_ref` / `set_ref_opacity` / `set_ref_scale` / `fit_ref_to_map` / `move_ref_image` / `toggle_ref_image`，以及 ToolPanel 既有 property（`_vanilla_ref_opacity_slider` 等 6 个）。
- 工作目录 = git 仓库根：`C:/Users/Administrator.SKY-20180310BMB/Desktop/MOD/hoi4_map_maker`。
- 跑测试统一用：`python -m pytest <path> -v`（Windows PowerShell）。

---

### Task 1: ref_images.py 重构为双图层通用结构

**Files:**
- Modify: `views/canvas/ref_images.py`（整文件重写）
- Modify: `views/canvas/widget.py:178-188`（图层初始化）+ 文件顶部 import
- Modify: `views/canvas/input_router.py:636-644`（Ctrl+滚轮分支里 `_ref_scale` 的读取）
- Test: `tests/views/test_ref_images.py`（新建）

**Interfaces:**
- Consumes: `MapCanvas`（组合了 `RefImageMixin`），`self.map_w` / `self.map_h` / `self._show_ref_image`
- Produces（后续 Task 依赖，签名固定）:
  - `RefLayer` 类：属性 `item: QGraphicsPixmapItem`、`original: QPixmap`、`scale: float`
  - `self._ref_layers: dict[str, RefLayer]`，键 `"custom"` / `"vanilla"`
  - `load_ref_layer(key: str, file_path: str, fit: bool = False) -> bool`
  - `set_ref_layer_opacity(key: str, opacity: float) -> None`
  - `set_ref_layer_scale(key: str, scale: float) -> None`
  - `move_ref_layer(key: str, dx: float, dy: float) -> None`
  - `fit_ref_layer(key: str) -> None`
  - `toggle_ref_layer(key: str, visible: bool) -> None`

- [ ] **Step 1: 写失败测试**

新建 `tests/views/test_ref_images.py`：

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/views/test_ref_images.py -v`
Expected: FAIL — `AttributeError: 'MapCanvas' object has no attribute '_ref_layers'`（或 `load_ref_layer` 不存在）

- [ ] **Step 3: 重写 views/canvas/ref_images.py**

整文件替换为：

```python
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

    def move_ref_layer(self, key: str, dx: float, dy: float) -> None:
        item = self._ref_layers[key].item
        pos = item.pos()
        item.setPos(pos.x() + dx, pos.y() + dy)

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
```

- [ ] **Step 4: widget.py 初始化 _ref_layers**

`views/canvas/widget.py` 找到参考图层初始化（约 178-188 行）：

```python
        # 原版地图参考层 (底层)
        self._vanilla_ref_item = QGraphicsPixmapItem()
        self._vanilla_ref_item.setOpacity(0.3)
        self._vanilla_ref_item.setZValue(1)
        self._scene.addItem(self._vanilla_ref_item)

        # 用户自定义参考图层 (上层)
        self._ref_pixmap_item = QGraphicsPixmapItem()
        self._ref_pixmap_item.setOpacity(0.4)
        self._ref_pixmap_item.setZValue(2)
        self._scene.addItem(self._ref_pixmap_item)
```

在这段**之后**追加（`_vanilla_ref_item` / `_ref_pixmap_item` 两个旧属性名保留）：

```python
        # 统一参考图层注册表 (ref_images.py 通用接口)
        self._ref_layers = {
            RefImageMixin.REF_VANILLA: RefLayer(self._vanilla_ref_item),
            RefImageMixin.REF_CUSTOM: RefLayer(self._ref_pixmap_item),
        }
```

widget.py 顶部找到 `from views.canvas.ref_images import RefImageMixin`（MapCanvas 的 mixin import 处），改为：

```python
from views.canvas.ref_images import RefImageMixin, RefLayer
```

- [ ] **Step 5: input_router.py Ctrl+滚轮改读图层 scale**

`views/canvas/input_router.py` wheelEvent（约 636-644 行），把：

```python
            new_scale = getattr(self, '_ref_scale', 1.0) + scale_step
```

改为：

```python
            new_scale = self._ref_layers[self.REF_CUSTOM].scale + scale_step
```

（旧 `_ref_scale` / `_ref_original_pixmap` 属性已由 RefLayer.scale / RefLayer.original 取代，全仓 grep `_ref_scale\b` 和 `_ref_original_pixmap` 确认除 slider 名字外无其他引用。）

- [ ] **Step 6: 跑测试确认通过**

Run: `python -m pytest tests/views/test_ref_images.py -v`
Expected: 5 passed

- [ ] **Step 7: 跑全量测试防回归**

Run: `python -m pytest -m "not slow" -q`
Expected: 全过（旧接口薄包装保证兼容）

- [ ] **Step 8: Commit**

```powershell
git add views/canvas/ref_images.py views/canvas/widget.py views/canvas/input_router.py tests/views/test_ref_images.py
git commit -m "refactor: 参考图重构为双图层通用结构（原版/自定义对称控制）"
```

---

### Task 2: 画布调整模式（拖拽/缩放参考图 + 禁用绘制）

**Files:**
- Modify: `views/canvas/ref_images.py`（追加调整模式方法）
- Modify: `views/canvas/widget.py`（信号 2 个 + 状态 + 橙色虚线框 item）
- Modify: `views/canvas/input_router.py`（mousePress / mouseMove / mouseRelease / wheel / keyPress 五处）
- Test: `tests/views/test_ref_images.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `_ref_layers` / `move_ref_layer` / `set_ref_layer_scale`
- Produces（Task 4 接线依赖）:
  - `set_ref_adjust_mode(target: str | None) -> None` — `"custom"`/`"vanilla"` 进入，`None` 退出
  - `self._ref_adjust_target: str | None` — 当前调整对象
  - 信号 `ref_adjust_exited = pyqtSignal()` — ESC 退出时发射
  - 信号 `ref_adjust_scale_changed = pyqtSignal(str, float)` — 滚轮缩放后发射 (target, scale)

- [ ] **Step 1: 写失败测试**

`tests/views/test_ref_images.py` 追加：

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/views/test_ref_images.py -v -k "adjust or esc or wheel_scales"`
Expected: FAIL — `AttributeError: set_ref_adjust_mode`

- [ ] **Step 3: widget.py 加信号 + 状态 + 虚线框**

widget.py MapCanvas 信号定义区（`zoom_changed` 等 pyqtSignal 声明旁）追加：

```python
    # 调整参考图模式
    ref_adjust_exited = pyqtSignal()                    # ESC 退出（页面按钮同步取消勾选）
    ref_adjust_scale_changed = pyqtSignal(str, float)   # 滚轮缩放 (target, scale)
```

`__init__` 里 `_ref_layers` 初始化之后追加：

```python
        # 调整参考图模式: None=关闭, "custom"/"vanilla"=正在调整哪张
        self._ref_adjust_target: str | None = None
```

场景 item 创建区（`_selection_rect_item` 附近）追加：

```python
        # 调整参考图模式的橙色虚线框（标出正在被拖拽的参考图）
        self._ref_adjust_border = QGraphicsRectItem()
        self._ref_adjust_border.setPen(QPen(QColor(249, 115, 22), 2, Qt.DashLine))
        self._ref_adjust_border.setBrush(QBrush(Qt.NoBrush))
        self._ref_adjust_border.setZValue(103)
        self._ref_adjust_border.setVisible(False)
        self._scene.addItem(self._ref_adjust_border)
```

- [ ] **Step 4: ref_images.py 追加调整模式方法**

`RefImageMixin` 末尾追加，并给 `move_ref_layer` / `set_ref_layer_scale` / `fit_ref_layer` 三个方法的**末尾**各加同一段虚线框跟随：

```python
    # ── 调整参考图模式 ────────────────────────────────

    def set_ref_adjust_mode(self, target: str | None) -> None:
        """进入/退出调整参考图模式。target=None 退出并恢复绘制。"""
        self._ref_adjust_target = target
        if target is None:
            self._ref_adjust_border.setVisible(False)
            self.setCursor(Qt.CrossCursor if self._current_tool != "pan"
                           else Qt.OpenHandCursor)
        else:
            self._update_ref_adjust_border()
            self._ref_adjust_border.setVisible(True)
            self.setCursor(Qt.SizeAllCursor)

    def _update_ref_adjust_border(self) -> None:
        """虚线框贴住当前被调整的参考图。"""
        if self._ref_adjust_target is None:
            return
        item = self._ref_layers[self._ref_adjust_target].item
        self._ref_adjust_border.setRect(item.sceneBoundingRect())
```

三个方法末尾追加的跟随代码（同一行内容，加三处）：

```python
        if getattr(self, '_ref_adjust_target', None) == key:
            self._update_ref_adjust_border()
```

- [ ] **Step 5: input_router.py 五处拦截**

(a) `mousePressEvent` — 中键平移分支（约 49-55 行）**之后**、框选模式拦截**之前**插入：

```python
        # 调整参考图模式: 左键 = 拖动参考图, 其余绘制交互全部拦截
        if (self._ref_adjust_target is not None
                and event.button() == Qt.MouseButton.LeftButton):
            if self._space_pressed:
                self._is_panning = True
                self._pan_start = event.pos()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            else:
                self._ref_dragging = True
                self._ref_drag_start = event.pos()
            event.accept()
            return
```

(b) `mouseMoveEvent` — 现有 `_ref_dragging` 分支（约 374-383 行）里，把 `self.move_ref_image(scene_dx, scene_dy)` 改为按目标分发：

```python
        # 拖拽移动参考图 (Ctrl+拖拽 = 自定义图; 调整模式 = 当前调整对象)
        if getattr(self, '_ref_dragging', False):
            delta = event.pos() - self._ref_drag_start
            self._ref_drag_start = event.pos()
            # 屏幕像素转场景像素（考虑缩放）
            scene_dx = delta.x() / self._zoom
            scene_dy = delta.y() / self._zoom
            target = self._ref_adjust_target or self.REF_CUSTOM
            self.move_ref_layer(target, scene_dx, scene_dy)
            event.accept()
            return
```

(c) `mouseReleaseEvent` — 现有"结束参考图拖拽"分支（约 501-506 行），光标按模式恢复：

```python
        # 结束参考图拖拽
        if getattr(self, '_ref_dragging', False):
            self._ref_dragging = False
            self.setCursor(Qt.CursorShape.SizeAllCursor
                           if self._ref_adjust_target is not None
                           else Qt.CursorShape.CrossCursor)
            event.accept()
            return
```

(d) `wheelEvent` — 方法**最顶部**（Ctrl+滚轮分支之前）插入：

```python
        # 调整参考图模式: 滚轮 = 缩放被调整的参考图
        if self._ref_adjust_target is not None:
            delta = event.angleDelta().y()
            step = 0.1 if delta > 0 else -0.1
            target = self._ref_adjust_target
            self.set_ref_layer_scale(target, self._ref_layers[target].scale + step)
            self.ref_adjust_scale_changed.emit(target, self._ref_layers[target].scale)
            event.accept()
            return
```

(e) `keyPressEvent` — 找到 `elif event.key() == Qt.Key.Key_Escape:` 分支（约 667 行），在该分支体的**第一行**（`if self._transform_active:` 之前）插入这 5 行，分支内其余原有代码一律不动：

```python
            # ESC 退出调整参考图模式
            if self._ref_adjust_target is not None:
                self.set_ref_adjust_mode(None)
                self.ref_adjust_exited.emit()
                return
```

- [ ] **Step 6: 跑测试确认通过**

Run: `python -m pytest tests/views/test_ref_images.py -v`
Expected: 9 passed

- [ ] **Step 7: 跑全量测试防回归**

Run: `python -m pytest -m "not slow" -q`
Expected: 全过

- [ ] **Step 8: Commit**

```powershell
git add views/canvas/ref_images.py views/canvas/widget.py views/canvas/input_router.py tests/views/test_ref_images.py
git commit -m "feat: 调整参考图模式（左键拖动/滚轮缩放, 期间禁用绘制, ESC 退出）"
```

---

### Task 3: LandPage 卡片重排 + 新控件/信号 + zh 文案

**Files:**
- Modify: `features/map/land/page.py:52-146`（"① 参考底图"卡片整段重写）+ 新信号 + 新方法
- Modify: `ui/i18n/zh/land.py`（新 key + 改 1 个旧 key 文案）
- Test: `tests/views/test_land_page_ref_card.py`（新建）

**Interfaces:**
- Consumes: `ui.styles` 的 `_SECONDARY_BTN_STYLE` / `_SLIDER_STYLE` / `_LABEL_STYLE` / `_DIM_LABEL_STYLE` / `make_card` / `make_hint`（现成）
- Produces（Task 4 依赖，名字固定）:
  - 信号 `open_vanilla_requested = pyqtSignal()`
  - 信号 `ref_adjust_toggled = pyqtSignal(bool)`
  - 信号 `ref_adjust_target_changed = pyqtSignal(str)`（`"custom"` / `"vanilla"`，仅选中时发）
  - 控件 `_vanilla_ref_scale_slider: QSlider`（10-500 初值 100）、`_vanilla_ref_fit_btn: QPushButton`
  - 方法 `current_adjust_target() -> str`
  - 方法 `set_ref_adjust_checked(on: bool) -> None`
  - 方法 `set_ref_scale_percent(target: str, percent: int) -> None`（blockSignals 防回环）
  - 既有控件名不变：`_vanilla_ref_opacity_slider` `_vanilla_ref_toggle` `_ref_opacity_slider` `_ref_toggle` `_ref_scale_slider` `_ref_scale_label` `_ref_fit_btn`

- [ ] **Step 1: 写失败测试**

新建 `tests/views/test_land_page_ref_card.py`：

```python
"""LandPage 参考底图卡片改版 — 新控件与新信号。"""

import pytest
from PyQt5.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def page(qapp):
    from features.map.land.page import LandPage
    return LandPage()


def test_open_vanilla_signal(page):
    fired = []
    page.open_vanilla_requested.connect(lambda: fired.append(1))
    page._open_vanilla_btn.click()
    assert fired == [1]


def test_vanilla_has_scale_and_fit(page):
    assert page._vanilla_ref_scale_slider.minimum() == 10
    assert page._vanilla_ref_scale_slider.maximum() == 500
    assert page._vanilla_ref_scale_slider.value() == 100
    assert page._vanilla_ref_fit_btn is not None


def test_adjust_toggle_emits_and_enables_radios(page):
    got = []
    page.ref_adjust_toggled.connect(got.append)
    assert not page._adjust_custom_radio.isEnabled()   # 平时置灰
    page._ref_adjust_btn.setChecked(True)
    assert got == [True]
    assert page._adjust_custom_radio.isEnabled()
    page._ref_adjust_btn.setChecked(False)
    assert got == [True, False]
    assert not page._adjust_custom_radio.isEnabled()


def test_adjust_target_radio_emits_only_selected(page):
    page._ref_adjust_btn.setChecked(True)
    got = []
    page.ref_adjust_target_changed.connect(got.append)
    page._adjust_vanilla_radio.setChecked(True)
    assert got == ["vanilla"]                          # custom 的 toggled(False) 不发
    assert page.current_adjust_target() == "vanilla"


def test_set_ref_scale_percent_no_signal_loop(page):
    fired = []
    page._vanilla_ref_scale_slider.valueChanged.connect(fired.append)
    page.set_ref_scale_percent("vanilla", 150)
    assert page._vanilla_ref_scale_slider.value() == 150
    assert fired == []                                 # blockSignals 生效
    assert page._vanilla_ref_scale_label.text() == "150%"


def test_set_ref_adjust_checked_syncs_button(page):
    page._ref_adjust_btn.setChecked(True)
    page.set_ref_adjust_checked(False)                 # 模拟画布 ESC 退出
    assert not page._ref_adjust_btn.isChecked()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/views/test_land_page_ref_card.py -v`
Expected: FAIL — `AttributeError: _open_vanilla_btn`

- [ ] **Step 3: zh 文案**

`ui/i18n/zh/land.py` STRINGS 里，改一处 + 新增（放在 `land_btn_import_ref` 附近）：

```python
    "land_btn_import_ref": "导入参考图…",
    "land_btn_open_vanilla": "打开原版参考",
    "land_btn_open_vanilla_tip": "一键从游戏目录加载原版地图垫底，照着原版地形描。",
    "land_btn_fit": "铺满",
    "land_btn_ref_adjust": "🖐 调整参考图位置",
    "land_btn_ref_adjust_active": "🖐 正在调整参考图（点击或 ESC 退出）",
    "land_label_adjust_target": "调整对象:",
    "land_adjust_custom": "自定义",
    "land_adjust_vanilla": "原版",
    "land_ref_adjust_hint": "调整模式下：左键拖动移动参考图，滚轮缩放；期间绘制功能暂停。平时也可 Ctrl+左键拖拽 / Ctrl+滚轮缩放自定义图。",
```

（en/ru 不动，发版前跑 i18n audit 统一补翻。）

- [ ] **Step 4: 重写卡片 UI**

`features/map/land/page.py`：

信号区追加：

```python
    open_vanilla_requested = pyqtSignal()        # 打开原版参考
    ref_adjust_toggled = pyqtSignal(bool)        # 调整参考图模式开关
    ref_adjust_target_changed = pyqtSignal(str)  # 调整对象: "custom"/"vanilla"
```

import 区把 `QButtonGroup` 行补上 `QRadioButton`（`from PyQt5.QtWidgets import ... QRadioButton`）。

样式常量（类外、import 之后）：

```python
# 调整模式开关: 平时次要按钮外观, 勾选后橙色 = "进行中"（与变换工具一致）
_ADJUST_BTN_STYLE = _SECONDARY_BTN_STYLE + """
    QPushButton:checked {
        background: #f97316;
        border: 2px solid #fb923c;
        color: white;
        font-weight: 700;
    }
"""
```

`_init_ui` 中 `ref_card = _make_card(...)` 到 `lay.addWidget(ref_card)`（现 53-146 行）整段替换为：

```python
        # ══ ① 参考底图 — 做图第一步: 垫在画布下照着描 ══
        ref_card = _make_card(tr("land_section_ref"), "①")

        # 顶部: 两个加载入口（导入自定义 / 打开原版）
        load_row = QHBoxLayout()
        load_row.setSpacing(4)
        import_ref_btn = QPushButton(tr("land_btn_import_ref"))
        import_ref_btn.setStyleSheet(_SECONDARY_BTN_STYLE)
        import_ref_btn.setToolTip(tr("land_btn_import_ref_tip"))
        import_ref_btn.clicked.connect(self.import_ref_requested.emit)
        load_row.addWidget(import_ref_btn)
        self._open_vanilla_btn = QPushButton(tr("land_btn_open_vanilla"))
        self._open_vanilla_btn.setStyleSheet(_SECONDARY_BTN_STYLE)
        self._open_vanilla_btn.setToolTip(tr("land_btn_open_vanilla_tip"))
        self._open_vanilla_btn.clicked.connect(self.open_vanilla_requested.emit)
        load_row.addWidget(self._open_vanilla_btn)
        ref_card.layout().addLayout(load_row)

        # 原版参考: 透明度 + 缩放 + 铺满 + 隐藏
        (self._vanilla_ref_opacity_slider, self._vanilla_ref_opacity_label,
         self._vanilla_ref_toggle) = self._add_ref_group(
            ref_card, tr("land_section_vanilla_ref"), opacity=30)
        (self._vanilla_ref_scale_slider, self._vanilla_ref_scale_label,
         self._vanilla_ref_fit_btn) = self._add_scale_row(ref_card)

        # 自定义参考图: 同样一套
        (self._ref_opacity_slider, self._ref_opacity_label,
         self._ref_toggle) = self._add_ref_group(
            ref_card, tr("land_section_custom_ref"), opacity=40)
        (self._ref_scale_slider, self._ref_scale_label,
         self._ref_fit_btn) = self._add_scale_row(ref_card)

        # 调整参考图位置（开关 + 调整对象单选）
        self._ref_adjust_btn = QPushButton(tr("land_btn_ref_adjust"))
        self._ref_adjust_btn.setCheckable(True)
        self._ref_adjust_btn.setStyleSheet(_ADJUST_BTN_STYLE)
        self._ref_adjust_btn.toggled.connect(self._on_adjust_toggled)
        ref_card.layout().addWidget(self._ref_adjust_btn)

        target_row = QHBoxLayout()
        target_row.setSpacing(10)
        t_lbl = QLabel(tr("land_label_adjust_target"))
        t_lbl.setStyleSheet(_DIM_LABEL_STYLE)
        target_row.addWidget(t_lbl)
        self._adjust_custom_radio = QRadioButton(tr("land_adjust_custom"))
        self._adjust_custom_radio.setChecked(True)
        self._adjust_vanilla_radio = QRadioButton(tr("land_adjust_vanilla"))
        self._adjust_target_group = QButtonGroup(self)
        for r in (self._adjust_custom_radio, self._adjust_vanilla_radio):
            self._adjust_target_group.addButton(r)
            r.setEnabled(False)          # 平时置灰, 进入调整模式才可用
            target_row.addWidget(r)
        target_row.addStretch()
        self._adjust_custom_radio.toggled.connect(
            lambda on: on and self.ref_adjust_target_changed.emit("custom"))
        self._adjust_vanilla_radio.toggled.connect(
            lambda on: on and self.ref_adjust_target_changed.emit("vanilla"))
        ref_card.layout().addLayout(target_row)

        ref_card.layout().addWidget(_make_hint(tr("land_ref_adjust_hint")))
        lay.addWidget(ref_card)
```

类里追加两个 UI 构造 helper 和三个公开方法 + 槽函数（放在 `_on_land_brush` 前）：

```python
    # ── 参考底图卡片 helper ──
    def _add_ref_group(self, card, title: str, opacity: int):
        """一组参考图控制的头两行: 标题+隐藏钮 / 透明度滑条。"""
        head = QHBoxLayout()
        head.setSpacing(4)
        lbl = QLabel(title)
        lbl.setStyleSheet(_LABEL_STYLE)
        head.addWidget(lbl)
        head.addStretch()
        toggle = QPushButton(tr("land_btn_hide"))
        toggle.setCheckable(True)
        toggle.setStyleSheet(_SECONDARY_BTN_STYLE)
        toggle.setMinimumWidth(50)
        toggle.toggled.connect(
            lambda on, b=toggle: b.setText(
                tr("land_btn_show") if on else tr("land_btn_hide")))
        head.addWidget(toggle)
        card.layout().addLayout(head)

        row = QHBoxLayout()
        row.setSpacing(4)
        cap = QLabel(tr("land_label_opacity"))
        cap.setStyleSheet(_DIM_LABEL_STYLE)
        row.addWidget(cap)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(opacity)
        slider.setStyleSheet(_SLIDER_STYLE)
        val = QLabel(f"{opacity}%")
        val.setStyleSheet(_DIM_LABEL_STYLE)
        val.setFixedWidth(36)
        slider.valueChanged.connect(lambda v, l=val: l.setText(f"{v}%"))
        row.addWidget(slider)
        row.addWidget(val)
        card.layout().addLayout(row)
        return slider, val, toggle

    def _add_scale_row(self, card):
        """一行缩放控制: 缩放滑条 + % + 铺满按钮。"""
        row = QHBoxLayout()
        row.setSpacing(4)
        cap = QLabel(tr("land_label_scale"))
        cap.setStyleSheet(_DIM_LABEL_STYLE)
        row.addWidget(cap)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(10, 500)
        slider.setValue(100)
        slider.setStyleSheet(_SLIDER_STYLE)
        val = QLabel("100%")
        val.setStyleSheet(_DIM_LABEL_STYLE)
        val.setFixedWidth(36)
        slider.valueChanged.connect(lambda v, l=val: l.setText(f"{v}%"))
        fit = QPushButton(tr("land_btn_fit"))
        fit.setStyleSheet(_SECONDARY_BTN_STYLE)
        fit.setMinimumWidth(50)
        row.addWidget(slider)
        row.addWidget(val)
        row.addWidget(fit)
        card.layout().addLayout(row)
        return slider, val, fit

    def _on_adjust_toggled(self, on: bool) -> None:
        self._ref_adjust_btn.setText(
            tr("land_btn_ref_adjust_active") if on else tr("land_btn_ref_adjust"))
        self._adjust_custom_radio.setEnabled(on)
        self._adjust_vanilla_radio.setEnabled(on)
        self.ref_adjust_toggled.emit(on)

    def current_adjust_target(self) -> str:
        """当前调整对象: "vanilla" / "custom"。"""
        return "vanilla" if self._adjust_vanilla_radio.isChecked() else "custom"

    def set_ref_adjust_checked(self, on: bool) -> None:
        """外部（画布 ESC 退出）同步按钮勾选状态。"""
        self._ref_adjust_btn.setChecked(on)

    def set_ref_scale_percent(self, target: str, percent: int) -> None:
        """画布滚轮缩放后回写滑条（blockSignals 防止再触发缩放回环）。"""
        slider = (self._vanilla_ref_scale_slider if target == "vanilla"
                  else self._ref_scale_slider)
        label = (self._vanilla_ref_scale_label if target == "vanilla"
                 else self._ref_scale_label)
        slider.blockSignals(True)
        slider.setValue(percent)
        slider.blockSignals(False)
        label.setText(f"{percent}%")
```

注意：`_DIM` / `_LABEL_STYLE` 等 import 已存在；删除原 53-146 行里被替换的所有旧控件构造代码（`v_lbl` / `v_row` / `c_head` / `c_row` / `scale_row` 等局部变量整段消失）。

- [ ] **Step 5: 跑测试确认通过**

Run: `python -m pytest tests/views/test_land_page_ref_card.py -v`
Expected: 6 passed

- [ ] **Step 6: 跑全量测试防回归**

Run: `python -m pytest -m "not slow" -q`
Expected: 全过（tool_panel property 引用的控件名全部保留）

- [ ] **Step 7: Commit**

```powershell
git add features/map/land/page.py ui/i18n/zh/land.py tests/views/test_land_page_ref_card.py
git commit -m "feat: 参考底图卡片重排（导入置顶+打开原版+双图对称控制+调整模式开关）"
```

---

### Task 4: ToolPanel 转发 + MainWindow 接线 + 手动验证

**Files:**
- Modify: `ui/tool_panel.py`（信号 3 个 + `_connect_land_signals` + property 2 个 + 委托方法 3 个）
- Modify: `views/main_window.py:322-345`（参考图接线区追加）
- Test: 全量 pytest + 手动 GUI 清单

**Interfaces:**
- Consumes: Task 2 的 `set_ref_adjust_mode` / `ref_adjust_exited` / `ref_adjust_scale_changed` / `set_ref_layer_scale` / `fit_ref_layer`；Task 3 的全部新信号/方法；`main_window_file_ops.py` 现成的 `_on_load_vanilla_ref`
- Produces: 完整可用的功能链

- [ ] **Step 1: tool_panel.py 转发**

信号区（`import_ref_requested = pyqtSignal()` 旁）追加：

```python
    open_vanilla_requested = pyqtSignal()
    ref_adjust_toggled = pyqtSignal(bool)
    ref_adjust_target_changed = pyqtSignal(str)
```

`_connect_land_signals` 末尾追加：

```python
        p.open_vanilla_requested.connect(self.open_vanilla_requested)
        p.ref_adjust_toggled.connect(self.ref_adjust_toggled)
        p.ref_adjust_target_changed.connect(self.ref_adjust_target_changed)
```

property 区（`_ref_toggle` 之后）追加：

```python
    @property
    def _vanilla_ref_scale_slider(self) -> QSlider:
        return self._land_page._vanilla_ref_scale_slider

    @property
    def _vanilla_ref_fit_btn(self) -> QPushButton:
        return self._land_page._vanilla_ref_fit_btn

    # 调整参考图模式 — 委托 land page
    def current_adjust_target(self) -> str:
        return self._land_page.current_adjust_target()

    def set_ref_adjust_checked(self, on: bool) -> None:
        self._land_page.set_ref_adjust_checked(on)

    def set_ref_scale_percent(self, target: str, percent: int) -> None:
        self._land_page.set_ref_scale_percent(target, percent)
```

- [ ] **Step 2: main_window.py 接线**

"参考图控件 → 画布"区（322-338 行）末尾追加：

```python
        # 原版参考: 缩放 + 铺满（与自定义图对称）
        tp._vanilla_ref_scale_slider.valueChanged.connect(
            lambda v: cv.set_ref_layer_scale("vanilla", v / 100.0)
        )
        tp._vanilla_ref_fit_btn.clicked.connect(
            lambda: cv.fit_ref_layer("vanilla")
        )
        # 打开原版参考（复用文件菜单动作）
        tp.open_vanilla_requested.connect(self._on_load_vanilla_ref)
        # 调整参考图模式
        tp.ref_adjust_toggled.connect(
            lambda on: cv.set_ref_adjust_mode(
                tp.current_adjust_target() if on else None)
        )
        tp.ref_adjust_target_changed.connect(cv.set_ref_adjust_mode)
        cv.ref_adjust_exited.connect(lambda: tp.set_ref_adjust_checked(False))
        cv.ref_adjust_scale_changed.connect(
            lambda t, s: tp.set_ref_scale_percent(t, int(round(s * 100)))
        )
```

（`ref_adjust_target_changed` 只在单选可用时发射，而单选只在调整模式激活时可用，直接连 `set_ref_adjust_mode` 安全。）

- [ ] **Step 3: 跑全量测试**

Run: `python -m pytest -m "not slow" -q`
Expected: 全过

- [ ] **Step 4: 手动 GUI 验证清单**

Run: `$env:PYTHONIOENCODING='utf-8'; python main.py`

逐项确认：
1. 陆地页卡片①顶部是 [导入参考图…] [打开原版参考] 两个按钮
2. 点「打开原版参考」→ 原版地图出现（游戏目录存在时）
3. 原版参考的缩放滑条/铺满按钮生效，且不影响自定义图
4. 点「🖐 调整参考图位置」→ 按钮变橙、单选可用、画布光标变移动、参考图出现橙色虚线框
5. 调整模式下左键拖动 = 移动参考图，**画笔不落笔**；滚轮 = 缩放参考图且滑条数值同步
6. 单选切「原版」→ 拖拽/滚轮作用到原版图
7. ESC → 按钮弹起、虚线框消失、画笔恢复
8. 平时 Ctrl+左键拖拽 / Ctrl+滚轮 仍作用于自定义图

- [ ] **Step 5: Commit**

```powershell
git add ui/tool_panel.py views/main_window.py
git commit -m "feat: 参考底图新信号接线（打开原版/原版缩放/调整模式联动）"
```

---

## 完成后

- 汇报：改动文件、验证结果、en/ru 待补翻的 key 清单（发版前跑 i18n audit）。
- 不 push，等用户确认。
