"""
地图画布组件 — 基于 QGraphicsView 的大画布
支持六种编辑模式：land / terrain / height / province / state / country
性能优化：脏矩形局部更新，避免每次操作渲染整张地图

从 ui/canvas_widget.py 拆分而来，保留核心逻辑:
- __init__: 场景/图层/状态初始化
- 数据属性 (tile_map, province_map 等)
- 渲染分发 (_full_render / _partial_render)
- 绘制操作 (_stamp_brush / _paint_at / _flood_fill)
- 变换操作 (_apply_transform / _cancel_transform / _end_transform)
- 省份操作 (merge / split / cleanup)
- 模式/工具设置
- 导航辅助
"""
import numpy as np
from PyQt5.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QGraphicsEllipseItem, QGraphicsPathItem, QGraphicsRectItem,
)
from PyQt5.QtCore import Qt, QPoint, QRectF, QRect, pyqtSignal, QTimer
from PyQt5.QtGui import (
    QImage, QPixmap, QPainter, QColor, QWheelEvent, QMouseEvent,
    QPen, QPainterPath, QBrush, QKeyEvent,
)

from data.constants import (
    MAP_WIDTH, MAP_HEIGHT,
    TILE_UNDEFINED, TILE_LAND, TILE_SEA, TILE_LAKE,
    ZOOM_MIN, ZOOM_MAX, ZOOM_STEP,
    BRUSH_DEFAULT,
)
from data.terrain_types import TERRAIN_TYPES, TERRAIN_PALETTE_INDEX, GRAPHICAL_TERRAINS, PALETTE_TO_TYPE
from domain.managers.river import (
    RIVER_DISPLAY_COLORS, RIVER_SOURCE, RIVER_BG_LAND, RIVER_BG_SEA,
    RIVER_ERASE, VALID_RIVER_VALUES,
)

from views.canvas.ref_images import RefImageMixin
from views.canvas.overlays import OverlayMixin, CS_OVERLAY_ALLOWED_MODES
from views.canvas.input_router import InputMixin


