"""land feature 页面 — 独立 QWidget, 不依赖 ToolPanel.

2026-07 UI 试点页: 按 MOD 作者的做事顺序排布 —
① 垫参考底图描海岸 → ② 画陆海+修海岸 → ③ 生成省份。
分组用 make_card (内嵌标题+步骤徽标), 信号接口与旧版完全一致。
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QSlider, QLabel, QButtonGroup, QRadioButton,
    QSpinBox, QFrame,
)

from data.constants import (
    TILE_LAND, TILE_SEA, TILE_LAKE,
    BRUSH_MIN, BRUSH_MAX, BRUSH_DEFAULT,
)

from ui.styles import (
    make_card as _make_card,
    make_hint as _make_hint,
    _DIM, _BORDER, _LABEL_STYLE, _DIM_LABEL_STYLE, _SLIDER_STYLE,
    _TOOL_BTN_STYLE, _TILE_BTN_STYLE, _PRIMARY_BTN_STYLE, _SECONDARY_BTN_STYLE,
    _SPINBOX_STYLE, _color_icon,
)
from ui.i18n import tr


# 调整模式开关: 平时次要按钮外观, 勾选后橙色 = "进行中"（与变换工具一致）
_ADJUST_BTN_STYLE = _SECONDARY_BTN_STYLE + """
    QPushButton:checked {
        background: #f97316;
        border: 2px solid #fb923c;
        color: white;
        font-weight: 700;
    }
