"""
工具面板 — 暗色主题，7 个图标导航模式 + 子标签页

重构自 13 模式分组列表 → 7 个图标按钮（画地图/省份/地形/河流/国家与区域/后勤/设置）。
复合模式内用水平子标签页切换子页面，stack 仍保留全部 13 个原始 page。
对外发射的 mode_id 不变（land/density/province/height/terrain/river/state/...），
MainWindow / Canvas / Controller 零改动。
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QSlider, QLabel, QButtonGroup,
    QFrame, QStackedWidget, QScrollArea,
    QSizePolicy,
)
from PyQt5.QtCore import Qt, pyqtSignal, QSize

from data.constants import BRUSH_DEFAULT
from ui.i18n import tr

from ui.styles import (
    _BG, _INPUT_BG, _BORDER, _TEXT, _ACCENT, _DIM,
    _SECTION_STYLE, _SUCCESS_BTN_STYLE,
)


# ── 7 个导航模式定义 ─────────────────────────────────────────
# (nav_id, icon, i18n_key, [(sub_mode_id, i18n_key, risk), ...], nav_tooltip)
#
# 风险等级（提示用户哪些操作影响游戏 / 易崩溃）：
#   "🎨" 渲染层（纯视觉，绝对安全）
#   "🟢" 基础数据（必填但低风险）
#   "🟠" 影响游戏机制（需谨慎）
#   "🔴" 崩溃高发区（必须严格按规范）
# 第 5 项是 tooltip 的 i18n key（渲染时 tr() 取翻译）
_NAV_MODES: list[tuple[str, str, str, list[tuple[str, str, str]], str]] = [
    ("map_draw", "🏖", "nav_map_draw", [
        ("land", "tab_land", "🟢"),
        ("density", "tab_density", "🟢"),
    ], "nav_tooltip_map_draw"),
    ("province", "🧩", "nav_province", [
        ("province", "", "🟢"),
    ], "nav_tooltip_province"),
    ("terrain_group", "⛰", "nav_terrain", [
        ("height", "tab_height", "🟠"),
        ("terrain", "tab_terrain", "🎨"),
        ("province_terrain", "tab_province_terrain", "🟢"),
    ], "nav_tooltip_terrain"),
    ("river", "💧", "nav_river", [
        ("river", "", "🔴"),
    ], "nav_tooltip_river"),
    ("region", "🏛", "nav_region", [
        ("state", "tab_state", "🟢"),
        ("country", "tab_country", "🟢"),
        ("continent", "tab_continent", "🟢"),
    ], "nav_tooltip_region"),
    ("logistics_group", "🛤", "nav_logistics", [
        ("strategic_region", "tab_strategic_region", "🟠"),
        ("logistics", "tab_logistics", "🟠"),
    ], "nav_tooltip_logistics"),
    ("preview_group", "👁", "nav_preview", [
        ("preview", "", "🎨"),
    ], "nav_tooltip_preview"),
    ("settings_group", "⚙", "nav_settings", [
        ("colormap", "tab_colormap", "🎨"),
        ("default_map", "tab_default_map", "🟠"),
    ], "nav_tooltip_settings"),
]


# ── 风险标签 → 颜色（用于 sub tab 文字） ─────────────────────
_RISK_COLORS = {
    "🎨": "#7DD3FC",  # 浅蓝 — 渲染层，安全
    "🟢": "#86EFAC",  # 浅绿 — 基础数据，低风险
    "🟠": "#FDBA74",  # 橙色 — 影响游戏，需谨慎
    "🔴": "#FCA5A5",  # 浅红 — 崩溃高发，需严格遵守规范
}


# ── 图标模式导航栏 ───────────────────────────────────────────
_ICON_BTN_STYLE = f"""
    QPushButton {{
        background: transparent;
        border: none;
        border-left: 3px solid transparent;
        color: {_DIM};
        padding: 10px 12px;
        font-size: 13px;
        font-weight: 400;
        text-align: left;
        margin: 0;
    }}
    QPushButton:checked {{
        background: rgba(108, 108, 240, 0.15);
        border-left: 3px solid {_ACCENT};
        color: white;
        font-weight: 600;
    }}
    QPushButton:hover:!checked {{
        background: rgba(108, 108, 240, 0.06);
        color: {_TEXT};
    }}
