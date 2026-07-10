"""
主窗口 — 薄壳，只做 UI 组装和信号路由。
所有业务逻辑委托给 ApplicationController。

文件操作/对话框拆分在:
  - views/main_window_actions.py (省份生成/验证/国家/河流/地形/大陆/战略区/后勤)
  - views/main_window_file_ops.py (新建/打开/保存/导入/导出)
"""
from __future__ import annotations

from PyQt5.QtWidgets import (
    QMainWindow, QAction, QFileDialog, QMessageBox, QWidget,
    QLabel, QApplication, QStackedWidget, QHBoxLayout,
    QWidgetAction, QSlider,
)
from PyQt5.QtCore import Qt, QTimer, QPoint
from PyQt5.QtGui import QKeySequence

from model.project import Project
from model.events import EventBus
from commands.history import CommandHistory
from controllers.app_controller import ApplicationController

from controllers.land import LandController
from controllers.province import ProvinceController
from controllers.terrain import TerrainController
from controllers.provincial_terrain import ProvincialTerrainController
from controllers.height import HeightController
from controllers.river import RiverController
from controllers.state import StateController
from controllers.country import CountryController
from controllers.continent import ContinentController
from controllers.logistics import LogisticsController
from controllers.strategic_region import StrategicRegionController
from controllers.colormap import ColormapController
from controllers.default_map import DefaultMapController

from views.canvas.widget import MapCanvas
from views.main_window_actions import MainWindowActionsMixin
from views.welcome_page import WelcomePage, save_recent_project
from views.context_menu import ProvinceContextMenu
from views.shortcuts import ShortcutManager, show_shortcut_dialog
from ui.tool_panel import ToolPanel
from ui.i18n import tr
from data.constants import DEFAULT_PROVINCES