"""


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
    import_ref_requested = pyqtSignal()          # 导入自定义参考图片
    open_vanilla_requested = pyqtSignal()        # 打开原版参考
    ref_adjust_toggled = pyqtSignal(bool)        # 调整参考图模式开关
    ref_adjust_target_changed = pyqtSignal(str)  # 调整对象: "custom"/"vanilla"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(10)

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

        # 原版参考: 透明度 + 缩放 + 隐藏
        (self._vanilla_ref_opacity_slider, self._vanilla_ref_opacity_label,
         self._vanilla_ref_toggle) = self._add_ref_group(
            ref_card, tr("land_section_vanilla_ref"), opacity=30)
        (self._vanilla_ref_scale_slider,
         self._vanilla_ref_scale_label) = self._add_scale_row(ref_card)

        # 自定义参考图: 同样一套
        (self._ref_opacity_slider, self._ref_opacity_label,
         self._ref_toggle) = self._add_ref_group(
            ref_card, tr("land_section_custom_ref"), opacity=40)
        (self._ref_scale_slider,
         self._ref_scale_label) = self._add_scale_row(ref_card)

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

        # ══ ② 绘制陆地与海洋 — 类型 / 工具 / 画笔 / 修海岸 ══
        draw_card = _make_card(tr("land_section_tile_draw"), "②")

        tile_row = QHBoxLayout()
        tile_row.setSpacing(3)
        self._tile_group = QButtonGroup(self)
        self._tile_group.setExclusive(True)
        for tile_id, label, color, tip_key in [
            (TILE_LAND, tr("land_draw_land"), (139, 172, 101), "land_draw_land_tip"),
            (TILE_SEA,  tr("land_draw_sea"), (68, 105, 156), "land_draw_sea_tip"),
            (TILE_LAKE, tr("land_draw_lake"), (100, 160, 210), "land_draw_lake_tip"),
        ]:
            btn = QPushButton(f"  {label}")
            btn.setIcon(_color_icon(*color))
            btn.setCheckable(True)
            btn.setProperty("tile_id", tile_id)
            btn.setStyleSheet(_TILE_BTN_STYLE)
            btn.setToolTip(tr(tip_key))
            btn.clicked.connect(lambda _, t=tile_id: self._on_tile_click(t))
            self._tile_group.addButton(btn)
            tile_row.addWidget(btn)
            if tile_id == TILE_LAND:
                btn.setChecked(True)
        draw_card.layout().addLayout(tile_row)

        # 工具行: [绘制] | [增量] | [编辑]
        tl = QHBoxLayout()
        tl.setSpacing(3)
        self._land_tool_group = QButtonGroup(self)
        self._land_tool_group.setExclusive(True)

        tool_groups: list[list[tuple[str, str]]] = [
            [("brush", tr("land_tool_brush")),
             ("eraser", tr("land_tool_eraser")),
             ("fill", tr("land_tool_fill"))],
            [("new_land", tr("land_tool_new_land"))],
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
        draw_card.layout().addLayout(tl)

        # 画笔大小
        brush_row = QHBoxLayout()
        lbl = QLabel(tr("land_label_size"))
        lbl.setStyleSheet(_LABEL_STYLE)
        brush_row.addWidget(lbl)
        brush_row.addStretch()
        self._land_brush_label = QLabel(f"{BRUSH_DEFAULT}px")
        self._land_brush_label.setStyleSheet(_DIM_LABEL_STYLE)
        brush_row.addWidget(self._land_brush_label)
        draw_card.layout().addLayout(brush_row)

        self._land_brush_slider = QSlider(Qt.Orientation.Horizontal)
        self._land_brush_slider.setRange(BRUSH_MIN, BRUSH_MAX)
        self._land_brush_slider.setValue(BRUSH_DEFAULT)
        self._land_brush_slider.setStyleSheet(_SLIDER_STYLE)
        self._land_brush_slider.valueChanged.connect(self._on_land_brush)
        draw_card.layout().addWidget(self._land_brush_slider)

        # 平滑海岸线 — 属于"画完修边", 放在绘制卡片里
        coast_btn = QPushButton(tr("land_btn_smooth_coast"))
        coast_btn.setStyleSheet(_SECONDARY_BTN_STYLE)
        coast_btn.setToolTip(tr("land_btn_smooth_coast_tip"))
        coast_btn.clicked.connect(self.smooth_coast_requested.emit)
        draw_card.layout().addWidget(coast_btn)

        # 导航/操作提示（含可点击的"清空扩展遮罩"链接）
        tip_label = QLabel(tr("land_nav_tip"))
        tip_label.setStyleSheet(f"color: {_DIM}; font-size: 11px; padding: 4px 2px;")
        tip_label.setWordWrap(True)
        tip_label.setTextFormat(Qt.RichText)
        tip_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        tip_label.linkActivated.connect(self._on_tip_link)
        draw_card.layout().addWidget(tip_label)

        lay.addWidget(draw_card)

        # ══ ③ 生成省份 — 陆海画好之后 ══
        gen_card = _make_card(tr("land_section_province_gen"), "③")

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
        gen_card.layout().addLayout(spin_row)

        sea_row = QHBoxLayout()
        sea_lbl = QLabel(tr("land_label_sea_density"))
        sea_lbl.setStyleSheet(_LABEL_STYLE)
        sea_row.addWidget(sea_lbl)
        self._sea_density_label = QLabel("15%")
        self._sea_density_label.setStyleSheet(_DIM_LABEL_STYLE)
        sea_row.addStretch()
        sea_row.addWidget(self._sea_density_label)
        gen_card.layout().addLayout(sea_row)

        self._sea_density_slider = QSlider(Qt.Orientation.Horizontal)
        self._sea_density_slider.setRange(5, 100)
        self._sea_density_slider.setValue(15)
        self._sea_density_slider.setStyleSheet(_SLIDER_STYLE)
        self._sea_density_slider.valueChanged.connect(
            lambda v: self._sea_density_label.setText(f"{v}%")
        )
        gen_card.layout().addWidget(self._sea_density_slider)

        lake_row = QHBoxLayout()
        lake_lbl = QLabel(tr("land_label_lake_density"))
        lake_lbl.setStyleSheet(_LABEL_STYLE)
        lake_row.addWidget(lake_lbl)
        self._lake_density_label = QLabel("30%")
        self._lake_density_label.setStyleSheet(_DIM_LABEL_STYLE)
        lake_row.addStretch()
        lake_row.addWidget(self._lake_density_label)
        gen_card.layout().addLayout(lake_row)

        self._lake_density_slider = QSlider(Qt.Orientation.Horizontal)
        self._lake_density_slider.setRange(10, 100)
        self._lake_density_slider.setValue(30)
        self._lake_density_slider.setStyleSheet(_SLIDER_STYLE)
        self._lake_density_slider.valueChanged.connect(
            lambda v: self._lake_density_label.setText(f"{v}%")
        )
        gen_card.layout().addWidget(self._lake_density_slider)

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
        gen_card.layout().addLayout(gen_btn_row)

        gen_card.layout().addWidget(
            _make_hint(tr("land_btn_generate_subhint")))

        lay.addWidget(gen_card)

        lay.addStretch()

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
        """一行缩放控制: 缩放滑条 + %。"""
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
        row.addWidget(slider)
        row.addWidget(val)
        card.layout().addLayout(row)
        return slider, val

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