"""


class _IconModeBar(QWidget):
    """7 个图标导航按钮（紧凑竖列）。"""
    nav_changed = pyqtSignal(str)  # 发射 nav_id

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._buttons: dict[str, QPushButton] = {}
        self._btn_group = QButtonGroup(self)
        self._btn_group.setExclusive(True)

        for nav_id, icon, label_key, _subs, tooltip_key in _NAV_MODES:
            btn = QPushButton(f"  {icon}  {tr(label_key)}")
            btn.setCheckable(True)
            btn.setProperty("nav_id", nav_id)
            btn.setStyleSheet(_ICON_BTN_STYLE)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.setToolTip(tr(tooltip_key))  # 风险等级提示
            self._btn_group.addButton(btn)
            self._buttons[nav_id] = btn
            layout.addWidget(btn)

        self._btn_group.buttonClicked.connect(
            lambda btn: self.nav_changed.emit(btn.property("nav_id"))
        )

        # 默认选中第一个
        first = list(self._buttons.values())[0]
        first.setChecked(True)

    def retranslateUi(self) -> None:
        """语言切换后刷新按钮文字。"""
        for nav_id, icon, label_key, _subs, tooltip_key in _NAV_MODES:
            btn = self._buttons.get(nav_id)
            if btn:
                btn.setText(f"  {icon}  {tr(label_key)}")
                btn.setToolTip(tr(tooltip_key))


# ── 子模式标签栏 ─────────────────────────────────────────────
_TAB_STYLE = f"""
    QPushButton {{
        background: transparent;
        border: none;
        border-bottom: 2px solid transparent;
        color: {_DIM};
        padding: 6px 14px;
        font-size: 12px;
        font-weight: 500;
    }}
    QPushButton:checked {{
        border-bottom: 2px solid {_ACCENT};
        color: white;
        font-weight: 600;
    }}
    QPushButton:hover:!checked {{
        color: {_TEXT};
    }}