class MainWindow(MainWindowActionsMixin, QMainWindow):
    """主窗口 — 纯 UI 壳，逻辑在 ApplicationController。"""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(tr("app_title"))
        self.setMinimumSize(1200, 700)

        # ── 核心对象 ──
        self._event_bus = EventBus()
        self._project = Project(event_bus=self._event_bus)
        self._cmd_history = CommandHistory(event_bus=self._event_bus)

        # 选区模式标志
        self._batch_state_mode = False
        self._batch_state_pids: list[int] = []
        self._sr_from_states_mode = False
        self._sr_selected_states: list[int] = []

        # 旧版 undo manager（画布 stroke 仍在用，阶段 4 统一后删除）
        from domain.undo_manager import UndoManager
        self._undo_mgr = UndoManager(max_steps=30)

        # ── 12 个 Controller ──
        self._controllers: dict[str, object] = {
            "land": LandController(self._project, self._cmd_history),
            "province": ProvinceController(self._project, self._cmd_history),
            "terrain": TerrainController(self._project, self._cmd_history),
            "province_terrain": ProvincialTerrainController(self._project, self._cmd_history),
            "height": HeightController(self._project, self._cmd_history),
            "river": RiverController(self._project, self._cmd_history),
            "state": StateController(self._project, self._cmd_history),
            "country": CountryController(self._project, self._cmd_history),
            "continent": ContinentController(self._project, self._cmd_history),
            "logistics": LogisticsController(self._project, self._cmd_history),
            "strategic_region": StrategicRegionController(self._project, self._cmd_history),
            "colormap": ColormapController(self._project, self._cmd_history),
            "default_map": DefaultMapController(self._project, self._cmd_history),
        }

        # ── 快捷键管理器 ──
        self._shortcut_mgr = ShortcutManager()

        # ── UI 组装 ──
        self._init_ui()
        self._init_menu()
        self._init_statusbar()

        # ── ApplicationController（在 UI 组装后创建）──
        self._app = ApplicationController(
            self._project, self._canvas, self._tool_panel,
            self._cmd_history, self._controllers, self._undo_mgr,
        )

        self._connect_signals()
        self._subscribe_events()
        self._init_shortcuts()

        # ── 右键上下文菜单 ──
        self._context_menu = ProvinceContextMenu(
            self._project, self._controllers, self._canvas,
            open_state_detail=self._on_state_detail_requested,
        )

        # 启动时显示欢迎页
        self._show_welcome()

        # 后台检查更新
        QTimer.singleShot(2000, self._check_for_update)

        # 让 canvas 和 project 共享同一个 MapData 实例
        self._canvas.set_map_data(self._project.map_data)
        # 挂管理器到 canvas，让后勤 overlay 能读到数据
        self._canvas._supply_mgr = self._project.supply_mgr
        self._canvas._railway_mgr = self._project.railway_mgr

        # 初始模式
        self._on_mode_changed("land")

        QTimer.singleShot(100, self._canvas.fit_in_view)

    # ═══════════════════════ UI 初始化 ═══════════════════════

    def _init_ui(self) -> None:
        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        # 欢迎页
        self._welcome_page = WelcomePage()
        self._welcome_page.new_project_requested.connect(self._on_welcome_new)
        self._welcome_page.open_project_requested.connect(self._on_open_project)
        self._welcome_page.open_recent_requested.connect(self._on_welcome_open_recent)
        self._welcome_page.import_mod_requested.connect(self._on_welcome_import_mod)
        self._welcome_page.open_vanilla_requested.connect(self._on_open_vanilla_reference)
        self._welcome_page.language_changed.connect(self._on_language_changed)
        self._stack.addWidget(self._welcome_page)

        # 编辑器布局：左侧固定宽度工具面板 + 右侧画布
        self._editor = QWidget()
        editor = self._editor
        editor_layout = QHBoxLayout(editor)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(0)

        self._tool_panel = ToolPanel()
        # 软约束: 最小 380px (中/英 设计宽度), 上限 480px 防俄语等长语言把侧栏吃满
        self._tool_panel.setMinimumWidth(380)
        self._tool_panel.setMaximumWidth(480)
        editor_layout.addWidget(self._tool_panel)

        self._canvas = MapCanvas()
        editor_layout.addWidget(self._canvas, 1)

        self._stack.addWidget(editor)

    def _init_menu(self) -> None:
        menubar = self.menuBar()

        # 文件
        file_menu = menubar.addMenu(tr("menu_file"))
        self._add_action(file_menu, tr("action_new"), self._on_new_project, QKeySequence.StandardKey.New)
        self._add_action(file_menu, tr("action_open"), self._on_open_project, "Ctrl+O")
        self._add_action(file_menu, tr("action_save"), self._on_save_project, "Ctrl+S")
        self._add_action(file_menu, tr("action_save_as"), self._on_save_project_as, "Ctrl+Shift+S")
        file_menu.addSeparator()
        self._add_action(file_menu, tr("action_import_image"), self._on_import_image, "Ctrl+I")
        self._add_action(file_menu, tr("action_load_vanilla_ref"), self._on_load_vanilla_ref)
        self._add_action(file_menu, tr("action_import_landmask"), self._on_import_landmask, "Ctrl+Shift+I")
        self._add_action(file_menu, tr("action_import_mod_map"), self._on_import_mod_map, "Ctrl+Shift+M")
        self._add_action(file_menu, tr("action_open_vanilla"), self._on_open_vanilla_reference)
        self._add_action(file_menu, tr("action_export_mod"), self._on_export_mod, "Ctrl+E")
        self._add_action(file_menu, tr("action_test_export"), self._on_test_export, "Ctrl+T")
        file_menu.addSeparator()
        self._add_action(file_menu, tr("action_exit"), self.close, QKeySequence.StandardKey.Quit)

        # 编辑
        edit_menu = menubar.addMenu(tr("menu_edit"))
        self._undo_action = self._add_action(edit_menu, tr("action_undo"), self._on_undo, "Ctrl+Z")
        self._redo_action = self._add_action(edit_menu, tr("action_redo"), self._on_redo, "Ctrl+Y")
        self._undo_action.setEnabled(False)
        self._redo_action.setEnabled(False)

        # 视图
        view_menu = menubar.addMenu(tr("menu_view"))
        self._add_action(view_menu, tr("action_zoom_fit"), self._canvas.fit_in_view, "Ctrl+0")
        act_ref = QAction(tr("action_show_ref"), self)
        act_ref.setCheckable(True)
        act_ref.setChecked(True)
        act_ref.triggered.connect(self._canvas.toggle_ref_image)
        view_menu.addAction(act_ref)
        # 国家/州 归属叠加层 —— 全局开关，任意模式下都能看
        act_cs = QAction(tr("action_show_country_state_overlay"), self)
        act_cs.setCheckable(True)
        act_cs.setChecked(False)
        act_cs.setToolTip(tr("action_show_country_state_overlay_tip"))
        act_cs.triggered.connect(self._on_terrain_context_overlay)
        view_menu.addAction(act_cs)
        self._act_country_state_overlay = act_cs
        # 地形底图（国家/州模式下做底，保留画边界时的地形参考）
        act_tu = QAction(tr("action_show_terrain_underlay"), self)
        act_tu.setCheckable(True)
        act_tu.setChecked(False)
        act_tu.setToolTip(tr("action_show_terrain_underlay_tip"))
        act_tu.triggered.connect(self._on_terrain_underlay_toggle)
        view_menu.addAction(act_tu)
        self._act_terrain_underlay = act_tu
        # 透明度滑块（嵌入菜单）
        opacity_widget = QWidget()
        opacity_layout = QHBoxLayout(opacity_widget)
        opacity_layout.setContentsMargins(24, 2, 12, 2)
        opacity_layout.addWidget(QLabel(tr("action_terrain_underlay_opacity")))
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(10, 100)
        slider.setValue(40)
        slider.setFixedWidth(140)
        slider.valueChanged.connect(self._on_terrain_underlay_opacity)
        opacity_layout.addWidget(slider)
        act_opacity = QWidgetAction(self)
        act_opacity.setDefaultWidget(opacity_widget)
        view_menu.addAction(act_opacity)
        self._terrain_underlay_slider = slider

        # 地形底图源切换 (互斥: 高度图 / 地形图)
        from PyQt5.QtWidgets import QActionGroup
        underlay_group = QActionGroup(self)
        underlay_group.setExclusive(True)
        act_src_height = QAction(tr("action_terrain_underlay_src_height"), self)
        act_src_height.setCheckable(True)
        act_src_height.setChecked(True)
        act_src_height.triggered.connect(lambda: self._on_terrain_underlay_source("height"))
        view_menu.addAction(act_src_height)
        underlay_group.addAction(act_src_height)

        act_src_terrain = QAction(tr("action_terrain_underlay_src_terrain"), self)
        act_src_terrain.setCheckable(True)
        act_src_terrain.triggered.connect(lambda: self._on_terrain_underlay_source("terrain"))
        view_menu.addAction(act_src_terrain)
        underlay_group.addAction(act_src_terrain)

        # 工具
        tools_menu = menubar.addMenu(tr("menu_tools"))
        self._add_action(tools_menu, tr("action_generate_provinces"),
                         lambda: self._on_generate_provinces(DEFAULT_PROVINCES), "Ctrl+G")
        self._add_action(tools_menu, tr("action_validate"), self._on_validate, "Ctrl+Shift+V")
        tools_menu.addSeparator()
        self._add_action(tools_menu, tr("action_quick_init"), self._on_quick_init)

        # 设置
        settings_menu = menubar.addMenu(tr("menu_settings"))
        self._add_action(settings_menu, tr("action_language"), self._on_toggle_language)
        self._add_action(settings_menu, tr("action_shortcut_settings"), self._on_shortcut_settings)

        # 帮助
        help_menu = menubar.addMenu(tr("menu_help"))
        self._add_action(help_menu, tr("action_guide"), self._show_guide_force)
        self._add_action(help_menu, tr("action_reset_hints"), self._reset_mode_hints)
        help_menu.addSeparator()
        self._add_action(help_menu, tr("action_about"), self._on_about)

    def _add_action(self, menu, text, slot, shortcut=None):
        act = QAction(text, self)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut) if isinstance(shortcut, str) else shortcut)
        act.triggered.connect(slot)
        menu.addAction(act)
        return act

    def _init_statusbar(self) -> None:
        self._status_pos = QLabel(tr("status_pos", 0, 0))
        self._status_zoom = QLabel(tr("status_zoom", 1.0))
        self._status_provinces = QLabel(tr("status_provinces", 0))
        self._status_mode = QLabel(tr("status_mode").format(mode=tr("mode_continent")))
        self._status_info = QLabel(tr("status_ready"))

        sb = self.statusBar()
        sb.addWidget(self._status_info, stretch=1)
        sb.addPermanentWidget(self._status_mode)
        sb.addPermanentWidget(self._status_provinces)
        sb.addPermanentWidget(self._status_pos)
        sb.addPermanentWidget(self._status_zoom)

    # ═══════════════════════ 信号连接 ═══════════════════════

    def _connect_signals(self) -> None:
        tp = self._tool_panel
        cv = self._canvas

        # 模式切换
        tp.mode_changed.connect(self._on_mode_changed)

        # 预览
        tp.preview_refresh_requested.connect(self._on_preview_refresh)
        tp.preview_game_dir_changed.connect(self._on_preview_game_dir_changed)
        tp.preview_political_toggled.connect(self._on_preview_political_toggled)
        tp.preview_night_toggled.connect(self._on_preview_night_toggled)

        # 工具/画笔 → 画布 (直通)
        tp.tool_changed.connect(cv.set_tool)
        tp.tile_type_changed.connect(cv.set_tile_type)
        tp.brush_size_changed.connect(cv.set_brush_size)
        tp.terrain_index_changed.connect(cv.set_terrain_index)
        # 按省份生成走 controller.on_province_clicked，必须同步 current_terrain_index
        tp.terrain_index_changed.connect(
            lambda idx: setattr(self._controllers["terrain"], "current_terrain_index", idx)
        )
        tp.terrain_brush_mode_changed.connect(cv.set_terrain_brush_mode)
        tp.terrain_brush_mode_changed.connect(
            lambda on: setattr(self._controllers["terrain"], "brush_mode", on)
        )
        tp.height_value_changed.connect(cv.set_height_value)
        # 属性地形选择 → 属性地形 controller
        tp.province_terrain_type_changed.connect(
            self._controllers["province_terrain"].set_type
        )
        tp.province_terrain_assign_mode_changed.connect(
            self._controllers["province_terrain"].set_assign_mode
        )

        # 参考图控件 → 画布
        tp._vanilla_ref_opacity_slider.valueChanged.connect(
            lambda v: cv.set_vanilla_ref_opacity(v / 100.0)
        )
        tp._vanilla_ref_toggle.toggled.connect(
            lambda on: cv.toggle_vanilla_ref(not on)
        )
        tp.ref_opacity_slider.valueChanged.connect(
            lambda v: cv.set_ref_opacity(v / 100.0)
        )
        tp._ref_scale_slider.valueChanged.connect(
            lambda v: cv.set_ref_scale(v / 100.0)
        )
        tp._ref_toggle.toggled.connect(
            lambda on: cv.toggle_ref_image(not on)
        )
        # 原版参考: 缩放（与自定义图对称）
        tp._vanilla_ref_scale_slider.valueChanged.connect(
            lambda v: cv.set_ref_layer_scale("vanilla", v / 100.0)
        )
        # 打开原版参考（复用文件菜单动作）
        tp.open_vanilla_requested.connect(self._on_load_vanilla_ref)
        # 调整参考图模式
        def _on_ref_adjust_toggled(on: bool) -> None:
            cv.set_ref_adjust_mode(tp.current_adjust_target() if on else None)
            if on:
                cv.setFocus()   # 焦点给画布, 让 ESC 直接可用（刚点完按钮时焦点在按钮上）
        tp.ref_adjust_toggled.connect(_on_ref_adjust_toggled)
        tp.ref_adjust_target_changed.connect(cv.set_ref_adjust_mode)
        cv.ref_adjust_exited.connect(lambda: tp.set_ref_adjust_checked(False))
        cv.ref_adjust_scale_changed.connect(
            lambda t, s: tp.set_ref_scale_percent(t, int(round(s * 100)))
        )
        # 已生成省份后画陆海 → 弹确认框（直连信号, 画布同步读结果）
        cv.land_paint_confirm_requested.connect(self._on_land_paint_confirm)

        # 操作按钮 → 本窗口处理（含 UI 交互）
        tp.generate_provinces_requested.connect(self._on_generate_provinces)
        tp.validate_requested.connect(self._on_validate)
        tp.smooth_coast_requested.connect(self._on_smooth_coast)
        # ① 参考底图卡片里的导入按钮 → 复用文件菜单的导入参考图动作
        tp.import_ref_requested.connect(self._on_import_image)
        tp.clear_new_land_mask_requested.connect(self._on_clear_new_land_mask)
        # 新大陆信号
        # 密度模式信号
        tp.density_value_changed.connect(
            lambda v: setattr(self._canvas, '_density_paint_value', v))
        tp.density_brush_size_changed.connect(cv.set_density_brush_size)
        tp.density_soft_edge_changed.connect(
            lambda s: setattr(self._canvas, '_density_soft_edge', s / 100.0))
        tp.density_clear_requested.connect(self._on_density_clear)
        tp.auto_terrain_requested.connect(self._on_auto_terrain)
        tp.detail_terrain_requested.connect(self._on_detail_terrain)
        tp.beautify_terrain_requested.connect(self._on_beautify_terrain)
        tp.downgrade_mountain_requested.connect(self._on_downgrade_mountain)
        tp.downgrade_lasso_mode_toggled.connect(self._on_downgrade_lasso_mode)
        cv.downgrade_lasso_drawn.connect(self._on_downgrade_lasso_drawn)
        tp.terrain_brush_size_changed.connect(cv.set_terrain_brush_size)
        tp.terrain_brush_size_changed.connect(
            lambda s: setattr(self._controllers["terrain"], "brush_size", s)
        )
        tp.terrain_soft_edge_changed.connect(
            lambda s: setattr(self._controllers["terrain"], "soft_edge", s)
        )
        tp.auto_height_requested.connect(self._on_auto_height)
        tp.realistic_height_requested.connect(self._on_realistic_height)
        tp.height_from_terrain_requested.connect(self._on_height_from_terrain)
        tp.height_brush_mode_changed.connect(cv.set_height_brush_mode)
        tp.height_brush_size_changed.connect(cv.set_height_brush_size)
        tp.height_brush_strength_changed.connect(cv.set_height_brush_strength)
        tp.ridge_mode_toggled.connect(self._on_ridge_mode)
        tp.ridge_peak_changed.connect(
            lambda v: setattr(self, '_ridge_peak', v))
        tp.ridge_falloff_changed.connect(
            lambda v: setattr(self, '_ridge_falloff', v))
        cv.ridge_drawn.connect(self._on_ridge_drawn)
        tp.ridge_preview_requested.connect(self._on_ridge_preview)
        tp.ridge_confirmed.connect(self._on_ridge_confirm)
        tp.ridge_cancelled.connect(self._on_ridge_cancel)
        # 保形精修（整图, 生成菜单第③项）
        tp.refine_whole_map_requested.connect(self._on_refine_whole_map)
        cv.province_gaps_detected.connect(
            lambda gaps: self._tool_panel.update_province_gaps(gaps)
        )
        tp.export_requested.connect(self._on_export_mod)

        # Province 信号 → controller
        tp.split_mode_toggled.connect(self._on_split_toggled)
        tp.lasso_province_toggled.connect(self._on_lasso_toggled)
        tp.merge_mode_toggled.connect(self._on_merge_toggled)
        tp.find_province_requested.connect(self._on_find_province)
        cv.split_line_drawn.connect(self._on_split_line_drawn)

        # State 信号 → controller
        tp.auto_states_requested.connect(self._on_auto_states_with_confirm)
        tp.state_selected.connect(
            lambda sid: self._controllers["state"].select_state(sid)
        )
        tp.state_property_changed.connect(
            lambda sid, prop, val: self._controllers["state"].change_property(sid, prop, val)
        )
        tp.state_detail_requested.connect(self._on_state_detail_requested)
        tp.batch_create_state_toggled.connect(self._on_batch_state_toggled)
        tp.batch_create_state_confirmed.connect(self._on_batch_state_confirmed)
        tp.state_assign_mode_changed.connect(
            lambda on: setattr(self._controllers["state"], "assign_mode", on)
        )
        tp.state_delete_requested.connect(
            lambda sid: self._controllers["state"].delete_state(sid)
        )
        tp.state_show_names_toggled.connect(
            lambda on: cv.set_name_labels_enabled("state", on)
        )
        tp.state_resplit_requested.connect(self._on_resplit_state)

        # Country 信号 → controller
        tp.create_country_requested.connect(self._on_create_country)
        tp.quick_create_country_requested.connect(self._on_quick_create_country)
        tp.country_selected.connect(
            lambda tag: self._controllers["country"].select_country(tag)
        )
        # 选中国家时, 在 canvas 上高亮该国所有领土像素
        tp.country_selected.connect(self._on_country_highlight)
        tp.country_property_changed.connect(self._on_country_property_change)
        tp.country_color_change_requested.connect(self._on_country_color_change)
        tp.country_delete_requested.connect(
            lambda tag: self._controllers["country"].delete_country(tag)
        )
        tp.country_show_names_toggled.connect(
            lambda on: cv.set_name_labels_enabled("country", on)
        )
        tp.country_assign_mode_toggled.connect(
            lambda on: self._controllers["country"].set_assign_mode(on)
        )

        # River 信号
        tp.river_type_changed.connect(cv.set_river_type)
        tp.validate_river_requested.connect(self._on_validate_river)

        # Logistics 信号 → controller
        tp.open_adjacency_dialog_requested.connect(self._open_adjacency_dialog)
        tp.open_railway_list_requested.connect(self._open_railway_dialog)
        tp.logistics_railway_level_changed.connect(
            lambda lv: self._controllers["logistics"].set_railway_level(lv)
        )
        tp.logistics_supply_pick_toggled.connect(
            lambda on, erase: self._controllers["logistics"].toggle_supply_pick(on, erase)
        )

        # Continent 信号 → controller
        tp.continent_pick_toggled.connect(self._on_continent_pick_toggled)
        tp.assign_by_state_changed.connect(
            lambda on: setattr(self._controllers["continent"], "assign_by_state", on)
        )
        tp.continent_add_requested.connect(
            lambda name: self._on_continent_add(name)
        )
        tp.continent_rename_requested.connect(
            lambda idx, name: self._on_continent_rename(idx, name)
        )
        tp.continent_remove_requested.connect(
            lambda idx: self._on_continent_remove(idx)
        )

        # Strategic region 信号 → controller
        tp.strategic_region_auto_requested.connect(self._on_auto_sr_with_confirm)
        tp.auto_weather_requested.connect(
            lambda: (self._controllers["strategic_region"].auto_assign_weather(), self._refresh_sr_list())
        )
        tp.strategic_region_pick_toggled.connect(self._on_sr_pick_toggled)
        tp.sr_assign_mode_changed.connect(
            lambda on: self._controllers["strategic_region"].set_assign_mode(on)
        )
        tp.strategic_region_new_requested.connect(self._on_sr_new)
        tp.strategic_region_delete_requested.connect(self._on_sr_delete)
        tp.strategic_region_name_changed.connect(self._on_sr_name_changed)
        tp.strategic_region_name_en_changed.connect(self._on_sr_name_en_changed)
        tp.strategic_region_weather_changed.connect(self._on_sr_weather_changed)
        tp.strategic_region_naval_changed.connect(self._on_sr_naval_changed)
        tp.strategic_region_selected.connect(self._on_sr_selected)
        tp.create_from_states_toggled.connect(self._on_sr_from_states_toggled)
        tp.create_from_states_confirmed.connect(self._on_sr_from_states_confirmed)

        # Colormap 信号 → controller
        tp.colormap_color_changed.connect(
            lambda attr, r, g, b: self._controllers["colormap"].change_color(attr, r, g, b)
        )
        tp.colormap_reset_requested.connect(
            lambda: self._controllers["colormap"].reset()
        )

        # Default map 信号 → controller
        tp.default_map_river_changed.connect(
            lambda lv: self._controllers["default_map"].set_river_level(lv)
        )
        tp.default_map_tree_add_requested.connect(self._on_dm_tree_add)
        tp.default_map_tree_del_requested.connect(self._on_dm_tree_del)
        tp.default_map_tree_reset_requested.connect(self._on_dm_tree_reset)

        # 画布信号
        cv.province_clicked.connect(self._on_province_clicked)
        cv.province_double_clicked.connect(self._on_province_double_clicked)
        cv.province_right_clicked.connect(self._on_province_right_clicked)
        cv.province_right_clicked_at.connect(self._on_province_right_clicked_at)
        cv.provinces_cleared.connect(self._on_provinces_cleared)
        cv.stroke_started.connect(self._app.on_stroke_started)
        cv.stroke_ended.connect(self._app.on_stroke_ended)
        cv.mouse_moved.connect(
            lambda x, y: self._status_pos.setText(tr("status_pos", x, y))
        )
        cv.zoom_changed.connect(
            lambda z: self._status_zoom.setText(tr("status_zoom", z))
        )

    # ═══════════════════════ EventBus 订阅 ═══════════════════

    def _subscribe_events(self) -> None:
        bus = self._event_bus
        # 只订阅纯 UI 更新事件，业务事件由 AppController 处理
        bus.subscribe("status_message", self._on_evt_status)
        bus.subscribe("undo_state_changed", self._on_evt_undo_state)
        bus.subscribe("province_count_changed", self._on_evt_province_count)
        bus.subscribe("vp_dialog_requested", self._on_evt_vp_dialog)
        bus.subscribe("logistics_province_picked", self._on_evt_logistics_picked)
        bus.subscribe("sr_select_in_list", self._on_evt_sr_select_in_list)

    def _on_evt_status(self, event) -> None:
        self._status_info.setText(event.data.get("text", ""))

    def _on_evt_undo_state(self, event) -> None:
        self._undo_action.setEnabled(event.data.get("can_undo", False))
        self._redo_action.setEnabled(event.data.get("can_redo", False))

    def _on_evt_sr_select_in_list(self, event) -> None:
        """点击省份查到所属战略区 → 在侧边栏列表中选中它。"""
        rid = event.data.get("rid", 0)
        if rid <= 0:
            return
        from PyQt5.QtCore import Qt
        lst = self._tool_panel._sr_list
        for i in range(lst.count()):
            item = lst.item(i)
            if item and int(item.data(Qt.UserRole) or 0) == rid:
                lst.setCurrentRow(i)
                break

    def _on_evt_province_count(self, event) -> None:
        count = event.data.get("count", 0)
        self._status_provinces.setText(tr("status_provinces", count))

    def _on_evt_vp_dialog(self, event) -> None:
        """StateController 请求弹 VP 对话框。"""
        pid = event.data.get("pid", 0)
        if pid <= 0:
            return

        # 读取当前值
        state_mgr = self._project.state_mgr
        sid = state_mgr.get_state_of_province(pid)
        state = state_mgr.get_state(sid) if sid > 0 else None
        cur_vp = state.victory_points.get(pid, 0) if state else 0
        cur_name = state.vp_names.get(pid, "") if state else ""

        from views.vp_dialog import ask_vp
        value, name, ok = ask_vp(self, pid, cur_vp, cur_name)
        if ok:
            ctrl: StateController = self._controllers["state"]
            ctrl.set_vp(pid, value, name)

    def _on_evt_logistics_picked(self, event) -> None:
        pid = event.data.get("pid", 0)
        target = event.data.get("target", "")
        if target in ("adj_from", "adj_to", "adj_through"):
            if self._adjacency_dialog is not None:
                self._adjacency_dialog.receive_picked_province(pid)
        elif target in ("rule_required", "rule_icon"):
            if self._adjacency_rule_dialog is not None:
                self._adjacency_rule_dialog.receive_picked_province(pid)

    # ═══════════════════════ 模式切换 ═══════════════════════

    def _on_mode_changed(self, mode: str) -> None:
        if mode == "preview":
            # 首次进预览要整图合成 (大图数秒), 给用户等待反馈
            from PyQt5.QtWidgets import QApplication
            from PyQt5.QtCore import Qt
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                mode_name = self._app.on_mode_changed(mode)
            finally:
                QApplication.restoreOverrideCursor()
        else:
            mode_name = self._app.on_mode_changed(mode)
        self._status_mode.setText(tr("status_mode").format(mode=mode_name))
        # 进入省份模式时检测 ID 空洞
        if mode == "province":
            self._check_province_gaps()

    def _on_preview_refresh(self) -> None:
        """预览页"刷新预览": 清合成缓存, 在预览模式则立即重新合成。"""
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtCore import Qt
        from features.map.preview import renderer as preview_renderer
        preview_renderer.invalidate_cache(self._canvas)
        if self._canvas.display_mode == "preview":
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                self._canvas._full_render()
            finally:
                QApplication.restoreOverrideCursor()

    def _on_preview_political_toggled(self, on: bool) -> None:
        """预览页"政治视图"开关: 叠加/取消国家势力色。"""
        self._canvas._preview_political = bool(on)
        if on:
            # 预览模式下国家色平时不刷新, 开叠加前拉一次最新数据
            self._app._refresh_country_colors()
        self._canvas._preview_political_cache = None
        if self._canvas.display_mode == "preview":
            self._canvas._full_render()

    def _on_preview_night_toggled(self, on: bool) -> None:
        """预览页"夜景"开关: 压暗底图并点亮 urban 城市灯光。"""
        self._canvas._preview_night = bool(on)
        self._canvas._preview_night_cache = None
        self._canvas._preview_night_src = None
        if self._canvas.display_mode == "preview":
            self._canvas._full_render()

    def _on_preview_game_dir_changed(self, path: str) -> None:
        """用户选择了游戏目录: 重建资产实例并作废预览缓存。"""
        from services.game_assets import set_default_install_dir
        from features.map.preview import renderer as preview_renderer
        set_default_install_dir(path)
        preview_renderer.invalidate_cache(self._canvas)

    def _check_province_gaps(self) -> None:
        """扫描省份 ID 空洞并更新提示。"""
        import numpy as np
        pm = self._project.map_data.province_map
        if pm is None or int(pm.max()) == 0:
            return
        max_id = int(pm.max())
        existing = set(np.unique(pm)) - {0}
        gap_ids = sorted(set(range(1, max_id + 1)) - existing)
        self._tool_panel.update_province_gaps(gap_ids)

    # ═══════════════════════ 省份点击路由 ═══════════════════

    def _on_province_clicked(self, pid: int) -> None:
        if pid <= 0:
            return

        # 批量建州模式
        if self._batch_state_mode:
            if pid in self._batch_state_pids:
                self._batch_state_pids.remove(pid)
            else:
                self._batch_state_pids.append(pid)
            self._status_info.setText(tr("status_selected_provinces_state").format(n=len(self._batch_state_pids)))
            # 画布高亮已选省份
            self._canvas.set_batch_selection_pids(self._batch_state_pids)
            return

        # 选州创建战略区域模式
        if self._sr_from_states_mode:
            sid = self._project.state_mgr.get_state_of_province(pid)
            if sid > 0:
                if sid in self._sr_selected_states:
                    self._sr_selected_states.remove(sid)
                else:
                    self._sr_selected_states.append(sid)
                # 收集所有选中州的省份 → 高亮
                all_pids: list[int] = []
                for s in self._sr_selected_states:
                    state = self._project.state_mgr.get_state(s)
                    if state:
                        all_pids.extend(state.provinces)
                self._canvas.set_batch_selection_pids(all_pids)
                self._status_info.setText(tr("status_selected_states").format(n=len(self._sr_selected_states)))
            else:
                self._status_info.setText(tr("status_province_no_state").format(pid=pid))
            return

        try:
            info = self._app.on_province_clicked(pid)
            if info:
                self._tool_panel.update_province_info(
                    pid, info["ptype"], info["terrain"],
                    info["pixels"], info["coastal"],
                )
        except Exception as e:
            self._status_info.setText(tr("status_operation_error").format(err=e))
            import traceback
            traceback.print_exc()

    def _on_province_double_clicked(self, pid: int) -> None:
        self._app.on_province_double_clicked(pid)

    def _on_province_right_clicked(self, pid: int) -> None:
        pass

    def _on_province_right_clicked_at(self, pid: int, screen_x: int, screen_y: int) -> None:
        if pid <= 0:
            return
        self._context_menu.show(pid, QPoint(screen_x, screen_y))

    def _on_provinces_cleared(self) -> None:
        self._update_province_count()
        self._status_info.setText(tr("status_provinces_cleared"))

    # ═══════════════════════ 撤销/重做 ═══════════════════════

    def _on_undo(self) -> None:
        msg = self._app.undo()
        self._status_info.setText(msg)
        self._update_province_count()

    def _on_redo(self) -> None:
        msg = self._app.redo()
        self._status_info.setText(msg)
        self._update_province_count()

    # ═══════════════════════ Province 操作 ═══════════════════

    def _on_split_toggled(self, on: bool) -> None:
        self._canvas._split_mode = on
        if on:
            self._status_info.setText(tr("province_hint_split"))
            # 如果已有选中省份，直接显示切割线
            pid = self._canvas._selected_province_id
            if pid > 0:
                self._canvas._init_split_preview(pid)
        else:
            self._canvas._split_ready = False
            self._canvas._split_line_item.setVisible(False)
            self._status_info.setText(tr("status_view_mode"))

    def _on_split_line_drawn(self, pid: int, path: list) -> None:
        """画线切割省份。"""
        ctrl: ProvinceController = self._controllers["province"]
        ctrl.selected_province_id = pid
        ok = ctrl.split_by_line(pid, path)
        if ok:
            self._update_province_count()
            # 刷新边界和高亮
            self._canvas._border_cache = None
            if hasattr(self._canvas, '_border_base_pixmap'):
                self._canvas._border_base_pixmap = None
            self._canvas._full_render()
            self._canvas._render_province_overlay()
            # 保持选中原省份，自动进入下一次切割预览
            if self._canvas._split_mode:
                self._canvas._init_split_preview(pid)

    def _on_merge_toggled(self, on: bool) -> None:
        self._controllers["province"].set_merge_mode(on)

    def _on_lasso_toggled(self, on: bool) -> None:
        if on:
            self._controllers["province"].set_merge_mode(False)
            from domain.tools import lasso_province  # noqa: F401
            self._canvas.set_framework_tool(
                "lasso_province",
                undo_mgr=self._undo_mgr,
                state_mgr=self._project.state_mgr,
                country_mgr=self._project.country_mgr,
            )
            self._status_info.setText(tr("status_expand_mode"))
        else:
            self._canvas.set_framework_tool(None)
            self._status_info.setText(tr("status_view_mode"))

    def _on_find_province(self, pid: int) -> None:
        """省份查找：跳转 + 高亮 + 同步信息条。"""
        import numpy as np
        if pid <= 0:
            return
        pm = self._canvas.province_map
        ys, xs = np.where(pm == pid)
        if len(ys) == 0:
            self._status_info.setText(tr("status_province_not_found").format(pid=pid))
            page = getattr(self._tool_panel, "_province_page", None)
            if page is not None and hasattr(page, "mark_find_not_found"):
                page.mark_find_not_found()
            return
        cx = int(xs.mean())
        cy = int(ys.mean())
        self._canvas.centerOn(float(cx), float(cy))
        # 复用省份模式的"选中"渲染做高亮
        self._canvas._selected_province_id = pid
        self._canvas._selected_province_tile = int(self._canvas._tile_map[cy, cx])
        self._canvas._render_province_overlay()
        # 通过 province controller 触发信息更新（让信息条/统计自动刷新）
        pctrl = self._controllers.get("province")
        if pctrl is not None and hasattr(pctrl, "on_province_clicked"):
            pctrl.on_province_clicked(pid)
        self._status_info.setText(tr("status_province_located").format(pid=pid))

    # ═══════════════════════ 批量建州 ═══════════════════════

    def _on_batch_state_toggled(self, on: bool) -> None:
        """开关批量选省份建州模式。"""
        self._batch_state_mode = on
        self._batch_state_pids = []
        # 关闭模式时清除高亮
        self._canvas.set_batch_selection_pids([])
        if on:
            self._status_info.setText(tr("status_batch_state_mode"))
        else:
            self._status_info.setText(tr("status_view_mode"))

    def _on_batch_state_confirmed(self) -> None:
        """确认用选中的省份创建新州。"""
        pids = self._batch_state_pids
        if not pids:
            QMessageBox.warning(self, tr("dlg_batch_state_title"), tr("dlg_batch_state_select_first"))
            return
        ctrl = self._controllers["state"]
        n = len(pids)
        new_sid = ctrl.create_state_from_provinces(pids)
        # 重置模式 + 清除高亮
        self._batch_state_mode = False
        self._batch_state_pids = []
        self._canvas.set_batch_selection_pids([])
        if new_sid > 0:
            self._canvas.refresh_display()
            QMessageBox.information(self, tr("dlg_batch_state_title"), tr("dlg_batch_state_done").format(sid=new_sid, n=n))

    # ═══════════════════════ 战略区域从州创建 ═══════════════════

    def _on_sr_from_states_toggled(self, on: bool) -> None:
        """开关选州创建战略区域模式。"""
        self._sr_from_states_mode = on
        self._sr_selected_states = []
        self._canvas.set_batch_selection_pids([])
        self._canvas.show_state_borders(on, self._project.state_mgr if on else None)
        if on:
            self._status_info.setText(tr("status_sr_from_states_mode"))
        else:
            self._status_info.setText(tr("status_view_mode"))

    def _on_sr_from_states_confirmed(self) -> None:
        """确认用选中的州创建战略区域。"""
        sids = self._sr_selected_states
        if not sids:
            QMessageBox.warning(self, tr("dlg_sr_from_states_title"), tr("dlg_sr_from_states_select_first"))
            return
        ctrl = self._controllers["strategic_region"]
        n = len(sids)
        new_rid = ctrl.create_from_states(sids)
        # 重置模式
        self._sr_from_states_mode = False
        self._sr_selected_states = []
        self._canvas.set_batch_selection_pids([])
        self._canvas.show_state_borders(False)
        if new_rid > 0:
            # 刷新战略区域颜色图 + 列表
            self._app._refresh_sr_colors()
            self._canvas.refresh_display()
            self._refresh_sr_list()
            QMessageBox.information(self, tr("dlg_sr_from_states_title"), tr("dlg_sr_from_states_done").format(rid=new_rid, n=n))

    # ═══════════════════════ State 管理 ═══════════════════════

    def _on_resplit_state(self, state_id: int, target_count: int) -> None:
        """重新分割州内省份: 确认 → 命令执行 (Ctrl+Z 可撤销) → 刷新。"""
        state = self._project.state_mgr.get_state(state_id)
        if not state or not state.provinces:
            return
        old_pids = set(state.provinces)
        lines = [
            tr("resplit_confirm_body").format(
                sid=state_id, name=state.name,
                old=len(old_pids), new=target_count),
        ]
        if state.victory_points:
            lines.append(tr("resplit_confirm_vp_warn").format(n=len(state.victory_points)))
        cap_tags = [
            tag for tag, c in self._project.country_mgr.countries.items()
            if c.capital in old_pids
        ]
        if cap_tags:
            lines.append(tr("resplit_confirm_capital_warn").format(tags=", ".join(cap_tags)))
        reply = QMessageBox.question(
            self, tr("resplit_confirm_title"), "\n\n".join(lines))
        if reply != QMessageBox.StandardButton.Yes:
            return

        from commands.state.resplit import ResplitStateCommand
        cmd = ResplitStateCommand(
            self._project.map_data, self._project.state_mgr,
            state_id, target_count,
        )
        self._cmd_history.execute(cmd)

        self._app._refresh_state_list()
        self._app._refresh_state_colors()
        self._update_province_count()
        self._canvas.refresh_display()
        self._status_info.setText(
            tr("resplit_done_status").format(sid=state_id, n=len(state.provinces)))

    def _on_state_detail_requested(self, state_id: int) -> None:
        state = self._project.state_mgr.get_state(state_id)
        if not state:
            return
        from features.map.state.detail_dialog import StateDetailDialog
        tags = list(self._project.country_mgr.countries.keys())
        dlg = StateDetailDialog(state, tags, parent=self)
        if dlg.exec_() == dlg.Accepted:
            self._app._refresh_state_list()
            self._status_info.setText(tr("status_state_updated").format(sid=state_id))

    # ═══════════════════════ 省份计数 ═══════════════════════

    def _update_province_count(self) -> None:
        count = self._app.update_province_count()
        self._status_provinces.setText(tr("status_provinces", count))

    # ═══════════════════════ 欢迎页 ═══════════════════════════

    def _check_for_update(self) -> None:
        """后台检查 GitHub 是否有新版本。"""
        import threading

        def _check():
            from services.update_checker import check_for_update
            result = check_for_update()
            if result:
                # 回到主线程弹窗
                QTimer.singleShot(0, lambda: self._show_update_dialog(result))

        threading.Thread(target=_check, daemon=True).start()

    def _show_update_dialog(self, info: dict) -> None:
        """显示更新提示对话框。"""
        import webbrowser
        from version import VERSION
        reply = QMessageBox.information(
            self, tr("dlg_update_title"),
            tr("dlg_update_body").format(
                current=VERSION, latest=info['version'],
                body=info['body'][:500],
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            webbrowser.open(info["url"])

    def _show_welcome(self) -> None:
        self._stack.setCurrentWidget(self._welcome_page)

    def _show_editor(self) -> None:
        self._stack.setCurrentWidget(self._editor)
        QTimer.singleShot(100, self._canvas.fit_in_view)

    def _on_language_changed(self, lang: str) -> None:
        """语言切换后刷新整个 UI。"""
        self._retranslate_ui()

    def _on_welcome_new(self, width: int, height: int) -> None:
        self._on_new_project()
        self._show_editor()
        self._maybe_show_guide()

    def _maybe_show_guide(self) -> None:
        """新建项目后弹出新手引导（除非用户勾了不再显示）。"""
        from views.guide_dialog import should_show_guide, GuideDialog
        if should_show_guide():
            dlg = GuideDialog(self)
            dlg.exec_()

    def _show_guide_force(self) -> None:
        """从帮助菜单强制打开引导。"""
        from views.guide_dialog import GuideDialog
        dlg = GuideDialog(self)
        dlg.exec_()

    def _reset_mode_hints(self) -> None:
        """重置所有模式操作提示。"""
        from ui.mode_hint_bar import ModeHintBar
        ModeHintBar.reset_all_hints()
        QMessageBox.information(self, tr("action_reset_hints"), tr("guide_reset_done"))

    def _on_welcome_open_recent(self, path: str) -> None:
        import os
        if not os.path.exists(path):
            QMessageBox.warning(self, tr("dlg_error"), tr("dlg_file_not_found").format(path=path))
            return
        self._load_project_file(path)
        save_recent_project(path)
        self._show_editor()

    def _on_welcome_import_mod(self) -> None:
        """欢迎页的导入MOD按钮：直接选文件夹 → 导入 → 进编辑器。"""
        from PyQt5.QtWidgets import QFileDialog

        mod_dir = QFileDialog.getExistingDirectory(
            self, tr("dlg_select_mod_dir"),
            "", QFileDialog.Option.ShowDirsOnly,
        )
        if not mod_dir:
            return
        self._import_mod_dir_with_progress(mod_dir)

    def _on_open_vanilla_reference(self) -> None:
        """打开原版游戏地图作为只读参考项目。

        游戏目录只在导入时被读取, 永远不会被写入; 导入结果不绑定任何
        项目文件, 保存时自动走"另存为" — 想保留修改只能存成自己的新项目,
        所以"原版不可被改坏"的语义天然成立。
        """
        from PyQt5.QtWidgets import QFileDialog
        from services.game_assets import find_hoi4_install

        # 编辑器里已开着项目时, 先确认替换
        if self._stack.currentWidget() is self._editor:
            reply = QMessageBox.question(
                self, tr("dlg_confirm"), tr("vanilla_confirm_replace"))
            if reply != QMessageBox.StandardButton.Yes:
                return

        game_dir = find_hoi4_install()
        if game_dir is None:
            QMessageBox.information(
                self, tr("vanilla_select_dir_title"), tr("vanilla_dir_not_found"))
            game_dir = QFileDialog.getExistingDirectory(
                self, tr("vanilla_select_dir_title"),
                "", QFileDialog.Option.ShowDirsOnly,
            )
            if not game_dir:
                return
        self._import_mod_dir_with_progress(game_dir, vanilla_note=True)

    def _import_mod_dir_with_progress(
            self, mod_dir: str, vanilla_note: bool = False) -> None:
        """带进度框的导入流程 (欢迎页导入MOD / 打开原版参考共用)。"""
        from PyQt5.QtWidgets import QProgressDialog
        from services.import_service import validate_mod_directory, import_mod_map

        missing = validate_mod_directory(mod_dir)
        if missing:
            QMessageBox.warning(
                self, tr("dlg_import_failed"),
                tr("dlg_import_missing_files") + "\n".join(missing),
            )
            return

        # 显示进度提示
        progress = QProgressDialog(tr("import_reading_files"), None, 0, 0, self)
        progress.setWindowTitle(tr("import_title"))
        progress.setMinimumDuration(0)
        progress.show()
        QApplication.processEvents()

        try:
            result = import_mod_map(mod_dir)
        except Exception as e:
            progress.close()
            import traceback
            QMessageBox.critical(
                self, tr("dlg_import_failed"),
                tr("dlg_import_read_error").format(err=e, tb=traceback.format_exc()),
            )
            return

        progress.setLabelText(tr("import_initializing"))
        QApplication.processEvents()

        new_w, new_h = result["width"], result["height"]

        from data.constants import set_map_size
        set_map_size(new_w, new_h)

        # 构建 MapData（不走 new_project 避免浪费 250MB 临时数组）
        from domain.map_data import MapData
        md = MapData()
        md.tile_map = result["tile_map"]
        md.province_map = result["province_map"]
        md.terrain_map = result["terrain_map"]
        md.height_map = result["height_map"]
        if result["river_map"] is not None:
            md.river_map = result["river_map"]
        md.provincial_terrain = result.get("provincial_terrain", {})
        self._project.map_data = md
        self._project.state_mgr.clear()
        self._project.country_mgr.clear()
        self._project.continent_mgr.clear()
        self._project.strategic_region_mgr.clear()
        self._project.railway_mgr.clear()
        self._project.supply_mgr.clear()
        self._project.adjacency_mgr.clear()

        # 保留导入的美术资产
        self._project.assets = dict(result.get("assets", {}))
        self._project.dirty_assets = set()

        # 填充导入的 states/strategic_regions/countries/railways/supply
        from views.main_window_file_ops import _populate_imported_data
        _populate_imported_data(self._project, result)
        self._project._dirty = False
        # 导入的项目不绑定项目文件 (原版参考尤其不能写回), 保存走另存为
        self._current_project_path = None

        self._canvas.set_map_data(md)
        self._canvas._scene.setSceneRect(0, 0, new_w, new_h)

        progress.setLabelText(tr("import_rendering"))
        QApplication.processEvents()

        self._show_editor()
        self._canvas.refresh_display()
        self._update_province_count()
        # 刷新着色（不然切到 state/country 模式看不到颜色）
        self._app._refresh_state_colors()
        self._app._refresh_country_colors()
        self._app._refresh_sr_colors()
        # 预计算质心缓存（VP 渲染和导出都需要）
        self._project.map_data.build_centroid_cache()
        self._app._refresh_vp_data()
        self._app._refresh_country_list()
        self._app._refresh_state_list()
        self._refresh_sr_list()
        self._project.mark_dirty()

        progress.close()

        info_text = tr("import_done").format(w=new_w, h=new_h, n=result['province_count'])
        self._status_info.setText(info_text)

        extra_text = ""
        if vanilla_note:
            extra_text = "\n\n" + tr("vanilla_opened_note")
        warnings_text = ""
        if result["warnings"]:
            warnings_text = "\n\n" + tr("import_warnings") + "\n".join(f"- {w}" for w in result["warnings"])
        QMessageBox.information(
            self, tr("import_done_title"), info_text + extra_text + warnings_text)

    # ═══════════════════════ 快捷键 ═══════════════════════════

    def _init_shortcuts(self) -> None:
        mgr = self._shortcut_mgr

        mgr.register("undo", self._on_undo)
        mgr.register("redo", self._on_redo)
        mgr.register("save", self._on_save_project)
        mgr.register("open", self._on_open_project)
        mgr.register("new", self._on_new_project)
        mgr.register("export", self._on_export_mod)
        mgr.register("zoom_fit", self._canvas.fit_in_view)

        # 模式切换
        modes = ["land", "province", "terrain", "height",
                 "river", "state", "country", "continent"]
        for mode_name in modes:
            key = f"mode_{mode_name}"
            mgr.register(key, lambda m=mode_name: self._on_mode_changed(m))

        # 工具切换
        tools = ["brush", "eraser", "fill", "transform", "pan"]
        for tool_name in tools:
            key = f"tool_{tool_name}"
            mgr.register(key, lambda t=tool_name: self._canvas.set_tool(t))

        mgr.register("delete", lambda: None)

        from PyQt5.QtWidgets import QShortcut
        from PyQt5.QtGui import QKeySequence as KS

        mode_tool_keys = [k for k in mgr.get_all_bindings()
                          if k.startswith("mode_") or k.startswith("tool_")]
        for name in mode_tool_keys:
            key_str = mgr.get_binding(name)
            cb = mgr._callbacks.get(name)
            if cb and key_str:
                sc = QShortcut(KS(key_str), self)
                sc.setContext(Qt.ShortcutContext.WindowShortcut)
                sc.activated.connect(cb)
                mgr._shortcuts.append(sc)

    def _on_shortcut_settings(self) -> None:
        show_shortcut_dialog(self, self._shortcut_mgr)