class MapCanvas(InputMixin, OverlayMixin, RefImageMixin, QGraphicsView):
    """地图画布，支持缩放/拖动/绘制，脏矩形局部更新"""

    mouse_moved = pyqtSignal(int, int)
    zoom_changed = pyqtSignal(float)
    province_clicked = pyqtSignal(int)
    province_double_clicked = pyqtSignal(int)   # 双击省份（设VP）
    province_right_clicked = pyqtSignal(int)    # 右键省份（设首都）
    province_right_clicked_at = pyqtSignal(int, int, int)  # pid, screen_x, screen_y (右键菜单用)
    provinces_cleared = pyqtSignal()  # 大陆模式修改时自动清除省份
    stroke_started = pyqtSignal()     # 画笔操作开始
    stroke_ended = pyqtSignal()       # 画笔操作结束
    ridge_drawn = pyqtSignal(list)    # 山脉画线完成, [(y,x), ...]
    refine_lasso_drawn = pyqtSignal(list)  # 局部精修套索完成, [(y,x), ...]
    downgrade_lasso_drawn = pyqtSignal(list)  # 选区降级套索完成, [(y,x), ...]
    split_line_drawn = pyqtSignal(int, list)  # 切割线完成, (pid, [(y,x), ...])
    province_gaps_detected = pyqtSignal(list)  # 省份 ID 空洞, [gap_id, ...]

    def __init__(self, parent=None):
        super().__init__(parent)

        # 数据层 — 通过 MapData 集中管理
        # 私有字段是 MapData 数组的别名（指向同一个 numpy 对象）
        from domain.map_data import MapData
        self._map_data = MapData()
        self._tile_map = self._map_data.tile_map
        self._province_map = self._map_data.province_map
        self._terrain_map = self._map_data.terrain_map
        self._height_map = self._map_data.height_map
        self._river_map = self._map_data.river_map

        # 新大陆画笔 mask：记录画了哪些像素（只记录真正从海/湖变陆地的）
        self.new_land_mask = np.zeros((MAP_HEIGHT, MAP_WIDTH), dtype=bool)

        # 河流编辑状态
        self._current_river_type = RIVER_SOURCE

        # 地形画笔模式: False=按省份(默认), True=逐像素画笔
        self._terrain_brush_mode = False
        self._terrain_brush_size = 20  # 独立的地形画笔尺寸，与通用 _brush_size 分离

        # 高度画笔: "off"(按省份) / "raise" / "lower" / "smooth"
        self._height_brush_mode = "off"
        self._height_brush_size = 30
        self._height_brush_strength = 5  # 每刷一下 ±N，平滑时做混合强度

        # 显示缓冲区（BGRA）
        self._display_buffer = np.zeros((MAP_HEIGHT, MAP_WIDTH, 4), dtype=np.uint8)
        self._province_border_buffer = None  # 延迟创建

        # 显示模式渲染器注册表: mode → renderer 模块路径 (延迟加载并缓存)
        from views.canvas.render_registry import DEFAULT_RENDERERS
        self._renderer_paths: dict[str, str] = dict(DEFAULT_RENDERERS)
        self._renderer_cache: dict[str, object] = {}

        # State / Country / Strategic Region / Railway 颜色缓冲区
        self._state_color_rgb = None   # np.ndarray (H, W, 3) or None
        self._country_color_rgb = None  # np.ndarray (H, W, 3) or None
        # 选中国家高亮: 该国 RGB (用于在 country renderer 里 mask 匹配)
        self._highlight_country_rgb: tuple[int, int, int] | None = None
        # 已分配国家的 land 像素 mask (H, W bool) — 让 country renderer 跳过未分配区域不画边
        self._country_assigned_mask: "np.ndarray | None" = None
        # country 边界 cache (避免每次重绘都全图算): (rgb_id, assigned_mask_id) → (white, red)
        self._country_borders_cache: tuple | None = None
        # 地形底图源: "height" (彩色高度图) 或 "terrain" (地形分类图)
        self._terrain_underlay_source: str = "height"
        self._sr_color_rgb = None      # np.ndarray (H, W, 3) or None
        self._railway_color_rgb = None # np.ndarray (H, W, 3) or None
        # 省份属性地形（gameplay terrain）颜色缓冲区
        self._provincial_terrain_color_rgb = None  # np.ndarray (H, W, 3) or None
        # 大陆颜色缓冲区
        self._continent_color_rgb = None  # np.ndarray (H, W, 3) or None

        # 显示/编辑模式
        self._display_mode = "land"

        # 框架工具（新规范）：当不为 None 时，鼠标事件转发给它
        self._framework_tool = None     # core.tools.base.Tool 实例
        self._framework_ctx = None       # ToolContext

        # 当前状态
        self._zoom = 1.0
        self._current_tool = "brush"
        self._current_tile_type = TILE_LAND
        self._current_terrain_index = 0
        self._selected_province_id = 0  # 省份模式下选中的省份ID
        self._selected_province_tile = 0  # 选中省份的地块类型（边界编辑时只能影响同类型像素）
        self._has_provinces = False     # 是否有省份数据（避免每笔都扫描整张图）
        self._current_height_value = 120
        self._brush_size = BRUSH_DEFAULT
        self._is_drawing = False
        self._is_panning = False
        self._pan_start = QPoint()
        self._space_pressed = False
        self._last_draw_pos = None  # 上一次绘制位置，用于插值连线
        self._show_ref_image = True
        self._show_provinces = True

        # 框选模式
        self._selection_mode = False
        self._selection_rect = None  # (x0, y0, x1, y1) scene coords
        self._selection_start = None
        self._selection_callback = None  # 框选完成后的回调

        # 变换工具状态
        self._transform_active = False    # 变换框是否激活
        self._transform_selecting = False # 正在框选阶段
        self._transform_box = None       # (x0, y0, x1, y1) 当前变换框
        self._transform_snippet = None   # 剪切出的 tile_map 片段 (numpy)
        self._transform_orig_box = None  # 原始框位置
        self._transform_drag = None      # 当前拖拽类型: "move"/"tl"/"tr"/"bl"/"br"/"rotate"/None
        self._transform_drag_start = None
        self._transform_angle = 0.0      # 旋转角度（度）
        # 上一次实时 apply 写入的目标 box (x0, y0, x1, y1); 下次 apply 前先擦掉,
        # 防止拖动经过的每个中间位置都留下"踪迹" (土地被复制 bug)
        self._transform_last_written_box: tuple[int, int, int, int] | None = None

        # 脏矩形（需要刷新的区域）
        self._dirty_rect = None  # (x0, y0, x1, y1) 或 None

        # 延迟渲染定时器（合并连续绘制操作）
        self._render_timer = QTimer()
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(16)  # ~60fps
        self._render_timer.timeout.connect(self._flush_dirty)

        # 场景和图层
        self._scene = QGraphicsScene(self)
        self._scene.setSceneRect(0, 0, MAP_WIDTH, MAP_HEIGHT)
        self.setScene(self._scene)

        self._map_pixmap_item = QGraphicsPixmapItem()
        self._scene.addItem(self._map_pixmap_item)

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

        self._province_pixmap_item = QGraphicsPixmapItem()
        self._province_pixmap_item.setOpacity(0.6)
        self._province_pixmap_item.setZValue(2)
        self._scene.addItem(self._province_pixmap_item)

        # 框选矩形（用于框选放大等功能）
        self._selection_rect_item = QGraphicsRectItem()
        self._selection_rect_item.setPen(QPen(QColor(255, 255, 0), 2, Qt.DashLine))
        self._selection_rect_item.setBrush(QBrush(QColor(255, 255, 0, 30)))
        self._selection_rect_item.setZValue(100)
        self._selection_rect_item.setVisible(False)
        self._scene.addItem(self._selection_rect_item)

        # 切割预览线
        from PyQt5.QtWidgets import QGraphicsPathItem
        self._split_line_item = QGraphicsPathItem()
        self._split_line_item.setPen(QPen(QColor(255, 80, 80), 2, Qt.SolidLine))
        self._split_line_item.setZValue(102)
        self._split_line_item.setVisible(False)
        self._scene.addItem(self._split_line_item)

        # 变换框（边框 + 4 个角 handle）
        self._transform_border = QGraphicsRectItem()
        self._transform_border.setPen(QPen(QColor(0, 200, 255), 2))
        self._transform_border.setBrush(QBrush(Qt.NoBrush))
        self._transform_border.setZValue(101)
        self._transform_border.setVisible(False)
        self._scene.addItem(self._transform_border)

        self._transform_handles: dict[str, QGraphicsRectItem] = {}
        for hid in ("tl", "tr", "bl", "br"):
            h = QGraphicsRectItem(-4, -4, 8, 8)
            h.setPen(QPen(QColor(0, 200, 255), 1))
            h.setBrush(QBrush(QColor(255, 255, 255)))
            h.setZValue(102)
            h.setVisible(False)
            self._scene.addItem(h)
            self._transform_handles[hid] = h

        # 画笔预览光标（半透明圆圈）
        self._brush_cursor = QGraphicsEllipseItem()
        self._brush_cursor.setPen(QPen(QColor(255, 255, 255, 180), 1))
        self._brush_cursor.setBrush(QColor(255, 255, 255, 40))
        self._brush_cursor.setZValue(10)
        self._brush_cursor.setVisible(False)
        self._scene.addItem(self._brush_cursor)

        # 密度叠加层
        self._density_overlay_item = QGraphicsPixmapItem()
        self._density_overlay_item.setZValue(5)
        self._density_overlay_item.setVisible(False)
        self._density_overlay_visible = False
        self._scene.addItem(self._density_overlay_item)

        # State 边界叠加层（选州创建战略区域时显示）
        self._state_border_overlay = QGraphicsPixmapItem()
        self._state_border_overlay.setZValue(6)
        self._state_border_overlay.setVisible(False)
        self._scene.addItem(self._state_border_overlay)

        # 地形视图下的国家/州叠加层（半透明国家色 + 白色州边界）
        self._terrain_context_overlay = QGraphicsPixmapItem()
        self._terrain_context_overlay.setZValue(6)
        self._terrain_context_overlay.setVisible(False)
        self._scene.addItem(self._terrain_context_overlay)
        self._terrain_context_visible = False
        self._terrain_ctx_country_mgr = None
        self._terrain_ctx_state_mgr = None

        # State / Country 模式下的地形底图叠加层（用 heightmap 彩色图做参考）
        self._terrain_underlay_item = QGraphicsPixmapItem()
        self._terrain_underlay_item.setZValue(5)
        self._terrain_underlay_item.setVisible(False)
        self._terrain_underlay_item.setOpacity(0.4)
        self._scene.addItem(self._terrain_underlay_item)
        self._terrain_underlay_visible = False
        self._terrain_underlay_opacity = 0.4

        # 套索路径反馈（黄色虚线）
        self._lasso_path_item = QGraphicsPathItem()
        pen = QPen(QColor(255, 230, 0, 230), 2)
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setCosmetic(True)  # 不随缩放变粗细
        self._lasso_path_item.setPen(pen)
        self._lasso_path_item.setZValue(11)
        self._lasso_path_item.setVisible(False)
        self._scene.addItem(self._lasso_path_item)

        # 山脉画线路径反馈（红色实线，比套索粗）
        self._ridge_path_item = QGraphicsPathItem()
        ridge_pen = QPen(QColor(230, 60, 60, 240), 3)
        ridge_pen.setStyle(Qt.PenStyle.SolidLine)
        ridge_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        ridge_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        ridge_pen.setCosmetic(True)
        self._ridge_path_item.setPen(ridge_pen)
        self._ridge_path_item.setZValue(12)
        self._ridge_path_item.setVisible(False)
        self._scene.addItem(self._ridge_path_item)

        # 套索 allowed 区域 overlay（半透明黄色填充）
        self._lasso_overlay = QGraphicsPixmapItem()
        self._lasso_overlay.setZValue(9)
        self._lasso_overlay.setVisible(False)
        self._scene.addItem(self._lasso_overlay)

        # 局部精修套索预览（蓝色虚线多边形）
        self._refine_lasso_item = QGraphicsPathItem()
        refine_pen = QPen(QColor(80, 150, 255, 240), 2)
        refine_pen.setStyle(Qt.PenStyle.DashLine)
        refine_pen.setCosmetic(True)
        self._refine_lasso_item.setPen(refine_pen)
        self._refine_lasso_item.setZValue(12)
        self._refine_lasso_item.setVisible(False)
        self._scene.addItem(self._refine_lasso_item)

        # VP 标记叠加层 (Feature 10)
        self._vp_overlay_item = QGraphicsPixmapItem()
        self._vp_overlay_item.setZValue(5)
        self._vp_overlay_item.setVisible(False)
        self._scene.addItem(self._vp_overlay_item)
        self._vp_data: dict[int, int] = {}  # {province_id: vp_value}

        # 视图设置
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.MinimalViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setMouseTracking(True)
        self.setStyleSheet("background: #050a12; border: none;")

        # 初始全量渲染
        self._full_render()

    # ========== 动态地图尺寸 ==========

    @property
    def map_h(self) -> int:
        return self._display_buffer.shape[0]

    @property
    def map_w(self) -> int:
        return self._display_buffer.shape[1]

    # ========== 数据访问 ==========

    def set_map_data(self, map_data) -> None:
        """替换底层 MapData 并重新绑定所有局部别名。

        调用时机：MainWindow 初始化后 / 新建项目 / 加载项目，
        让 canvas 和 project 共享同一个 MapData 实例，
        这样 controller 通过 Command 修改 project.map_data 的数组时，
        canvas 也能立即看到变化。
        """
        self._map_data = map_data
        self._tile_map = map_data.tile_map
        self._province_map = map_data.province_map
        self._terrain_map = map_data.terrain_map
        self._height_map = map_data.height_map
        self._river_map = map_data.river_map
        self._has_provinces = int(self._province_map.max()) > 0
        # 清除所有缓存
        self._border_cache = None
        if hasattr(self, '_border_base_pixmap'):
            self._border_base_pixmap = None
        self._state_color_rgb = None
        self._country_color_rgb = None
        self._sr_color_rgb = None
        self._railway_color_rgb = None
        self._provincial_terrain_color_rgb = None
        self._continent_color_rgb = None
        h, w = map_data.tile_map.shape[0], map_data.tile_map.shape[1]
        self.new_land_mask = np.zeros((h, w), dtype=bool)
        self._display_buffer = np.zeros((h, w, 4), dtype=np.uint8)
        self._scene.setSceneRect(0, 0, w, h)
        # map_data 换了，地形上下文 overlay 的 pixmap 尺寸不匹配，重建
        if getattr(self, '_terrain_context_visible', False):
            self.refresh_terrain_context_overlay()
        # 地形底图同理 — 跟 heightmap 走
        if getattr(self, '_terrain_underlay_visible', False):
            self.refresh_terrain_underlay()

    @property
    def map_data(self):
        """暴露 MapData 给外部使用高级查询方法（get_neighbors 等）。"""
        return self._map_data

    def set_framework_tool(self, tool_name: str | None, undo_mgr=None,
                            state_mgr=None, country_mgr=None) -> None:
        """启用/禁用一个框架工具。tool_name=None 关闭。"""
        from domain.tools import get_tool, ToolContext

        if tool_name is None:
            if self._framework_tool is not None and self._framework_ctx is not None:
                self._framework_tool.on_cancel(self._framework_ctx)
            self._framework_tool = None
            self._framework_ctx = None
            self._clear_lasso_visual()
            self._render_province_overlay()
            return

        tool = get_tool(tool_name)
        if tool is None:
            return
        if undo_mgr is None:
            return
        self._framework_tool = tool
        self._framework_ctx = ToolContext(
            map_data=self._map_data,
            undo_mgr=undo_mgr,
            state_mgr=state_mgr,
            country_mgr=country_mgr,
            display_mode=self._display_mode,
            brush_size=self._brush_size,
        )

    def _set_layer(self, attr: str, data: np.ndarray, dtype) -> None:
        """统一的图层替换：写入 MapData，同步本地别名。

        如果形状相同，原地写入以保持引用稳定（controller/command 持有的引用不会失效）。
        形状不同时（地图尺寸变化）才替换整个数组。
        """
        existing = getattr(self._map_data, attr, None)
        if existing is not None and existing.shape == data.shape:
            existing[:] = data.astype(dtype)
            # 别名仍指向同一对象，无需更新
        else:
            new_arr = data.astype(dtype)
            setattr(self._map_data, attr, new_arr)
            setattr(self, "_" + attr, new_arr)
            # 地图尺寸变化时，同步 display_buffer 和 scene rect
            h, w = new_arr.shape[:2]
            if (h, w) != (self._display_buffer.shape[0], self._display_buffer.shape[1]):
                self._display_buffer = np.zeros((h, w, 4), dtype=np.uint8)
                self._scene.setSceneRect(0, 0, w, h)

    def _rebind_aliases(self) -> None:
        """重新绑定局部别名到 MapData 当前属性。

        当 Command 或外部代码替换了 MapData 的某个属性（而非原地修改），
        canvas 的 _tile_map 等局部别名会过期。调用此方法刷新。
        """
        self._tile_map = self._map_data.tile_map
        self._province_map = self._map_data.province_map
        self._terrain_map = self._map_data.terrain_map
        self._height_map = self._map_data.height_map
        self._river_map = self._map_data.river_map

    @property
    def tile_map(self) -> np.ndarray:
        return self._tile_map

    @tile_map.setter
    def tile_map(self, data: np.ndarray) -> None:
        self._set_layer("tile_map", data, np.uint8)
        if self._display_mode == "land":
            self._full_render()

    @property
    def province_map(self) -> np.ndarray:
        return self._province_map

    @province_map.setter
    def province_map(self, data: np.ndarray) -> None:
        self._set_layer("province_map", data, np.int32)
        self._has_provinces = int(self._province_map.max()) > 0
        # 省份数据变了，清除边界缓存以便下次重建
        self._border_cache = None
        if hasattr(self, '_border_base_pixmap'):
            self._border_base_pixmap = None
        if self._display_mode == "province":
            self._full_render()
        self._render_province_overlay()
        # 地形视图的国家/州 overlay pixmap 尺寸和内容都要跟着省份图重建
        if getattr(self, '_terrain_context_visible', False):
            self.refresh_terrain_context_overlay()
        if getattr(self, '_terrain_underlay_visible', False):
            self.refresh_terrain_underlay()

    @property
    def terrain_map(self) -> np.ndarray:
        return self._terrain_map

    @terrain_map.setter
    def terrain_map(self, data: np.ndarray) -> None:
        self._set_layer("terrain_map", data, np.uint8)
        if self._display_mode == "terrain":
            self._full_render()

    @property
    def height_map(self) -> np.ndarray:
        return self._height_map

    @height_map.setter
    def height_map(self, data: np.ndarray) -> None:
        self._set_layer("height_map", data, np.uint8)
        if self._display_mode == "height":
            self._full_render()

    @property
    def river_map(self) -> np.ndarray:
        return self._river_map

    @river_map.setter
    def river_map(self, data: np.ndarray) -> None:
        self._set_layer("river_map", data, np.uint8)
        if self._display_mode == "river":
            self._full_render()

    def set_river_type(self, river_type: int) -> None:
        self._current_river_type = max(0, min(255, river_type))

    @property
    def display_mode(self) -> str:
        return self._display_mode

    @display_mode.setter
    def display_mode(self, mode: str) -> None:
        _VALID = (
            "land", "terrain", "height", "province",
            "state", "country", "river", "logistics",
            "continent", "strategic_region", "colormap", "default_map",
            "province_terrain", "preview",
        )
        if mode not in _VALID:
            return
        if mode == self._display_mode:
            return
        self._display_mode = mode
        # 国家/州归属 overlay — 全局开关，仅在基础视图本身不按国家/州染色的模式下显示，
        # 避免在 state/country/continent/strategic_region 模式下双层染色造成混乱。
        overlay = getattr(self, '_terrain_context_overlay', None)
        if overlay is not None:
            if getattr(self, '_terrain_context_visible', False) \
                    and mode in CS_OVERLAY_ALLOWED_MODES:
                self.refresh_terrain_context_overlay()
            else:
                overlay.setVisible(False)
        # 地形底图仅在 state/country 模式下显示
        underlay = getattr(self, '_terrain_underlay_item', None)
        if underlay is not None:
            if getattr(self, '_terrain_underlay_visible', False) and mode in ("state", "country"):
                self.refresh_terrain_underlay()
            else:
                underlay.setVisible(False)
        self._full_render()
        # 后勤模式不再需要 overlay（改用着色图）
        if mode != "logistics" and self._lasso_overlay.isVisible():
            # 离开后勤模式：清掉后勤 overlay（但套索/批量选择的 overlay 会被别处管理）
            # 只有在不是批量选择等状态时才清
            pass  # 先不动，让 set_batch_selection_pids 等管理

    # ========== 工具设置 ==========

    def set_tool(self, tool: str) -> None:
        self._current_tool = tool
        self.setCursor(Qt.CursorShape.OpenHandCursor if tool == "pan"
                       else Qt.CursorShape.CrossCursor)

    def set_tile_type(self, tile_type: int) -> None:
        self._current_tile_type = tile_type

    def set_brush_size(self, size: int) -> None:
        self._brush_size = max(1, min(100, size))

    def set_terrain_index(self, index: int) -> None:
        self._current_terrain_index = max(0, min(255, index))

    def set_terrain_brush_mode(self, brush_mode: bool) -> None:
        """切换地形编辑模式: True=画笔逐像素, False=按省份(默认)"""
        self._terrain_brush_mode = brush_mode

    def set_terrain_brush_size(self, size: int) -> None:
        """地形画笔尺寸 (与通用画笔解耦)."""
        self._terrain_brush_size = max(1, min(200, int(size)))

    def set_height_value(self, value: int) -> None:
        self._current_height_value = max(0, min(255, value))

    def set_height_brush_mode(self, mode: str) -> None:
        """高度画笔模式: 'off' / 'raise' / 'lower' / 'smooth'."""
        if mode not in ("off", "raise", "lower", "smooth"):
            mode = "off"
        self._height_brush_mode = mode
        self.setCursor(Qt.CursorShape.CrossCursor if mode != "off"
                       else Qt.CursorShape.ArrowCursor)

    def set_height_brush_size(self, size: int) -> None:
        self._height_brush_size = max(1, min(400, int(size)))

    def set_height_brush_strength(self, strength: int) -> None:
        self._height_brush_strength = max(1, min(50, int(strength)))

    # ========== State / Country 颜色设置 ==========

    def set_state_colors(self, rgb: np.ndarray) -> None:
        """存储 State 颜色 RGB 数组并触发渲染"""
        self._state_color_rgb = rgb
        if self._display_mode == "state":
            self._full_render()

    def set_country_colors(self, rgb: np.ndarray, assigned_mask=None) -> None:
        """存储 Country 颜色 RGB 数组 + 已分配国家像素 mask, 触发渲染.

        assigned_mask: H×W bool, True = 该像素属于已分配国家的 land
            (海洋/未分配 state 处为 False, country renderer 不在这些边界上画白边).
        """
        self._country_color_rgb = rgb
        self._country_assigned_mask = assigned_mask
        # rgb 变了 → country renderer 边界 cache 和 state renderer 国家边界 cache 都失效
        self._country_borders_cache = None
        self._state_country_borders_cache = None
        # state 模式也叠加国家边界 → 改国家归属时需要刷新
        if self._display_mode in ("country", "state"):
            self._full_render()

    def set_highlight_country(self, rgb: tuple[int, int, int] | None) -> None:
        """设置选中国家的 RGB.

        country mode 下: 该国边界 2 像素红描边.
        state mode 下: 该国全部像素叠加暖黄, 一眼看清同 owner 还有哪些州.
        传 None 取消.
        """
        self._highlight_country_rgb = rgb
        # 高亮不影响国家边界 cache, 只需重绘
        if self._display_mode in ("country", "state"):
            self._full_render()

    def set_terrain_underlay_visible(self, visible: bool) -> None:
        """开关 state/country 模式下的地形底图叠加层。"""
        self._terrain_underlay_visible = bool(visible)
        self.refresh_terrain_underlay()

    def set_terrain_underlay_opacity(self, opacity: float) -> None:
        """设置地形底图不透明度 (0.0 全透明 ~ 1.0 完全不透明)。"""
        self._terrain_underlay_opacity = max(0.0, min(1.0, float(opacity)))
        item = getattr(self, "_terrain_underlay_item", None)
        if item is not None:
            item.setOpacity(self._terrain_underlay_opacity)

    def set_terrain_underlay_source(self, source: str) -> None:
        """切换地形底图源: 'height' (彩色高度图) 或 'terrain' (地形分类图)."""
        if source not in ("height", "terrain"):
            return
        self._terrain_underlay_source = source
        self.refresh_terrain_underlay()

    def set_sr_colors(self, rgb: np.ndarray) -> None:
        """存储 Strategic Region 颜色 RGB 数组并触发渲染"""
        self._sr_color_rgb = rgb
        if self._display_mode == "strategic_region":
            self._full_render()

    def set_railway_colors(self, rgb: np.ndarray) -> None:
        """存储铁路等级颜色 RGB 数组并触发渲染"""
        self._railway_color_rgb = rgb
        if self._display_mode == "logistics":
            self._full_render()

    def set_provincial_terrain_colors(self, rgb: np.ndarray) -> None:
        """存储省份属性地形 RGB 数组并触发渲染"""
        self._provincial_terrain_color_rgb = rgb
        if self._display_mode == "province_terrain":
            self._full_render()

    def set_continent_colors(self, rgb: np.ndarray) -> None:
        """存储大陆颜色 RGB 数组并触发渲染"""
        self._continent_color_rgb = rgb
        if self._display_mode == "continent":
            self._full_render()

    def set_batch_selection_pids(self, pids: list[int]) -> None:
        """高亮显示批量选中的省份（用于创建 state/country 等场景）。

        pids 为空时清除高亮。使用半透明黄色 overlay。
        """
        from PyQt5.QtGui import QImage, QPixmap
        if not pids or self._province_map is None:
            self._lasso_overlay.setVisible(False)
            return
        mask = np.isin(self._province_map, list(pids))
        h, w = self._province_map.shape
        rgba = np.zeros((h, w, 4), dtype=np.uint8)
        # 半透明亮黄 (BGRA 字节序: B=0, G=220, R=255, A=160)
        rgba[mask] = (0, 220, 255, 160)
        img = QImage(rgba.data, w, h, w * 4, QImage.Format.Format_ARGB32)
        img._ref = rgba  # 防止内存被释放
        self._lasso_overlay.setPixmap(QPixmap.fromImage(img))
        self._lasso_overlay.setVisible(True)

    def refresh_logistics_overlay(self) -> None:
        """后勤模式下绘制补给节点和铁路 overlay（在 _lasso_overlay 上画）。

        补给节点：小绿圆，半径=3+level
        铁路：彩色线（level 1=细灰 / level 5=粗红），线宽 = 1+level
        """
        from PyQt5.QtGui import QImage, QPixmap, QPainter, QColor, QPen
        if self._province_map is None:
            self._lasso_overlay.setVisible(False)
            return

        pm = self._province_map
        tm = self._tile_map
        h, w = pm.shape

        # 拿到 managers（挂在 canvas 实例上）
        supply_mgr = getattr(self, '_supply_mgr', None)
        railway_mgr = getattr(self, '_railway_mgr', None)
        if supply_mgr is None and railway_mgr is None:
            self._lasso_overlay.setVisible(False)
            return

        # 预计算省份质心（用于画节点/线条）
        max_pid = int(pm.max())
        if max_pid <= 0:
            return
        flat = pm.ravel()
        pid_count = np.bincount(flat, minlength=max_pid + 1)
        ys_grid, xs_grid = np.mgrid[0:h, 0:w]
        sum_y = np.bincount(flat, weights=ys_grid.ravel().astype(np.float64), minlength=max_pid + 1)
        sum_x = np.bincount(flat, weights=xs_grid.ravel().astype(np.float64), minlength=max_pid + 1)

        # 用 QPainter 在 transparent QImage 上画
        img = QImage(w, h, QImage.Format.Format_ARGB32)
        img.fill(0)  # 全透明
        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # 铁路线（级别 1-5 颜色由灰到红，粗细从 2 到 6）
        RAIL_COLORS = {
            1: QColor(120, 120, 140, 200),  # 灰
            2: QColor(100, 160, 100, 210),  # 深绿
            3: QColor(230, 180, 60, 220),   # 金黄
            4: QColor(230, 130, 60, 230),   # 橙
            5: QColor(230, 60, 60, 240),    # 红（最高级）
        }
        # 铁路线：只画陆地省份之间的线段，跳过海洋省份（避免跨海飞线）
        if railway_mgr is not None:
            from data.constants import TILE_LAND
            for entry in railway_mgr._entries:
                lvl = entry.level
                color = RAIL_COLORS.get(lvl, RAIL_COLORS[1])
                pen = QPen(color, 1 + lvl)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                pts = []
                for pid in entry.province_ids:
                    if 0 < pid <= max_pid and pid_count[pid] > 0:
                        # 检查省份是否为陆地（跳过海洋/湖泊省份）
                        cy_idx = int(sum_y[pid] / pid_count[pid])
                        cx_idx = int(sum_x[pid] / pid_count[pid])
                        cy_idx = min(cy_idx, h - 1)
                        cx_idx = min(cx_idx, w - 1)
                        if tm is not None and int(tm[cy_idx, cx_idx]) != TILE_LAND:
                            # 海洋省份 → 断开线段（后面重新开始）
                            pts.append(None)
                            continue
                        pts.append((sum_x[pid] / pid_count[pid], sum_y[pid] / pid_count[pid]))
                # 画线段，遇到 None 断开
                for i in range(len(pts) - 1):
                    if pts[i] is None or pts[i + 1] is None:
                        continue
                    x1, y1 = pts[i]
                    x2, y2 = pts[i + 1]
                    # 过长线段跳过（跨海连接 > 200px）
                    if abs(x1 - x2) > 200 or abs(y1 - y2) > 200:
                        continue
                    painter.drawLine(int(x1), int(y1), int(x2), int(y2))

        # 海峡/邻接 — 不在后勤 overlay 画（太多会乱），只在邻接对话框里管理
        # 如果需要可在邻接对话框打开时单独渲染

        # 补给节点（菱形 + 十字标志，HOI4 风格）
        if supply_mgr is not None:
            from PyQt5.QtCore import QPointF
            from PyQt5.QtGui import QPolygonF
            for pid, node in supply_mgr._nodes.items():
                if 0 < pid <= max_pid and pid_count[pid] > 0:
                    cx = int(sum_x[pid] / pid_count[pid])
                    cy = int(sum_y[pid] / pid_count[pid])
                    r = 4  # 菱形半径
                    diamond = QPolygonF([
                        QPointF(cx, cy - r),
                        QPointF(cx + r, cy),
                        QPointF(cx, cy + r),
                        QPointF(cx - r, cy),
                    ])
                    painter.setPen(QPen(QColor(0, 0, 0, 230), 1))
                    painter.setBrush(QColor(60, 200, 60, 240))
                    painter.drawPolygon(diamond)
                    # 白色十字
                    painter.setPen(QPen(QColor(255, 255, 255, 255), 1))
                    painter.drawLine(cx - 2, cy, cx + 2, cy)
                    painter.drawLine(cx, cy - 2, cx, cy + 2)

        painter.end()
        self._lasso_overlay.setPixmap(QPixmap.fromImage(img))
        self._lasso_overlay.setVisible(True)

    # ── 变换工具 ──

    def _apply_transform(self) -> None:
        """将变换结果（缩放+旋转）写入 tile_map。"""
        if self._transform_snippet is None or self._transform_box is None:
            return

        from scipy.ndimage import zoom, rotate

        x0, y0, x1, y1 = [int(v) for v in self._transform_box]
        x0 = max(0, x0); y0 = max(0, y0)
        x1 = min(self.map_w, x1); y1 = min(self.map_h, y1)
        tw, th = x1 - x0, y1 - y0
        if tw < 2 or th < 2:
            return

        # 1. 缩放 snippet 到目标尺寸
        src_h, src_w = self._transform_snippet.shape
        zy = th / src_h
        zx = tw / src_w
        scaled = zoom(self._transform_snippet.astype(np.float32), (zy, zx), order=0)
        scaled = np.round(scaled).astype(np.uint8)

        # 2. 旋转（如果有角度）
        if abs(self._transform_angle) > 0.5:
            # cval=TILE_SEA 填充旋转后的空白区域
            rotated = rotate(scaled.astype(np.float32), -self._transform_angle,
                             reshape=False, order=0, cval=float(TILE_SEA))
            scaled = np.round(rotated).astype(np.uint8)

        # 3. 先清除旧变换区域，再写入
        # 清除整个可能被影响的区域
        ox0, oy0, ox1, oy1 = self._transform_orig_box
        self._tile_map[oy0:oy1, ox0:ox1] = TILE_SEA  # 清原位
        # 擦上一次实时 apply 写入的位置 — 修复"拖动留下复制痕迹"bug
        if self._transform_last_written_box is not None:
            lx0, ly0, lx1, ly1 = self._transform_last_written_box
            self._tile_map[ly0:ly1, lx0:lx1] = TILE_SEA
        # 也清当前框位置（可能被上次预览污染）
        self._tile_map[y0:y1, x0:x1] = TILE_SEA

        # 写入
        sh, sw = scaled.shape
        ph = min(sh, y1 - y0)
        pw = min(sw, x1 - x0)
        self._tile_map[y0:y0 + ph, x0:x0 + pw] = scaled[:ph, :pw]
        self._transform_last_written_box = (x0, y0, x0 + pw, y0 + ph)
        # _tile_map 和 _map_data.tile_map 是同一个数组，无需额外同步
        self._full_render()

    def _cancel_transform(self) -> None:
        """取消变换，恢复原始状态。"""
        if self._transform_snippet is not None and self._transform_orig_box is not None:
            # 先擦上一次实时 apply 留在画布上的内容 — 否则 ESC 取消时仍有"复制"残留
            if self._transform_last_written_box is not None:
                lx0, ly0, lx1, ly1 = self._transform_last_written_box
                self._tile_map[ly0:ly1, lx0:lx1] = TILE_SEA
            # 恢复原始片段到原始位置
            ox0, oy0, ox1, oy1 = self._transform_orig_box
            self._tile_map[oy0:oy1, ox0:ox1] = self._transform_snippet
            # _tile_map 和 _map_data.tile_map 是同一个数组，无需额外同步
            self._full_render()
        self._end_transform()

    def _end_transform(self) -> None:
        """清理变换状态。"""
        self._transform_active = False
        self._transform_selecting = False
        self._transform_box = None
        self._transform_snippet = None
        self._transform_orig_box = None
        self._transform_drag = None
        self._transform_angle = 0.0
        self._transform_last_written_box = None
        self._update_transform_visuals()

    # ── 框选模式 ──

    def start_selection_mode(self, callback) -> None:
        """进入框选模式。用户拖拽出矩形后调用 callback(x0, y0, x1, y1)."""
        self._selection_mode = True
        self._selection_callback = callback
        self._selection_rect_item.setVisible(False)
        self.setCursor(Qt.CrossCursor)

    def _finish_selection(self) -> None:
        """框选完成，调用回调。"""
        self._selection_mode = False
        self._selection_rect_item.setVisible(False)
        self.setCursor(Qt.CursorShape.CrossCursor)
        if self._selection_rect and self._selection_callback:
            x0, y0, x1, y1 = self._selection_rect
            if x1 > x0 + 5 and y1 > y0 + 5:  # 最小 5px
                self._selection_callback(x0, y0, x1, y1)
        self._selection_rect = None
        self._selection_callback = None

    # ========== 渲染（性能核心） ==========

    def register_renderer(self, mode: str, module_path: str) -> None:
        """注册/覆盖一个显示模式的渲染器模块 (运行时扩展点, 如预览模式)。

        renderer 模块约定见 views/canvas/render_registry.py 模块说明。
        """
        self._renderer_paths[mode] = module_path
        self._renderer_cache.pop(mode, None)

    def _resolve_renderer(self, mode: str):
        """按模式取渲染器模块。未注册的模式回退 land; 延迟 import 并缓存。"""
        if mode not in self._renderer_cache:
            import importlib
            path = self._renderer_paths.get(mode) or self._renderer_paths["land"]
            self._renderer_cache[mode] = importlib.import_module(path)
        return self._renderer_cache[mode]

    def _full_render(self) -> None:
        """全量渲染整个地图到显示缓冲区（根据当前模式）"""
        self._resolve_renderer(self._display_mode).render(self)
        self._update_pixmap_from_buffer()
        # VP 叠加层可见性切换（不重绘，用缓存）
        self._update_vp_visibility()
        # 密度叠加层：由 app_controller 管理显隐，这里只刷新内容
        if getattr(self, '_density_overlay_visible', False):
            self._render_density_overlay()

    def _partial_render(self, x0: int, y0: int, x1: int, y1: int) -> None:
        """局部渲染指定矩形区域（根据当前模式）"""
        renderer = self._resolve_renderer(self._display_mode)
        partial = getattr(renderer, "partial_render", None)
        if partial is None:
            # 该渲染器不支持局部渲染 (整图合成类, 如预览) → 回退全量
            self._full_render()
            return
        partial(self, x0, y0, x1, y1)
        self._update_pixmap_from_buffer()

    # ---------- 通用渲染辅助 ----------

    def _update_pixmap_from_buffer(self) -> None:
        """将显示缓冲区写入 QPixmap"""
        img = QImage(self._display_buffer.data, self.map_w, self.map_h,
                     self.map_w * 4, QImage.Format.Format_RGB32)
        img._ref = self._display_buffer  # 防止 GC
        self._map_pixmap_item.setPixmap(QPixmap.fromImage(img))

    def _cleanup_after_province_edit(self) -> None:
        """边界编辑结束后的安全清理：
        1. 修复可能产生的 X-crossings
        2. 修复可能产生的不连通碎片（边界编辑可能把对方省份切成两半）
        3. 压实 ID（防止某省份被推到 0 像素消失后留下 gap）
        4. 维护选中省份 ID 在压实后仍指向正确省份
        """
        from domain.validators.province import fix_x_crossings
        from domain.generators.province import _fix_non_contiguous_fast, compact_province_ids

        old_sel = self._selected_province_id

        # 1. X-crossings
        for _ in range(5):
            if fix_x_crossings(self._province_map) == 0:
                break

        # 2. 不连通碎片
        _fix_non_contiguous_fast(self._province_map)

        # 3. 压实前先记录 selected 是否还存在
        sel_existed = bool((self._province_map == old_sel).any()) if old_sel > 0 else False

        # 4. 压实 ID（用映射表追踪 selected 的新 ID）
        if old_sel > 0 and sel_existed:
            unique_before = np.unique(self._province_map)
            compact_province_ids(self._province_map)
            unique_after = np.unique(self._province_map)
            # 找出 old_sel 在压实后的新 ID
            old_list = unique_before.tolist()
            new_list = unique_after.tolist()
            if old_sel in old_list:
                idx = old_list.index(old_sel)
                self._selected_province_id = int(new_list[idx])
        else:
            compact_province_ids(self._province_map)
            if not sel_existed:
                # 选中省份被推没了
                self._selected_province_id = 0

    def center_on_pixel(self, x: int, y: int, zoom: float | None = None) -> None:
        """让画布中心对准地图坐标 (x, y)，可选放大到 zoom 倍。
        用于验证对话框跳转到问题位置。"""
        if not (0 <= x < self.map_w and 0 <= y < self.map_h):
            return
        if zoom is not None:
            self.resetTransform()
            self.scale(zoom, zoom)
        self.centerOn(float(x), float(y))

    def center_on_province(self, pid: int) -> None:
        """跳转到指定省份的中心，并选中它"""
        if pid <= 0 or pid > self._province_map.max():
            return
        ys, xs = np.where(self._province_map == pid)
        if len(ys) == 0:
            return
        cx = int(xs.mean())
        cy = int(ys.mean())
        self._selected_province_id = pid
        self._selected_province_tile = int(self._tile_map[cy, cx])
        self._render_province_overlay()
        self.center_on_pixel(cx, cy, zoom=2.0)

    def split_province(self, pid: int) -> bool:
        """切割省份：沿中线把一个省份分成两半，新半用新ID"""
        if pid <= 0:
            return False
        mask = self._province_map == pid
        ys, xs = np.where(mask)
        if len(ys) < 2:
            return False

        # 沿较长轴的中线切割
        y_range = ys.max() - ys.min()
        x_range = xs.max() - xs.min()
        new_id = int(self._province_map.max()) + 1

        if x_range >= y_range:
            # 水平方向更宽，沿 x 中线切
            mid_x = (xs.min() + xs.max()) // 2
            right_half = mask & (np.arange(self.map_w)[np.newaxis, :] > mid_x)
        else:
            # 垂直方向更高，沿 y 中线切
            mid_y = (ys.min() + ys.max()) // 2
            right_half = mask & (np.arange(self.map_h)[:, np.newaxis] > mid_y)

        if not np.any(right_half):
            return False

        self._province_map[right_half] = new_id
        self._full_render()
        self._render_province_overlay()
        return True

    def refresh_display(self) -> None:
        self._border_cache = None
        if hasattr(self, '_border_base_pixmap'):
            self._border_base_pixmap = None
        self._full_render()
        self._render_province_overlay()

    # ========== 脏矩形系统 ==========

    def _mark_dirty(self, x0: int, y0: int, x1: int, y1: int) -> None:
        """标记脏区域，合并多次绘制"""
        if self._dirty_rect is None:
            self._dirty_rect = (x0, y0, x1, y1)
        else:
            dx0, dy0, dx1, dy1 = self._dirty_rect
            self._dirty_rect = (min(dx0, x0), min(dy0, y0), max(dx1, x1), max(dy1, y1))
        if not self._render_timer.isActive():
            self._render_timer.start()

    def _flush_dirty(self) -> None:
        """刷新脏区域"""
        if self._dirty_rect is None:
            return
        x0, y0, x1, y1 = self._dirty_rect
        self._dirty_rect = None
        self._partial_render(x0, y0, x1, y1)

    # ========== 绘制操作 ==========

    def _stamp_brush(self, cx: int, cy: int) -> None:
        """在单个位置盖一个圆形笔刷印章（根据当前模式）"""
        import numpy as np

        # 省份模式：固定 1 像素，不依赖刷子大小（边界编辑要精确）
        if self._display_mode == "province":
            r = 0
        else:
            r = self._brush_size // 2
        x0 = max(0, cx - r)
        y0 = max(0, cy - r)
        x1 = min(self.map_w, cx + r + 1)
        y1 = min(self.map_h, cy + r + 1)
        if x0 >= x1 or y0 >= y1:
            return

        # 构建圆形 mask（r >= 2 时用圆，小笔刷不需要）
        if r >= 2:
            yy, xx = np.ogrid[y0:y1, x0:x1]
            circle = (yy - cy) ** 2 + (xx - cx) ** 2 <= r * r
        else:
            circle = None  # 小笔刷直接全覆盖

        mode = self._display_mode

        if mode == "land":
            # 密度画笔模式（密度遮罩开启时）
            if getattr(self, '_density_overlay_visible', False):
                dm = getattr(self._map_data, 'density_map', None) if self._map_data else None
                if dm is not None:
                    # 用密度专属画笔大小
                    dr = getattr(self, '_density_brush_size', 30) // 2
                    dy0, dy1 = max(0, cy - dr), min(self.map_h, cy + dr + 1)
                    dx0, dx1 = max(0, cx - dr), min(self.map_w, cx + dr + 1)
                    yy_d, xx_d = np.ogrid[dy0:dy1, dx0:dx1]
                    dist_sq = (yy_d - cy) ** 2 + (xx_d - cx) ** 2
                    r_sq = dr * dr
                    d_circle = dist_sq <= r_sq
                    dv = getattr(self, '_density_paint_value', 0.8)
                    soft = getattr(self, '_density_soft_edge', 0.5)
                    if soft > 0.01:
                        dist_norm = np.sqrt(dist_sq[d_circle].astype(np.float32)) / max(dr, 1)
                        falloff = np.exp(-dist_norm * dist_norm / (2 * soft * soft))
                        old_vals = dm[dy0:dy1, dx0:dx1][d_circle]
                        dm[dy0:dy1, dx0:dx1][d_circle] = old_vals + (dv - old_vals) * falloff
                    else:
                        dm[dy0:dy1, dx0:dx1][d_circle] = dv
                return

            # 已有省份时不再自动清除 — 用户可能只是想扩张陆地
            # 新画的陆地区域 province_map 保持 0（未分配），
            # 后续用"增量生成省份"给新区域补省份

            if self._current_tool == "eraser":
                if circle is not None:
                    self._tile_map[y0:y1, x0:x1][circle] = TILE_SEA
                else:
                    self._tile_map[y0:y1, x0:x1] = TILE_SEA
            elif self._current_tool in ("brush", "new_land"):
                tile_val = TILE_LAND if self._current_tool == "new_land" else self._current_tile_type
                if self._current_tool == "new_land":
                    # 记录真正从非陆地变成陆地的像素（旧陆地不记）
                    sub = self._tile_map[y0:y1, x0:x1]
                    if circle is not None:
                        changed = circle & (sub != TILE_LAND)
                        self.new_land_mask[y0:y1, x0:x1][changed] = True
                        sub[circle] = tile_val
                    else:
                        changed = sub != TILE_LAND
                        self.new_land_mask[y0:y1, x0:x1][changed] = True
                        sub[:] = tile_val
                else:
                    if circle is not None:
                        self._tile_map[y0:y1, x0:x1][circle] = tile_val
                    else:
                        self._tile_map[y0:y1, x0:x1] = tile_val

        elif mode == "terrain":
            if not self._terrain_brush_mode:
                return
            # 用独立的地形画笔尺寸，忽略通用 brush_size
            tr = self._terrain_brush_size // 2
            if tr < 1:
                tr = 1
            ty0 = max(0, cy - tr)
            ty1 = min(self.map_h, cy + tr + 1)
            tx0 = max(0, cx - tr)
            tx1 = min(self.map_w, cx + tr + 1)
            if ty0 >= ty1 or tx0 >= tx1:
                return
            yy_t, xx_t = np.ogrid[ty0:ty1, tx0:tx1]
            dist_sq_t = (yy_t - cy) ** 2 + (xx_t - cx) ** 2
            t_circle = dist_sq_t <= tr * tr
            # 海/湖保护：视觉地形不改海和湖
            sub_tile = self._tile_map[ty0:ty1, tx0:tx1]
            t_circle = t_circle & (sub_tile == TILE_LAND)
            if not np.any(t_circle):
                self._mark_dirty(tx0, ty0, tx1, ty1)
                return
            if self._current_tool == "eraser":
                self._terrain_map[ty0:ty1, tx0:tx1][t_circle] = 0
            elif self._current_tool == "brush":
                self._terrain_map[ty0:ty1, tx0:tx1][t_circle] = self._current_terrain_index
            self._mark_dirty(tx0, ty0, tx1, ty1)
            return

        elif mode == "height":
            if self._height_brush_mode == "off":
                return
            # 用独立的高度画笔尺寸，忽略通用 brush_size
            hr = self._height_brush_size // 2
            if hr < 1:
                hr = 1
            hy0 = max(0, cy - hr)
            hy1 = min(self.map_h, cy + hr + 1)
            hx0 = max(0, cx - hr)
            hx1 = min(self.map_w, cx + hr + 1)
            if hy0 >= hy1 or hx0 >= hx1:
                return
            yy_h, xx_h = np.ogrid[hy0:hy1, hx0:hx1]
            dist_sq = (yy_h - cy) ** 2 + (xx_h - cx) ** 2
            r_sq = hr * hr
            disk = dist_sq <= r_sq
            # 只改陆地像素（海和湖都不动）
            sub_tile = self._tile_map[hy0:hy1, hx0:hx1]
            disk = disk & (sub_tile == TILE_LAND)
            if not np.any(disk):
                return
            # 距离衰减（0..1, 中心最强, 边缘最弱）
            dist_norm = np.sqrt(dist_sq.astype(np.float32)) / max(hr, 1)
            falloff = np.clip(1.0 - dist_norm, 0.0, 1.0)
            sub_h = self._height_map[hy0:hy1, hx0:hx1].astype(np.int16)
            strength = float(self._height_brush_strength)
            if self._height_brush_mode == "raise":
                delta = (falloff * strength).astype(np.int16)
                new_h = np.clip(sub_h + delta, 0, 255).astype(np.uint8)
                self._height_map[hy0:hy1, hx0:hx1][disk] = new_h[disk]
                # 被抬起来的陆地如果还低于海平面，拉到海平面+1
                from data.constants import SEA_LEVEL
                low_mask = disk & (self._height_map[hy0:hy1, hx0:hx1] <= SEA_LEVEL)
                if np.any(low_mask):
                    self._height_map[hy0:hy1, hx0:hx1][low_mask] = SEA_LEVEL + 1
            elif self._height_brush_mode == "lower":
                delta = (falloff * strength).astype(np.int16)
                new_h = np.clip(sub_h - delta, 0, 255).astype(np.uint8)
                self._height_map[hy0:hy1, hx0:hx1][disk] = new_h[disk]
                # 不让陆地下沉到海平面以下（保持陆地身份）
                from data.constants import SEA_LEVEL
                below = disk & (self._height_map[hy0:hy1, hx0:hx1] <= SEA_LEVEL)
                if np.any(below):
                    self._height_map[hy0:hy1, hx0:hx1][below] = SEA_LEVEL + 1
            elif self._height_brush_mode == "smooth":
                # 盒式模糊（只在 disk 内取均值）：用 disk 像素平均拉近
                area_vals = sub_h[disk]
                avg = int(area_vals.mean())
                blend = falloff * (strength / 10.0)  # 10 强度 = 完全拉到均值
                blend = np.clip(blend, 0.0, 1.0)
                new_h = (sub_h * (1.0 - blend) + avg * blend).astype(np.int16)
                new_h = np.clip(new_h, 0, 255).astype(np.uint8)
                self._height_map[hy0:hy1, hx0:hx1][disk] = new_h[disk]
            self._mark_dirty(hx0, hy0, hx1, hy1)
            return

        elif mode == "province":
            if self._selected_province_id <= 0:
                return
            sub_pm = self._province_map[y0:y1, x0:x1]
            sub_tm = self._tile_map[y0:y1, x0:x1]
            mask = (
                (sub_tm == self._selected_province_tile)
                & (sub_pm != 0)
                & (sub_pm != self._selected_province_id)
            )
            sub_pm[mask] = self._selected_province_id

        elif mode == "river":
            if self._current_tool == "eraser":
                if circle is not None:
                    self._river_map[y0:y1, x0:x1][circle] = RIVER_ERASE
                else:
                    self._river_map[y0:y1, x0:x1] = RIVER_ERASE
            elif self._current_tool == "brush":
                if circle is not None:
                    self._river_map[y0:y1, x0:x1][circle] = self._current_river_type
                else:
                    self._river_map[y0:y1, x0:x1] = self._current_river_type

        self._mark_dirty(x0, y0, x1, y1)

    def _paint_at(self, scene_x: int, scene_y: int) -> None:
        """在指定位置绘制，并与上一个位置做插值避免断线。

        河流模式用**阶梯式正交路径**（先水平后垂直），符合 HOI4 规则
        （pixels do not connect diagonally — Paradox wiki《Map modding》）。
        其它模式用 Bresenham 斜线（更平滑）。
        """
        if self._last_draw_pos is not None:
            lx, ly = self._last_draw_pos
            dx = abs(scene_x - lx)
            dy = abs(scene_y - ly)
            steps = max(dx, dy)
            if self._display_mode == "river":
                # 河流：永远走阶梯（哪怕只是 1 像素的对角移动也要走正交）
                # 慢速拖鼠标每次只报 1px，dx=dy=1 时 steps=1，
                # 走直接 stamp 会产生一串对角像素 → 不合法
                if dx > 0 or dy > 0:
                    self._stamp_orthogonal(lx, ly, scene_x, scene_y)
            elif steps > 1:
                # 其它模式：Bresenham 斜线插值（平滑）
                for i in range(1, steps + 1):
                    t = i / steps
                    ix = int(lx + (scene_x - lx) * t)
                    iy = int(ly + (scene_y - ly) * t)
                    self._stamp_brush(ix, iy)
            else:
                self._stamp_brush(scene_x, scene_y)
        else:
            self._stamp_brush(scene_x, scene_y)

        self._last_draw_pos = (scene_x, scene_y)

    def _stamp_orthogonal(self, x0: int, y0: int, x1: int, y1: int) -> None:
        """正交阶梯画线：先沿 x 方向走一格一格，再沿 y 方向。
        保证相邻两像素必然上下左右相贴，不产生对角连接。
        用于河流模式 — HOI4 规定河流只能正交连接。
        """
        # 水平段
        x = x0
        step_x = 1 if x1 > x0 else -1 if x1 < x0 else 0
        while x != x1:
            x += step_x
            self._stamp_brush(x, y0)
        # 垂直段
        y = y0
        step_y = 1 if y1 > y0 else -1 if y1 < y0 else 0
        while y != y1:
            y += step_y
            self._stamp_brush(x1, y)

    def _flood_fill(self, x: int, y: int) -> None:
        if x < 0 or x >= self.map_w or y < 0 or y >= self.map_h:
            return

        mode = self._display_mode

        if mode in ("province", "state", "country", "river"):
            return  # 这些模式不支持填充

        # 确定填充目标数组和填充值
        if mode == "land":
            data = self._tile_map
            fill_val = self._current_tile_type
        elif mode == "terrain":
            data = self._terrain_map
            fill_val = self._current_terrain_index
        elif mode == "height":
            data = self._height_map
            fill_val = self._current_height_value
        else:
            return

        target = data[y, x]
        if target == fill_val:
            return

        stack = [(x, y)]
        visited = np.zeros((self.map_h, self.map_w), dtype=bool)

        while stack:
            cx, cy = stack.pop()
            if cx < 0 or cx >= self.map_w or cy < 0 or cy >= self.map_h:
                continue
            if visited[cy, cx] or data[cy, cx] != target:
                continue

            left = cx
            while left > 0 and data[cy, left - 1] == target and not visited[cy, left - 1]:
                left -= 1
            right = cx
            while right < self.map_w - 1 and data[cy, right + 1] == target and not visited[cy, right + 1]:
                right += 1

            data[cy, left:right + 1] = fill_val
            visited[cy, left:right + 1] = True

            for nx in range(left, right + 1):
                if cy > 0 and not visited[cy - 1, nx] and data[cy - 1, nx] == target:
                    stack.append((nx, cy - 1))
                if cy < self.map_h - 1 and not visited[cy + 1, nx] and data[cy + 1, nx] == target:
                    stack.append((nx, cy + 1))

        # 填充后全量渲染（因为区域不确定）
        self._full_render()

    # ========== 事件辅助 ==========

    def _scene_pos(self, event: QMouseEvent) -> tuple[int, int]:
        pos = self.mapToScene(event.pos())
        return int(pos.x()), int(pos.y())

    def _scene_pos_clamped(self, event: QMouseEvent) -> tuple[int, int]:
        """返回限制在地图边界内的场景坐标"""
        sx, sy = self._scene_pos(event)
        return max(0, min(self.map_w - 1, sx)), max(0, min(self.map_h - 1, sy))

    def _is_in_bounds(self, sx: int, sy: int) -> bool:
        """检查坐标是否在地图边界内"""
        return 0 <= sx < self.map_w and 0 <= sy < self.map_h

    def cleanup_mode_state(self) -> None:
        """清理所有临时模式状态。模式切换时调用，防止状态残留导致异常。"""
        # 变换工具状态
        if self._transform_active:
            self._end_transform()
        self._transform_selecting = False
        self._transform_box = None
        self._transform_snippet = None
        self._transform_orig_box = None
        self._transform_drag = None
        self._transform_drag_start = None
        self._transform_angle = 0.0
        self._transform_last_written_box = None

        # 框选状态
        self._selection_mode = False
        self._selection_rect = None
        self._selection_start = None
        self._selection_rect_item.setVisible(False)

        # 绘制状态
        self._is_drawing = False
        self._last_draw_pos = None

        # 框架工具
        self._framework_tool = None

        # 省份选中
        self._selected_province_id = 0

        # lasso / overlay 清理
        self._clear_lasso_visual()

        # 光标重置
        self.setCursor(Qt.CursorShape.CrossCursor)

    def fit_in_view(self) -> None:
        self.fitInView(QRectF(0, 0, self.map_w, self.map_h),
                       Qt.AspectRatioMode.KeepAspectRatio)
        transform = self.transform()
        self._zoom = transform.m11()
        self.zoom_changed.emit(self._zoom)
