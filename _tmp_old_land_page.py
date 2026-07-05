"""land feature 页面 — 独立 QWidget, 不依赖 ToolPanel."""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QSlider, QLabel, QButtonGroup,
    QSpinBox, QGridLayout, QFrame,
)

from data.constants import (
    TILE_LAND, TILE_SEA, TILE_LAKE,
    BRUSH_MIN, BRUSH_MAX, BRUSH_DEFAULT,
)

from ui.styles import (
    make_section as _make_section,
    _DIM, _BORDER, _SECTION_STYLE, _LABEL_STYLE, _DIM_LABEL_STYLE, _SLIDER_STYLE,
    _TOOL_BTN_STYLE, _TILE_BTN_STYLE, _PRIMARY_BTN_STYLE, _SECONDARY_BTN_STYLE,
    _SPINBOX_STYLE, _color_icon,
)
from ui.i18n import tr




class LandPage(QWidget):
    """陆地/海洋/湖泊绘制页面."""

    # 输出信号
    tool_changed = pyqtSignal(str)
    tile_type_changed = pyqtSignal(int)
    brush_size_changed = pyqtSignal(int)
    generate_provinces_requested = pyqtSignal(int)
    validate_requested = pyqtSignal()
    smooth_coast_requested = pyqtSignal()
    clear_new_land_mask_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(10)

        # ── 地块类型（互斥 toggle，默认选陆地）──
        tile_box = _make_section(tr("land_section_tile_draw"))
        tile_row = QHBoxLayout()
        tile_row.setSpacing(3)
        self._tile_group = QButtonGroup(self)
        self._tile_group.setExclusive(True)
        for tile_id, label, color in [
            (TILE_LAND, tr("land_draw_land"), (139, 172, 101)),
            (TILE_SEA,  tr("land_draw_sea"), (68, 105, 156)),
            (TILE_LAKE, tr("land_draw_lake"), (100, 160, 210)),
        ]:
            btn = QPushButton(f"  {label}")
            btn.setIcon(_color_icon(*color))
            btn.setCheckable(True)
            btn.setProperty("tile_id", tile_id)
            btn.setStyleSheet(_TILE_BTN_STYLE)
            btn.clicked.connect(lambda _, t=tile_id: self._on_tile_click(t))
            self._tile_group.addButton(btn)
            tile_row.addWidget(btn)
            if tile_id == TILE_LAND:
                btn.setChecked(True)
        tile_box.layout().addLayout(tile_row)
        lay.addWidget(tile_box)

        # ── 工具 + 画笔大小（合并为一个 section）──
        # 按性质分三组：[绘制] | [编辑] | [导航]，用竖线视觉分隔
        tools_box = _make_section(tr("land_section_tools"))
        tl = QHBoxLayout()
        tl.setSpacing(3)
        self._land_tool_group = QButtonGroup(self)
        self._land_tool_group.setExclusive(True)

        tool_groups: list[list[tuple[str, str]]] = [
            # 绘制
            [("brush", tr("land_tool_brush")),
             ("eraser", tr("land_tool_eraser")),
             ("fill", tr("land_tool_fill"))],
            # 增量（new_land 工具，记入 mask 用于增量生成）
            [("new_land", tr("land_tool_new_land"))],
            # 编辑（框选）
            [("transform", tr("land_tool_transform"))],
        ]

        for gi, group in enumerate(tool_groups):
            if gi > 0:
                sep = QFrame()
                sep.setFixedWidth(1)
                sep.setStyleSheet(f"background: {_BORDER}; margin: 4px 6px;")
                tl.addWidget(sep)
            for tid, label in group:
                btn = QPushButton(label)
                btn.setCheckable(True)
                btn.setProperty("tool_id", tid)
                btn.setStyleSheet(_TOOL_BTN_STYLE)
                if tid == "transform":
                    btn.setToolTip(tr("land_tool_transform_tip"))
                elif tid == "fill":
                    btn.setToolTip(tr("land_tool_fill_tip"))
                elif tid == "new_land":
                    btn.setToolTip(tr("land_tool_new_land_tip"))
                self._land_tool_group.addButton(btn)
                tl.addWidget(btn)
                if tid == "brush":
                    btn.setChecked(True)
        self._land_tool_group.buttonClicked.connect(
            lambda b: self.tool_changed.emit(b.property("tool_id"))
        )
        tools_box.layout().addLayout(tl)

        # 画笔大小（内嵌在工具 section 里）
        brush_row = QHBoxLayout()
        lbl = QLabel(tr("land_label_size"))
        lbl.setStyleSheet(_LABEL_STYLE)
        brush_row.addWidget(lbl)
        brush_row.addStretch()
        self._land_brush_label = QLabel(f"{BRUSH_DEFAULT}px")
        self._land_brush_label.setStyleSheet(_DIM_LABEL_STYLE)
        brush_row.addWidget(self._land_brush_label)
        tools_box.layout().addLayout(brush_row)

        self._land_brush_slider = QSlider(Qt.Orientation.Horizontal)
        self._land_brush_slider.setRange(BRUSH_MIN, BRUSH_MAX)
        self._land_brush_slider.setValue(BRUSH_DEFAULT)
        self._land_brush_slider.setStyleSheet(_SLIDER_STYLE)
        self._land_brush_slider.valueChanged.connect(self._on_land_brush)
        tools_box.layout().addWidget(self._land_brush_slider)

        # 导航/操作 入口提示（含可点击的"清空扩展遮罩"链接）
        tip_label = QLabel(tr("land_nav_tip"))
        tip_label.setStyleSheet(f"color: {_DIM}; font-size: 11px; padding: 4px 2px;")
        tip_label.setWordWrap(True)
        tip_label.setTextFormat(Qt.RichText)
        tip_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        tip_label.linkActivated.connect(self._on_tip_link)
        tools_box.layout().addWidget(tip_label)
        lay.addWidget(tools_box)

        # ── 省份生成 ──
        gen_box = _make_section(tr("land_section_province_gen"))

        # 平滑海岸线（建议生成省份前使用，所以收进此 section 顶部）
        coast_btn = QPushButton(tr("land_btn_smooth_coast"))
        coast_btn.setStyleSheet(_SECONDARY_BTN_STYLE)
        coast_btn.setToolTip(tr("land_btn_smooth_coast_tip"))
        coast_btn.clicked.connect(self.smooth_coast_requested.emit)
        gen_box.layout().addWidget(coast_btn)

        spin_row = QHBoxLayout()
        spin_lbl = QLabel(tr("land_label_province_count"))
        spin_lbl.setStyleSheet(_LABEL_STYLE)
        spin_row.addWidget(spin_lbl)
        self._province_count_spin = QSpinBox()
        self._province_count_spin.setRange(100, 20000)
        self._province_count_spin.setSingleStep(500)
        self._province_count_spin.setValue(12000)
        self._province_count_spin.setStyleSheet(_SPINBOX_STYLE)
        spin_row.addWidget(self._province_count_spin)
        gen_box.layout().addLayout(spin_row)

        # 海洋省份密度
        sea_row = QHBoxLayout()
        sea_lbl = QLabel(tr("land_label_sea_density"))
        sea_lbl.setStyleSheet(_LABEL_STYLE)
        sea_row.addWidget(sea_lbl)
        self._sea_density_label = QLabel("15%")
        self._sea_density_label.setStyleSheet(_DIM_LABEL_STYLE)
        sea_row.addStretch()
        sea_row.addWidget(self._sea_density_label)
        gen_box.layout().addLayout(sea_row)

        self._sea_density_slider = QSlider(Qt.Orientation.Horizontal)
        self._sea_density_slider.setRange(5, 100)
        self._sea_density_slider.setValue(15)
        self._sea_density_slider.setStyleSheet(_SLIDER_STYLE)
        self._sea_density_slider.valueChanged.connect(
            lambda v: self._sea_density_label.setText(f"{v}%")
        )
        gen_box.layout().addWidget(self._sea_density_slider)

        # 湖泊省份密度
        lake_row = QHBoxLayout()
        lake_lbl = QLabel(tr("land_label_lake_density"))
        lake_lbl.setStyleSheet(_LABEL_STYLE)
        lake_row.addWidget(lake_lbl)
        self._lake_density_label = QLabel("30%")
        self._lake_density_label.setStyleSheet(_DIM_LABEL_STYLE)
        lake_row.addStretch()
        lake_row.addWidget(self._lake_density_label)
        gen_box.layout().addLayout(lake_row)

        self._lake_density_slider = QSlider(Qt.Orientation.Horizontal)
        self._lake_density_slider.setRange(10, 100)
        self._lake_density_slider.setValue(30)
        self._lake_density_slider.setStyleSheet(_SLIDER_STYLE)
        self._lake_density_slider.valueChanged.connect(
            lambda v: self._lake_density_label.setText(f"{v}%")
        )
        gen_box.layout().addWidget(self._lake_density_slider)

        # 生成 + 验证 并排
        gen_btn_row = QHBoxLayout()
        gen_btn_row.setSpacing(4)
        gen_btn = QPushButton(tr("land_btn_generate"))
        gen_btn.setStyleSheet(_PRIMARY_BTN_STYLE)
        gen_btn.setToolTip(tr("land_btn_generate_tip"))
        gen_btn.clicked.connect(self._on_generate_provinces)
        gen_btn_row.addWidget(gen_btn)

        validate_btn = QPushButton(tr("land_btn_validate"))
        validate_btn.setStyleSheet(_SECONDARY_BTN_STYLE)
        validate_btn.clicked.connect(self.validate_requested.emit)
        gen_btn_row.addWidget(validate_btn)
        gen_box.layout().addLayout(gen_btn_row)

        # 增量/全量提示（按钮下方常驻小灰字，不依赖 hover）
        gen_subhint = QLabel(tr("land_btn_generate_subhint"))
        gen_subhint.setStyleSheet(f"color: {_DIM}; font-size: 11px; padding: 2px;")
        gen_subhint.setWordWrap(True)
        gen_box.layout().addWidget(gen_subhint)

        lay.addWidget(gen_box)

        # ── 参考图（合并为一个 section）──
        ref_box = _make_section(tr("land_section_ref"))

        # 原版参考
        v_lbl = QLabel(tr("land_section_vanilla_ref"))
        v_lbl.setStyleSheet(_LABEL_STYLE)
        ref_box.layout().addWidget(v_lbl)

        v_row = QHBoxLayout()
        v_row.setSpacing(4)
        self._vanilla_ref_opacity_label = QLabel("30%")
        self._vanilla_ref_opacity_label.setStyleSheet(_DIM_LABEL_STYLE)
        self._vanilla_ref_opacity_label.setFixedWidth(36)
        self._vanilla_ref_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._vanilla_ref_opacity_slider.setRange(0, 100)
        self._vanilla_ref_opacity_slider.setValue(30)
        self._vanilla_ref_opacity_slider.setStyleSheet(_SLIDER_STYLE)
        self._vanilla_ref_opacity_slider.valueChanged.connect(
            lambda v: self._vanilla_ref_opacity_label.setText(f"{v}%")
        )
        self._vanilla_ref_toggle = QPushButton(tr("land_btn_hide"))
        self._vanilla_ref_toggle.setCheckable(True)
        self._vanilla_ref_toggle.setStyleSheet(_SECONDARY_BTN_STYLE)
        self._vanilla_ref_toggle.setMinimumWidth(50)
        self._vanilla_ref_toggle.toggled.connect(
            lambda on: self._vanilla_ref_toggle.setText(tr("land_btn_show") if on else tr("land_btn_hide"))
        )
        v_row.addWidget(self._vanilla_ref_opacity_slider)
        v_row.addWidget(self._vanilla_ref_opacity_label)
        v_row.addWidget(self._vanilla_ref_toggle)
        ref_box.layout().addLayout(v_row)

        # 自定义参考
        c_lbl = QLabel(tr("land_section_custom_ref"))
        c_lbl.setStyleSheet(_LABEL_STYLE)
        ref_box.layout().addWidget(c_lbl)

        c_row = QHBoxLayout()
        c_row.setSpacing(4)
        self._ref_opacity_label = QLabel("40%")
        self._ref_opacity_label.setStyleSheet(_DIM_LABEL_STYLE)
        self._ref_opacity_label.setFixedWidth(36)
        self._ref_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._ref_opacity_slider.setRange(0, 100)
        self._ref_opacity_slider.setValue(40)
        self._ref_opacity_slider.setStyleSheet(_SLIDER_STYLE)
        self._ref_opacity_slider.valueChanged.connect(
            lambda v: self._ref_opacity_label.setText(f"{v}%")
        )
        self._ref_toggle = QPushButton(tr("land_btn_hide"))
        self._ref_toggle.setCheckable(True)
        self._ref_toggle.setStyleSheet(_SECONDARY_BTN_STYLE)
        self._ref_toggle.setMinimumWidth(50)
        self._ref_toggle.toggled.connect(
            lambda on: self._ref_toggle.setText(tr("land_btn_show") if on else tr("land_btn_hide"))
        )
        c_row.addWidget(self._ref_opacity_slider)
        c_row.addWidget(self._ref_opacity_label)
        c_row.addWidget(self._ref_toggle)
        ref_box.layout().addLayout(c_row)

        # 缩放 + 铺满
        scale_row = QHBoxLayout()
        scale_row.setSpacing(4)
        slbl = QLabel(tr("land_label_scale"))
        slbl.setStyleSheet(_LABEL_STYLE)
        scale_row.addWidget(slbl)
        self._ref_scale_label = QLabel("100%")
        self._ref_scale_label.setStyleSheet(_DIM_LABEL_STYLE)
        scale_row.addWidget(self._ref_scale_label)
        scale_row.addStretch()
        self._ref_fit_btn = QPushButton(tr("land_btn_fit_map"))
        self._ref_fit_btn.setStyleSheet(_SECONDARY_BTN_STYLE)
        self._ref_fit_btn.setMinimumWidth(70)
        scale_row.addWidget(self._ref_fit_btn)
        ref_box.layout().addLayout(scale_row)

        self._ref_scale_slider = QSlider(Qt.Orientation.Horizontal)
        self._ref_scale_slider.setRange(10, 500)
        self._ref_scale_slider.setValue(100)
        self._ref_scale_slider.setStyleSheet(_SLIDER_STYLE)
        self._ref_scale_slider.valueChanged.connect(
            lambda v: self._ref_scale_label.setText(f"{v}%")
        )
        ref_box.layout().addWidget(self._ref_scale_slider)

        lay.addWidget(ref_box)

        lay.addStretch()

    # ── 槽函数 ──
    def _on_land_brush(self, size: int) -> None:
        self._land_brush_label.setText(f"{size}px")
        self.brush_size_changed.emit(size)

    def _on_tile_click(self, tile_type: int) -> None:
        self.tile_type_changed.emit(tile_type)
        # 自动切换到画笔工具
        for btn in self._land_tool_group.buttons():
            if btn.property("tool_id") == "brush":
                btn.setChecked(True)
                self.tool_changed.emit("brush")
                break

    def _on_generate_provinces(self) -> None:
        count = self._province_count_spin.value()
        self.generate_provinces_requested.emit(count)

    def _on_tip_link(self, href: str) -> None:
        """提示条 HTML 链接点击 — 当前只有清空扩展遮罩。"""
        if href == "clear_new_land_mask":
            self.clear_new_land_mask_requested.emit()

    def get_generation_params(self) -> dict:
        """返回省份生成的所有参数。"""
        return {
            "target_count": self._province_count_spin.value(),
            "sea_scale": self._sea_density_slider.value() / 100.0,
            "lake_scale": self._lake_density_slider.value() / 100.0,
        }