"""


class _SubModeTabBar(QWidget):
    """水平子标签栏 — 只在复合模式（子模式 > 1）时显示。"""
    sub_mode_changed = pyqtSignal(str)  # 发射 sub_mode_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(34)
        self.setStyleSheet(f"background: {_INPUT_BG}; border-bottom: 1px solid {_BORDER};")

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(8, 0, 8, 0)
        self._layout.setSpacing(0)

        self._btn_group = QButtonGroup(self)
        self._btn_group.setExclusive(True)
        self._btn_group.buttonClicked.connect(self._on_tab_clicked)
        self._buttons: list[QPushButton] = []

        self.hide()

    def set_tabs(self, tabs: list[tuple[str, str, str]]) -> None:
        """设置子标签列表。tabs=[(mode_id, i18n_key, risk), ...]。
        risk 是风险等级 emoji（🎨/🟢/🟠/🔴），显示在按钮文字前。
        如果只有一个 tab（或 label_key 为空），则隐藏。"""
        # 清除旧按钮
        for btn in self._buttons:
            self._btn_group.removeButton(btn)
            btn.setParent(None)
            btn.deleteLater()
        self._buttons.clear()

        # 清除 stretch items
        while self._layout.count():
            self._layout.takeAt(0)

        # 只有 >1 个子模式且都有 label 时才显示
        visible_tabs = [(mid, lk, risk) for mid, lk, risk in tabs if lk]
        if len(visible_tabs) <= 1:
            self.hide()
            return

        self._layout.addStretch()
        for mode_id, label_key, risk in visible_tabs:
            # 风险标签作为前缀显示
            btn_text = f"{risk} {tr(label_key)}" if risk else tr(label_key)
            btn = QPushButton(btn_text)
            btn.setCheckable(True)
            btn.setProperty("sub_mode_id", mode_id)
            btn.setStyleSheet(_TAB_STYLE)
            self._btn_group.addButton(btn)
            self._buttons.append(btn)
            self._layout.addWidget(btn)
        self._layout.addStretch()

        # 默认选中第一个
        if self._buttons:
            self._buttons[0].setChecked(True)

        self.show()

    def _on_tab_clicked(self, btn: QPushButton) -> None:
        mid = btn.property("sub_mode_id")
        if mid:
            self.sub_mode_changed.emit(mid)

    def select_tab(self, mode_id: str) -> None:
        """外部选中某个子标签。"""
        for btn in self._buttons:
            if btn.property("sub_mode_id") == mode_id:
                btn.setChecked(True)
                break


# ── 主面板 ────────────────────────────────────────────────
class ToolPanel(QWidget):
    """左侧工具面板 — 7 个导航图标 + 子标签页 + 13 个页面 stack"""

    # 信号 (保持与 MainWindow 的连接不变)
    mode_changed = pyqtSignal(str)
    tool_changed = pyqtSignal(str)
    tile_type_changed = pyqtSignal(int)
    brush_size_changed = pyqtSignal(int)
    terrain_index_changed = pyqtSignal(int)
    terrain_brush_mode_changed = pyqtSignal(bool)
    # 属性地形：选了哪种 provincial terrain 类型
    province_terrain_type_changed = pyqtSignal(str)
    # 属性地形：分配模式开关
    province_terrain_assign_mode_changed = pyqtSignal(bool)
    height_value_changed = pyqtSignal(int)
    generate_provinces_requested = pyqtSignal(int)
    validate_requested = pyqtSignal()
    smooth_coast_requested = pyqtSignal()
    clear_new_land_mask_requested = pyqtSignal()

    # 密度模式信号
    density_value_changed = pyqtSignal(float)
    density_brush_size_changed = pyqtSignal(int)
    density_soft_edge_changed = pyqtSignal(int)
    density_clear_requested = pyqtSignal()
    auto_terrain_requested = pyqtSignal()
    detail_terrain_requested = pyqtSignal(int)
    downgrade_mountain_requested = pyqtSignal()
    downgrade_lasso_mode_toggled = pyqtSignal(bool)
    terrain_brush_size_changed = pyqtSignal(int)
    terrain_soft_edge_changed = pyqtSignal(bool)
    auto_height_requested = pyqtSignal()
    realistic_height_requested = pyqtSignal()
    height_from_terrain_requested = pyqtSignal()
    import_heightmap_requested = pyqtSignal()
    height_brush_mode_changed = pyqtSignal(str)
    height_brush_size_changed = pyqtSignal(int)
    height_brush_strength_changed = pyqtSignal(int)
    ridge_mode_toggled = pyqtSignal(bool)
    ridge_peak_changed = pyqtSignal(int)
    ridge_falloff_changed = pyqtSignal(int)
    ridge_preview_requested = pyqtSignal()
    ridge_confirmed = pyqtSignal()
    ridge_cancelled = pyqtSignal()
    refine_lasso_mode_toggled = pyqtSignal(bool)
    refine_whole_map_requested = pyqtSignal()
    export_requested = pyqtSignal()
    preview_refresh_requested = pyqtSignal()
    preview_game_dir_changed = pyqtSignal(str)
    split_mode_toggled = pyqtSignal(bool)
    lasso_province_toggled = pyqtSignal(bool)
    merge_mode_toggled = pyqtSignal(bool)
    regen_mode_toggled = pyqtSignal(bool)
    regen_execute_requested = pyqtSignal()
    find_province_requested = pyqtSignal(int)

    # State / Country 信号
    auto_states_requested = pyqtSignal(int)
    state_selected = pyqtSignal(int)
    state_property_changed = pyqtSignal(int, str, object)
    state_detail_requested = pyqtSignal(int)
    batch_create_state_toggled = pyqtSignal(bool)
    batch_create_state_confirmed = pyqtSignal()
    state_assign_mode_changed = pyqtSignal(bool)
    state_delete_requested = pyqtSignal(int)
    create_country_requested = pyqtSignal()
    quick_create_country_requested = pyqtSignal(str, str, str)
    country_selected = pyqtSignal(str)
    country_delete_requested = pyqtSignal(str)
    country_property_changed = pyqtSignal(str, str, object)
    country_color_change_requested = pyqtSignal(str)

    # 河流信号
    river_type_changed = pyqtSignal(int)
    validate_river_requested = pyqtSignal()

    # 后勤信号
    open_adjacency_dialog_requested = pyqtSignal()
    open_railway_list_requested = pyqtSignal()
    logistics_railway_level_changed = pyqtSignal(int)
    logistics_supply_pick_toggled = pyqtSignal(bool, bool)

    # 大陆分区信号
    continent_pick_toggled = pyqtSignal(bool)
    continent_add_requested = pyqtSignal(str)
    continent_rename_requested = pyqtSignal(int, str)
    continent_remove_requested = pyqtSignal(int)
    assign_by_state_changed = pyqtSignal(bool)

    # 战略区域信号
    strategic_region_auto_requested = pyqtSignal()
    auto_weather_requested = pyqtSignal()
    strategic_region_selected = pyqtSignal(int)
    strategic_region_new_requested = pyqtSignal()
    strategic_region_delete_requested = pyqtSignal()
    strategic_region_name_changed = pyqtSignal(str)
    strategic_region_name_en_changed = pyqtSignal(str)
    strategic_region_weather_changed = pyqtSignal(str)
    strategic_region_naval_changed = pyqtSignal(str)
    strategic_region_pick_toggled = pyqtSignal(bool)
    sr_assign_mode_changed = pyqtSignal(bool)
    create_from_states_toggled = pyqtSignal(bool)
    create_from_states_confirmed = pyqtSignal()

    # 总览贴图信号
    colormap_color_changed = pyqtSignal(str, int, int, int)
    colormap_reset_requested = pyqtSignal()

    # 地图配置信号
    default_map_river_changed = pyqtSignal(int)
    default_map_tree_add_requested = pyqtSignal()
    default_map_tree_del_requested = pyqtSignal()
    default_map_tree_reset_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(300)
        self.setMaximumWidth(520)
        self.setStyleSheet(f"background: {_BG};")

        # nav_id → 子模式列表 (查找表)
        self._nav_subs: dict[str, list[tuple[str, str, str]]] = {}
        # sub_mode_id → nav_id (反向查找)
        self._sub_to_nav: dict[str, str] = {}
        # sub_mode_id → risk emoji (用于显示风险标签)
        self._sub_risks: dict[str, str] = {}
        for nav_id, _icon, _label, subs, _tooltip in _NAV_MODES:
            self._nav_subs[nav_id] = subs
            for sub_id, _sub_label, risk in subs:
                self._sub_to_nav[sub_id] = nav_id
                self._sub_risks[sub_id] = risk

        self._current_nav = ""
        self._init_ui()

    # ── UI 构建 ───────────────────────────────────────────
    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 图标导航栏 (7 个按钮)
        self._icon_bar = _IconModeBar()
        self._icon_bar.nav_changed.connect(self._on_nav_changed)
        root.addWidget(self._icon_bar)

        # 子标签栏 (复合模式时显示)
        self._sub_tabs = _SubModeTabBar()
        self._sub_tabs.sub_mode_changed.connect(self._on_sub_mode_changed)
        root.addWidget(self._sub_tabs)

        # 模式操作提示条
        from ui.mode_hint_bar import ModeHintBar
        self._hint_bar = ModeHintBar()
        root.addWidget(self._hint_bar)

        # 页面内容滚动区域
        self._page_scroll = QScrollArea()
        self._page_scroll.setWidgetResizable(True)
        self._page_scroll.setFrameShape(QFrame.NoFrame)
        self._page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._page_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background: transparent; border: none;")
        self._stack.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._page_scroll.setWidget(self._stack)
        root.addWidget(self._page_scroll, 1)

        # 创建各页面实例并连接信号
        self._create_pages()

        # 初始化第一个导航组的子标签栏（图标栏 setChecked 不触发信号）
        first_nav = _NAV_MODES[0][0]
        self._on_nav_changed(first_nav)

        # 底部固定区域
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color: {_BORDER}; margin: 0;")
        root.addWidget(sep)

        self._export_btn = QPushButton(tr("panel_export_btn"))
        self._export_btn.setStyleSheet(_SUCCESS_BTN_STYLE)
        self._export_btn.clicked.connect(self.export_requested.emit)
        root.addWidget(self._export_btn)

    def _create_pages(self) -> None:
        """实例化各 page 类, 加入 stack, 连接信号转发."""
        from features.map.land.page import LandPage
        from features.map.density.page import DensityPage
        from features.map.province.page import ProvincePage
        from features.map.terrain.page import TerrainPage
        from features.map.province_terrain.page import ProvincialTerrainPage
        from features.map.height.page import HeightPage
        from features.map.river.page import RiverPage
        from features.map.state.page import StatePage
        from features.map.country.page import CountryPage
        from features.map.continent.page import ContinentPage
        from features.map.strategic_region.page import StrategicRegionPage
        from features.map.logistics.page import LogisticsPage
        from features.map.colormap.page import ColormapPage
        from features.map.default_map.page import DefaultMapPage
        from features.map.preview.page import PreviewPage

        # 创建实例
        self._land_page = LandPage()
        self._density_page = DensityPage()
        self._province_page = ProvincePage()
        self._terrain_page = TerrainPage()
        self._province_terrain_page = ProvincialTerrainPage()
        self._height_page = HeightPage()
        self._river_page = RiverPage()
        self._state_page = StatePage()
        self._country_page = CountryPage()
        self._continent_page = ContinentPage()
        self._strategic_region_page = StrategicRegionPage()
        self._logistics_page = LogisticsPage()
        self._colormap_page = ColormapPage()
        self._default_map_page = DefaultMapPage()
        self._preview_page = PreviewPage()

        # 按 mode_id 顺序加入 stack
        page_list = [
            ("land", self._land_page),
            ("density", self._density_page),
            ("province", self._province_page),
            ("height", self._height_page),
            ("terrain", self._terrain_page),
            ("province_terrain", self._province_terrain_page),
            ("river", self._river_page),
            ("state", self._state_page),
            ("country", self._country_page),
            ("continent", self._continent_page),
            ("strategic_region", self._strategic_region_page),
            ("logistics", self._logistics_page),
            ("colormap", self._colormap_page),
            ("default_map", self._default_map_page),
            ("preview", self._preview_page),
        ]
        self._pages: dict[str, QWidget] = {}
        self._mode_index: dict[str, int] = {}
        for i, (mode_id, page) in enumerate(page_list):
            self._stack.addWidget(page)
            self._pages[mode_id] = page
            self._mode_index[mode_id] = i
        self._stack.setCurrentIndex(0)

        # ── 信号转发 ──
        self._connect_land_signals()
        self._connect_density_signals()
        self._connect_province_signals()
        self._connect_terrain_signals()
        self._connect_height_signals()
        self._connect_river_signals()
        self._connect_state_signals()
        self._connect_country_signals()
        self._connect_continent_signals()
        self._connect_strategic_region_signals()
        self._connect_logistics_signals()
        self._connect_colormap_signals()
        self._connect_default_map_signals()
        self._connect_preview_signals()

    def _connect_land_signals(self) -> None:
        p = self._land_page
        p.tool_changed.connect(self.tool_changed)
        p.tile_type_changed.connect(self.tile_type_changed)
        p.brush_size_changed.connect(self.brush_size_changed)
        p.generate_provinces_requested.connect(self.generate_provinces_requested)
        p.validate_requested.connect(self.validate_requested)
        p.smooth_coast_requested.connect(self.smooth_coast_requested)
        p.clear_new_land_mask_requested.connect(self.clear_new_land_mask_requested)

    def _connect_density_signals(self) -> None:
        p = self._density_page
        p.density_value_changed.connect(self.density_value_changed)
        p.density_brush_size_changed.connect(self.density_brush_size_changed)
        p.density_soft_edge_changed.connect(self.density_soft_edge_changed)
        p.density_clear_requested.connect(self.density_clear_requested)

    def _connect_province_signals(self) -> None:
        p = self._province_page
        p.split_mode_toggled.connect(self.split_mode_toggled)
        p.lasso_province_toggled.connect(self.lasso_province_toggled)
        p.merge_mode_toggled.connect(self.merge_mode_toggled)
        p.regen_mode_toggled.connect(self.regen_mode_toggled)
        p.regen_execute_requested.connect(self.regen_execute_requested)
        p.find_province_requested.connect(self.find_province_requested)

    def _connect_terrain_signals(self) -> None:
        p = self._terrain_page
        p.terrain_index_changed.connect(self.terrain_index_changed)
        p.terrain_brush_mode_changed.connect(self.terrain_brush_mode_changed)
        p.terrain_brush_size_changed.connect(self.terrain_brush_size_changed)
        p.terrain_soft_edge_changed.connect(self.terrain_soft_edge_changed)
        p.auto_terrain_requested.connect(self.auto_terrain_requested)
        p.detail_terrain_requested.connect(self.detail_terrain_requested)
        p.downgrade_mountain_requested.connect(self.downgrade_mountain_requested)
        p.downgrade_lasso_mode_toggled.connect(self.downgrade_lasso_mode_toggled)
        # 属性地形 page 信号
        self._province_terrain_page.type_changed.connect(self.province_terrain_type_changed)
        self._province_terrain_page.assign_mode_changed.connect(self.province_terrain_assign_mode_changed)

    def _connect_height_signals(self) -> None:
        p = self._height_page
        p.height_value_changed.connect(self.height_value_changed)
        p.auto_height_requested.connect(self.auto_height_requested)
        p.realistic_height_requested.connect(self.realistic_height_requested)
        p.height_from_terrain_requested.connect(self.height_from_terrain_requested)
        p.import_heightmap_requested.connect(self.import_heightmap_requested)
        p.ridge_mode_toggled.connect(self.ridge_mode_toggled)
        p.ridge_peak_changed.connect(self.ridge_peak_changed)
        p.ridge_falloff_changed.connect(self.ridge_falloff_changed)
        p.ridge_preview_requested.connect(self.ridge_preview_requested)
        p.ridge_confirmed.connect(self.ridge_confirmed)
        p.ridge_cancelled.connect(self.ridge_cancelled)
        p.refine_lasso_mode_toggled.connect(self.refine_lasso_mode_toggled)
        p.refine_whole_map_requested.connect(self.refine_whole_map_requested)
        p.height_brush_mode_changed.connect(self.height_brush_mode_changed)
        p.height_brush_size_changed.connect(self.height_brush_size_changed)
        p.height_brush_strength_changed.connect(self.height_brush_strength_changed)

    def _connect_river_signals(self) -> None:
        p = self._river_page
        p.tool_changed.connect(self.tool_changed)
        p.brush_size_changed.connect(self.brush_size_changed)
        p.river_type_changed.connect(self.river_type_changed)
        p.validate_river_requested.connect(self.validate_river_requested)

    def _connect_state_signals(self) -> None:
        p = self._state_page
        p.auto_states_requested.connect(self.auto_states_requested)
        p.state_selected.connect(self.state_selected)
        p.state_property_changed.connect(self.state_property_changed)
        p.state_detail_requested.connect(self.state_detail_requested)
        p.batch_create_state_toggled.connect(self.batch_create_state_toggled)
        p.batch_create_state_confirmed.connect(self.batch_create_state_confirmed)
        p.assign_mode_changed.connect(self.state_assign_mode_changed)
        p.state_delete_requested.connect(self.state_delete_requested)

    def _connect_country_signals(self) -> None:
        p = self._country_page
        p.create_country_requested.connect(self.create_country_requested)
        p.quick_create_country_requested.connect(self.quick_create_country_requested)
        p.country_selected.connect(self.country_selected)
        p.country_property_changed.connect(self.country_property_changed)
        p.country_color_change_requested.connect(self.country_color_change_requested)
        p.country_delete_requested.connect(self.country_delete_requested)

    def _connect_continent_signals(self) -> None:
        p = self._continent_page
        p.continent_pick_toggled.connect(self.continent_pick_toggled)
        p.continent_add_requested.connect(self.continent_add_requested)
        p.continent_rename_requested.connect(self.continent_rename_requested)
        p.continent_remove_requested.connect(self.continent_remove_requested)
        p.assign_by_state_changed.connect(self.assign_by_state_changed)

    def _connect_strategic_region_signals(self) -> None:
        p = self._strategic_region_page
        p.strategic_region_auto_requested.connect(self.strategic_region_auto_requested)
        p.auto_weather_requested.connect(self.auto_weather_requested)
        p.strategic_region_selected.connect(self.strategic_region_selected)
        p.strategic_region_new_requested.connect(self.strategic_region_new_requested)
        p.strategic_region_delete_requested.connect(self.strategic_region_delete_requested)
        p.strategic_region_name_changed.connect(self.strategic_region_name_changed)
        p.strategic_region_name_en_changed.connect(self.strategic_region_name_en_changed)
        p.strategic_region_weather_changed.connect(self.strategic_region_weather_changed)
        p.strategic_region_naval_changed.connect(self.strategic_region_naval_changed)
        p.strategic_region_pick_toggled.connect(self.strategic_region_pick_toggled)
        p.sr_assign_mode_changed.connect(self.sr_assign_mode_changed)
        p.create_from_states_toggled.connect(self.create_from_states_toggled)
        p.create_from_states_confirmed.connect(self.create_from_states_confirmed)

    def _connect_logistics_signals(self) -> None:
        p = self._logistics_page
        p.open_adjacency_dialog_requested.connect(self.open_adjacency_dialog_requested)
        p.open_railway_list_requested.connect(self.open_railway_list_requested)
        p.logistics_railway_level_changed.connect(self.logistics_railway_level_changed)
        p.logistics_supply_pick_toggled.connect(self.logistics_supply_pick_toggled)

    def _connect_colormap_signals(self) -> None:
        p = self._colormap_page
        p.colormap_color_changed.connect(self.colormap_color_changed)
        p.colormap_reset_requested.connect(self.colormap_reset_requested)

    def _connect_default_map_signals(self) -> None:
        p = self._default_map_page
        p.default_map_river_changed.connect(self.default_map_river_changed)
        p.default_map_tree_add_requested.connect(self.default_map_tree_add_requested)
        p.default_map_tree_del_requested.connect(self.default_map_tree_del_requested)
        p.default_map_tree_reset_requested.connect(self.default_map_tree_reset_requested)

    def _connect_preview_signals(self) -> None:
        p = self._preview_page
        p.refresh_requested.connect(self.preview_refresh_requested)
        p.game_dir_changed.connect(self.preview_game_dir_changed)

    # ── 属性 (保持与 MainWindow 的兼容) ──────────────────────
    @property
    def ref_opacity_slider(self) -> QSlider:
        return self._land_page._ref_opacity_slider

    @property
    def mode_tabs(self) -> _IconModeBar:
        return self._icon_bar

    # 参考图控件 — 暴露给 MainWindow 直连画布
    @property
    def _vanilla_ref_opacity_slider(self) -> QSlider:
        return self._land_page._vanilla_ref_opacity_slider

    @property
    def _vanilla_ref_toggle(self) -> QPushButton:
        return self._land_page._vanilla_ref_toggle

    @property
    def _ref_scale_slider(self) -> QSlider:
        return self._land_page._ref_scale_slider

    @property
    def _ref_fit_btn(self) -> QPushButton:
        return self._land_page._ref_fit_btn

    @property
    def _ref_toggle(self) -> QPushButton:
        return self._land_page._ref_toggle

    # 快速创建颜色 — 外部读取
    @property
    def _quick_create_color(self) -> tuple:
        return self._country_page._quick_create_color

    # 后勤状态标签 — 外部直接更新
    @property
    def _logi_adj_status(self) -> QLabel:
        return self._logistics_page._logi_adj_status

    @property
    def _logi_rail_status(self) -> QLabel:
        return self._logistics_page._logi_rail_status

    @property
    def _logi_sup_status(self) -> QLabel:
        return self._logistics_page._logi_sup_status

    @property
    def _logi_rail_draw_btn(self) -> QPushButton:
        return self._logistics_page._logi_rail_draw_btn

    @property
    def _logi_sup_toggle_btn(self) -> QPushButton:
        return self._logistics_page._logi_sup_toggle_btn

    @property
    def _logi_rail_level(self):
        return self._logistics_page._logi_rail_level

    # 大陆列表/拾取/状态 — 外部直接访问
    @property
    def _continent_list(self):
        return self._continent_page._continent_list

    @property
    def _continent_pick_btn(self):
        return self._continent_page._continent_pick_btn

    @property
    def _continent_status(self):
        return self._continent_page._continent_status

    # 战略区域 — 外部直接访问
    @property
    def _sr_list(self):
        return self._strategic_region_page._sr_list

    @property
    def _sr_name_edit(self):
        return self._strategic_region_page._sr_name_edit

    @property
    def _sr_name_en_edit(self):
        return self._strategic_region_page._sr_name_en_edit

    @property
    def _sr_weather_combo(self):
        return self._strategic_region_page._sr_weather_combo

    @property
    def _sr_naval_combo(self):
        return self._strategic_region_page._sr_naval_combo

    @property
    def _sr_prov_count(self):
        return self._strategic_region_page._sr_prov_count

    @property
    def _sr_pick_btn(self):
        return self._strategic_region_page._sr_pick_btn

    # Colormap swatches — 外部通过旧名访问
    @property
    def _colormap_land_swatch(self):
        return self._colormap_page._swatches["land"]

    @property
    def _colormap_sea_swatch(self):
        return self._colormap_page._swatches["sea"]

    @property
    def _colormap_lake_swatch(self):
        return self._colormap_page._swatches["lake"]

    # Default map — 外部直接访问
    @property
    def _dm_river_max(self):
        return self._default_map_page._dm_river_max

    @property
    def _dm_tree_list(self):
        return self._default_map_page._dm_tree_list

    # Province 合并/扩张按钮 — 外部访问
    @property
    def _merge_btn(self):
        return self._province_page._merge_btn

    @property
    def _expand_btn(self):
        return self._province_page._expand_btn

    @property
    def _province_hint(self):
        return self._province_page._province_hint

    # ── 语言切换 ──────────────────────────────────────────
    def retranslateUi(self) -> None:
        """语言切换后刷新导航栏/子标签/导出按钮文字。"""
        self._icon_bar.retranslateUi()
        # 刷新当前子标签栏
        subs = self._nav_subs.get(self._current_nav, [])
        self._sub_tabs.set_tabs(subs)
        # 导出按钮
        self._export_btn.setText(tr("panel_export_btn"))
        # 模式提示条
        self._hint_bar.on_mode_changed(
            list(self._pages.keys())[self._stack.currentIndex()]
            if self._stack.currentIndex() < len(self._pages)
            else "land"
        )

    # ── 槽函数 ────────────────────────────────────────────
    def _on_nav_changed(self, nav_id: str) -> None:
        """图标导航点击 → 更新子标签栏 + 切到默认子模式。"""
        self._current_nav = nav_id
        subs = self._nav_subs.get(nav_id, [])
        self._sub_tabs.set_tabs(subs)

        # 切到该 nav 的第一个子模式
        if subs:
            first_sub = subs[0][0]
            self._switch_to_mode(first_sub)

    def _on_sub_mode_changed(self, mode: str) -> None:
        """子标签切换 → 切页面 + 发射信号。"""
        self._switch_to_mode(mode)

    def _switch_to_mode(self, mode: str) -> None:
        """切换到指定 mode_id，更新 stack、hint、信号。"""
        # 确保子标签栏显示（初始化时 _on_nav_changed 可能没被调用）
        nav_id = self._sub_to_nav.get(mode, "")
        if nav_id and nav_id != self._current_nav:
            self._current_nav = nav_id
            subs = self._nav_subs.get(nav_id, [])
            self._sub_tabs.set_tabs(subs)
            self._sub_tabs.select_tab(mode)

        idx = self._mode_index.get(mode, 0)
        self._stack.setCurrentIndex(idx)
        # 切换模式时自动设工具（用户在工具栏单独切 new_land 工具，不靠 mode）
        if mode not in ("province", "state", "country"):
            self.tool_changed.emit("brush")
        # 触发模式提示条
        self._hint_bar.on_mode_changed(mode)
        self.mode_changed.emit(mode)

    # ── 公共方法 (转发到对应 page) ────────────────────────
    def update_province_info(
        self, pid: int, ptype: str, terrain: str, pixels: int, coastal: bool
    ) -> None:
        """更新省份信息面板"""
        self._province_page.update_province_info(pid, ptype, terrain, pixels, coastal)

    def update_state_list(self, states: list[tuple[int, str, int]]) -> None:
        """刷新 State 列表"""
        self._state_page.update_state_list(states)

    def update_state_info(self, name: str, manpower: int, category: str) -> None:
        """填充 State 属性字段"""
        self._state_page.update_state_info(name, manpower, category)

    def select_state_in_list(self, state_id: int) -> None:
        """在 State 列表中选中指定 ID 的行。"""
        from PyQt5.QtCore import Qt
        lst = self._state_page._state_list
        for i in range(lst.count()):
            item = lst.item(i)
            if item and int(item.data(Qt.UserRole) or 0) == state_id:
                lst.blockSignals(True)
                lst.setCurrentRow(i)
                lst.blockSignals(False)
                self._state_page._current_state_id = state_id
                break

    def update_country_list(self, countries: list[tuple[str, str, tuple]]) -> None:
        """刷新国家列表"""
        self._country_page.update_country_list(countries)

    def update_country_info(
        self, tag: str, name: str, party: str, color: tuple, capital_name: str
    ) -> None:
        """填充国家属性字段"""
        self._country_page.update_country_info(tag, name, party, color, capital_name)

    def update_province_gaps(self, gap_ids: list[int]) -> None:
        """更新省份 ID 空洞提示"""
        self._province_page.update_province_gaps(gap_ids)
