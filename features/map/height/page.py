"""height feature 页面 — 高度图编辑。

流程: 画完陆海 → 点「智能生成」自动算高度 → 用画笔微调 → 切地形模式生成地形。
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QSlider, QLabel, QGridLayout, QSpinBox,
    QButtonGroup,
)

from ui.styles import (
    make_section as _make_section,
    _DIM, _LABEL_STYLE, _DIM_LABEL_STYLE, _SLIDER_STYLE,
    _PRIMARY_BTN_STYLE, _SECONDARY_BTN_STYLE, _SPINBOX_STYLE,
)
from ui.i18n import tr


class HeightPage(QWidget):
    """高度编辑页面."""

    # 输出信号
    height_value_changed = pyqtSignal(int)
    auto_height_requested = pyqtSignal()
    realistic_height_requested = pyqtSignal()    # 真实感高度图 (山链/平原/大陆架)
    height_from_terrain_requested = pyqtSignal()
    ridge_mode_toggled = pyqtSignal(bool)       # 山脉画线模式开关
    ridge_peak_changed = pyqtSignal(int)         # 山峰高度
    ridge_falloff_changed = pyqtSignal(int)      # 衰减距离
    ridge_preview_requested = pyqtSignal()       # 请求刷新预览
    ridge_confirmed = pyqtSignal()               # 确认应用山脉
    ridge_cancelled = pyqtSignal()               # 取消山脉
    refine_whole_map_requested = pyqtSignal()    # 保形精修整张高度图（生成菜单第③项）
    # 手动微调画笔
    height_brush_mode_changed = pyqtSignal(str)   # "off" | "raise" | "lower" | "smooth"
    height_brush_size_changed = pyqtSignal(int)
    height_brush_strength_changed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _on_generate_menu(self) -> None:
        """单一生成入口: 弹出选择题, 按用户情况发射对应的既有信号。"""
        from ui.option_dialog import OptionChooserDialog
        # 顺序 = 用户的做事顺序: ①自动生成 → ②按地形反推 → ③精修当前
        key = OptionChooserDialog.choose(self, tr("height_gen_menu_title"), [
            ("realistic", tr("height_gen_opt_realistic"),
             tr("height_gen_opt_realistic_desc")),
            ("from_terrain", tr("height_gen_opt_from_terrain"),
             tr("height_gen_opt_from_terrain_desc")),
            ("refine", tr("height_gen_opt_refine"),
             tr("height_gen_opt_refine_desc")),
        ])
        if key == "realistic":
            self.realistic_height_requested.emit()
        elif key == "refine":
            self.refine_whole_map_requested.emit()
        elif key == "from_terrain":
            self.height_from_terrain_requested.emit()

    def _init_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(10)

        # ═══════ 🏔 顶部：一键智能生成高度（推荐）═══════
        from ui.styles import _ACCENT
        auto_top_box = _make_section(tr("height_auto_top_section"))
        auto_top_layout = auto_top_box.layout()

        # 单一入口: 三种生成/优化方式收进一个"说人话的选择题"对话框
        # (2026-07-04 用户反馈"按钮太多不知道点哪个" — 每页只留一个生成入口)
        gen_menu_btn = QPushButton(tr("height_btn_generate_menu"))
        gen_menu_btn.setMinimumHeight(44)
        gen_menu_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {_ACCENT};"
            f"  color: white;"
            f"  border: none;"
            f"  border-radius: 6px;"
            f"  font-size: 15px;"
            f"  font-weight: 600;"
            f"  padding: 8px;"
            f"}}"
            f"QPushButton:hover {{ background: #6ba1ff; }}"
        )
        gen_menu_btn.setToolTip(tr("height_btn_generate_menu_tooltip"))
        gen_menu_btn.clicked.connect(self._on_generate_menu)
        auto_top_layout.addWidget(gen_menu_btn)

        auto_top_tip = QLabel(tr("height_gen_menu_tip"))
        auto_top_tip.setStyleSheet(f"color: {_DIM}; font-size: 12px; padding: 4px 2px;")
        auto_top_tip.setWordWrap(True)
        auto_top_layout.addWidget(auto_top_tip)

        lay.addWidget(auto_top_box)

        # ── 详细参数（自动生成区）──
        gen_box = _make_section(tr("height_section_auto_gen"))
        gl = gen_box.layout()

        # 种子
        seed_row = QHBoxLayout()
        seed_lbl = QLabel(tr("height_label_seed"))
        seed_lbl.setStyleSheet(_LABEL_STYLE)
        seed_row.addWidget(seed_lbl)
        self._height_seed_spin = QSpinBox()
        self._height_seed_spin.setRange(0, 99999)
        self._height_seed_spin.setValue(42)
        self._height_seed_spin.setStyleSheet(_SPINBOX_STYLE)
        seed_row.addWidget(self._height_seed_spin)
        rand_btn = QPushButton(tr("height_btn_random"))
        rand_btn.setStyleSheet(_SECONDARY_BTN_STYLE)
        rand_btn.setMaximumWidth(60)
        rand_btn.clicked.connect(self._randomize_seed)
        seed_row.addWidget(rand_btn)
        gl.addLayout(seed_row)

        # 山脉强度
        mt_row = QHBoxLayout()
        mt_lbl = QLabel(tr("height_label_mountain"))
        mt_lbl.setStyleSheet(_LABEL_STYLE)
        mt_row.addWidget(mt_lbl)
        self._mountain_label = QLabel("200")
        self._mountain_label.setStyleSheet(_DIM_LABEL_STYLE)
        mt_row.addStretch()
        mt_row.addWidget(self._mountain_label)
        gl.addLayout(mt_row)

        self._mountain_slider = QSlider(Qt.Orientation.Horizontal)
        self._mountain_slider.setRange(50, 400)
        self._mountain_slider.setValue(200)
        self._mountain_slider.setStyleSheet(_SLIDER_STYLE)
        self._mountain_slider.valueChanged.connect(
            lambda v: self._mountain_label.setText(str(v))
        )
        gl.addWidget(self._mountain_slider)

        # 提示：改了参数要再次点[一键生成]才生效
        gen_hint = QLabel(tr("height_gen_params_hint"))
        gen_hint.setStyleSheet(f"color: {_DIM}; font-size: 11px; padding: 4px 2px;")
        gen_hint.setWordWrap(True)
        gl.addWidget(gen_hint)

        lay.addWidget(gen_box)

        # ── 山脉画线 ──
        ridge_box = _make_section(tr("height_section_ridge"))
        rl = ridge_box.layout()

        self._ridge_btn = QPushButton(tr("height_btn_ridge"))
        self._ridge_btn.setCheckable(True)
        self._ridge_btn.setStyleSheet(_PRIMARY_BTN_STYLE)
        self._ridge_btn.toggled.connect(self._on_ridge_toggled)
        rl.addWidget(self._ridge_btn)

        # 山峰高度
        rpk_row = QHBoxLayout()
        rpk_lbl = QLabel(tr("height_label_ridge_peak"))
        rpk_lbl.setStyleSheet(_LABEL_STYLE)
        rpk_row.addWidget(rpk_lbl)
        self._ridge_peak_label = QLabel("220")
        self._ridge_peak_label.setStyleSheet(_DIM_LABEL_STYLE)
        rpk_row.addStretch()
        rpk_row.addWidget(self._ridge_peak_label)
        rl.addLayout(rpk_row)

        self._ridge_peak_slider = QSlider(Qt.Orientation.Horizontal)
        self._ridge_peak_slider.setRange(100, 255)
        self._ridge_peak_slider.setValue(220)
        self._ridge_peak_slider.setStyleSheet(_SLIDER_STYLE)
        self._ridge_peak_slider.valueChanged.connect(
            lambda v: (self._ridge_peak_label.setText(str(v)), self.ridge_peak_changed.emit(v))
        )
        rl.addWidget(self._ridge_peak_slider)

        # 衰减距离
        rfo_row = QHBoxLayout()
        rfo_lbl = QLabel(tr("height_label_ridge_falloff"))
        rfo_lbl.setStyleSheet(_LABEL_STYLE)
        rfo_row.addWidget(rfo_lbl)
        self._ridge_falloff_label = QLabel("80px")
        self._ridge_falloff_label.setStyleSheet(_DIM_LABEL_STYLE)
        rfo_row.addStretch()
        rfo_row.addWidget(self._ridge_falloff_label)
        rl.addLayout(rfo_row)

        self._ridge_falloff_slider = QSlider(Qt.Orientation.Horizontal)
        self._ridge_falloff_slider.setRange(20, 300)
        self._ridge_falloff_slider.setValue(80)
        self._ridge_falloff_slider.setStyleSheet(_SLIDER_STYLE)
        self._ridge_falloff_slider.valueChanged.connect(
            lambda v: (self._ridge_falloff_label.setText(f"{v}px"), self.ridge_falloff_changed.emit(v))
        )
        rl.addWidget(self._ridge_falloff_slider)

        # 确认/取消按钮（画完线后显示）
        self._ridge_confirm_row = QWidget()
        cr = QHBoxLayout(self._ridge_confirm_row)
        cr.setContentsMargins(0, 8, 0, 0)
        cr.setSpacing(8)

        self._ridge_cancel_btn = QPushButton(tr("btn_cancel"))
        self._ridge_cancel_btn.setStyleSheet(_SECONDARY_BTN_STYLE)
        self._ridge_cancel_btn.clicked.connect(self.ridge_cancelled.emit)
        cr.addWidget(self._ridge_cancel_btn)

        self._ridge_confirm_btn = QPushButton(tr("height_btn_ridge_confirm"))
        self._ridge_confirm_btn.setStyleSheet(
            "QPushButton { background: #22c55e; color: white; padding: 8px;"
            " border-radius: 4px; font-weight: bold; font-size: 13px; }"
            "QPushButton:hover { background: #2ad66a; }"
        )
        self._ridge_confirm_btn.clicked.connect(self.ridge_confirmed.emit)
        cr.addWidget(self._ridge_confirm_btn)

        rl.addWidget(self._ridge_confirm_row)
        self._ridge_confirm_row.hide()

        # 滑块变化时请求刷新预览
        self._ridge_peak_slider.valueChanged.connect(lambda _: self._on_ridge_param_changed())
        self._ridge_falloff_slider.valueChanged.connect(lambda _: self._on_ridge_param_changed())

        lay.addWidget(ridge_box)

        # ── 手动微调 ──
        brush_box = _make_section(tr("height_section_manual"))
        bl = brush_box.layout()

        val_row = QHBoxLayout()
        vlbl = QLabel(tr("height_label_value"))
        vlbl.setStyleSheet(_LABEL_STYLE)
        val_row.addWidget(vlbl)
        self._height_value_label = QLabel("120")
        self._height_value_label.setStyleSheet(_DIM_LABEL_STYLE)
        val_row.addStretch()
        val_row.addWidget(self._height_value_label)
        bl.addLayout(val_row)

        self._height_slider = QSlider(Qt.Orientation.Horizontal)
        self._height_slider.setRange(0, 255)
        self._height_slider.setValue(120)
        self._height_slider.setStyleSheet(_SLIDER_STYLE)
        self._height_slider.valueChanged.connect(self._on_height_value)
        bl.addWidget(self._height_slider)

        # 快捷预设
        preset_row = QHBoxLayout()
        preset_row.setSpacing(4)
        for name, val in [(tr("height_preset_seabed"), 40), (tr("height_preset_sealevel"), 95), (tr("height_preset_flat"), 110),
                          (tr("height_preset_hills"), 150), (tr("height_preset_mountain"), 200)]:
            btn = QPushButton(name)
            btn.setStyleSheet(_SECONDARY_BTN_STYLE + "QPushButton { padding: 4px 6px; font-size: 11px; }")
            btn.setToolTip(tr("height_preset_tip", val))
            btn.clicked.connect(lambda _, v=val: self._height_slider.setValue(v))
            preset_row.addWidget(btn)
        bl.addLayout(preset_row)

        # ── 雕刻画笔（抬升 / 下沉 / 平滑）──
        sep = QLabel("—— " + tr("height_brush_section") + " ——")
        sep.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sep.setStyleSheet(f"color: {_DIM}; font-size: 11px; padding: 6px 0 2px 0;")
        bl.addWidget(sep)

        brush_row = QHBoxLayout()
        brush_row.setSpacing(4)
        # 非互斥按钮组 — 再次点击已选按钮 = 关闭画笔（切回按省份模式）
        self._brush_group = QButtonGroup(self)
        self._brush_group.setExclusive(False)
        self._brush_btns: dict[str, QPushButton] = {}
        for key, label_key, tip_key in [
            ("raise", "height_brush_raise", "height_brush_raise_tip"),
            ("lower", "height_brush_lower", "height_brush_lower_tip"),
            ("smooth", "height_brush_smooth", "height_brush_smooth_tip"),
        ]:
            b = QPushButton(tr(label_key))
            b.setCheckable(True)
            b.setToolTip(tr(tip_key))
            b.setStyleSheet(
                "QPushButton {"
                "  background: #3a3a3a; color: #ddd; border: 1px solid #555;"
                "  padding: 6px; border-radius: 4px; font-size: 12px; font-weight: 600;"
                "}"
                "QPushButton:hover { border-color: #88e; }"
                "QPushButton:checked { background: #6a5acd; color: white; border-color: #8a78ff; }"
            )
            b.clicked.connect(lambda _=False, k=key: self._on_brush_button(k))
            self._brush_group.addButton(b)
            self._brush_btns[key] = b
            brush_row.addWidget(b)
        bl.addLayout(brush_row)

        # 画笔尺寸
        bsize_row = QHBoxLayout()
        bsize_lbl = QLabel(tr("height_brush_size"))
        bsize_lbl.setStyleSheet(_LABEL_STYLE)
        bsize_row.addWidget(bsize_lbl)
        self._brush_size_label = QLabel("30px")
        self._brush_size_label.setStyleSheet(_DIM_LABEL_STYLE)
        bsize_row.addStretch()
        bsize_row.addWidget(self._brush_size_label)
        bl.addLayout(bsize_row)

        self._brush_size_slider = QSlider(Qt.Orientation.Horizontal)
        self._brush_size_slider.setRange(4, 200)
        self._brush_size_slider.setValue(30)
        self._brush_size_slider.setStyleSheet(_SLIDER_STYLE)
        self._brush_size_slider.valueChanged.connect(self._on_brush_size)
        bl.addWidget(self._brush_size_slider)

        # 强度（每刷一下改变多少 / 平滑多快）
        bstr_row = QHBoxLayout()
        bstr_lbl = QLabel(tr("height_brush_strength"))
        bstr_lbl.setStyleSheet(_LABEL_STYLE)
        bstr_row.addWidget(bstr_lbl)
        self._brush_strength_label = QLabel("5")
        self._brush_strength_label.setStyleSheet(_DIM_LABEL_STYLE)
        bstr_row.addStretch()
        bstr_row.addWidget(self._brush_strength_label)
        bl.addLayout(bstr_row)

        self._brush_strength_slider = QSlider(Qt.Orientation.Horizontal)
        self._brush_strength_slider.setRange(1, 20)
        self._brush_strength_slider.setValue(5)
        self._brush_strength_slider.setStyleSheet(_SLIDER_STYLE)
        self._brush_strength_slider.valueChanged.connect(self._on_brush_strength)
        bl.addWidget(self._brush_strength_slider)

        lay.addWidget(brush_box)

        lay.addStretch()

    # ── 槽函数 ──
    def _on_height_value(self, value: int) -> None:
        self._height_value_label.setText(str(value))
        self.height_value_changed.emit(value)

    def _randomize_seed(self) -> None:
        import random
        self._height_seed_spin.setValue(random.randint(0, 99999))

    def get_height_config(self):
        """返回当前 UI 参数构建的 HeightGenConfig。"""
        from services.terrain_service import HeightGenConfig
        return HeightGenConfig(
            noise_amplitude=float(self._mountain_slider.value()),
            seed=self._height_seed_spin.value(),
        )

    def show_ridge_confirm(self) -> None:
        """画完线后显示确认/取消按钮。"""
        self._ridge_confirm_row.show()

    def hide_ridge_confirm(self) -> None:
        """隐藏确认/取消按钮。"""
        self._ridge_confirm_row.hide()

    def _on_ridge_param_changed(self) -> None:
        """滑块变化时，如果确认按钮可见（预览中），请求刷新预览。"""
        if self._ridge_confirm_row.isVisible():
            self.ridge_preview_requested.emit()

    def _on_ridge_toggled(self, on: bool) -> None:
        """山脉画线开关：打开时关闭雕刻画笔（两者互斥）。"""
        if on:
            any_brush = any(b.isChecked() for b in getattr(self, '_brush_btns', {}).values())
            if any_brush:
                for b in self._brush_btns.values():
                    b.blockSignals(True)
                    b.setChecked(False)
                    b.blockSignals(False)
                self.height_brush_mode_changed.emit("off")
        self.ridge_mode_toggled.emit(on)

    # ── 雕刻画笔 ──
    def _on_brush_button(self, key: str) -> None:
        """点击画笔按钮：同按钮再点 = 关闭；其它按钮 = 切换到该模式。"""
        clicked_btn = self._brush_btns[key]
        # 取消其它画笔按钮勾选
        for k, b in self._brush_btns.items():
            if k != key and b.isChecked():
                b.blockSignals(True)
                b.setChecked(False)
                b.blockSignals(False)
        # 与山脉画线互斥：激活画笔时关闭山脉模式
        if clicked_btn.isChecked() and self._ridge_btn.isChecked():
            self._ridge_btn.setChecked(False)  # 触发 ridge_mode_toggled(False)
        if clicked_btn.isChecked():
            self.height_brush_mode_changed.emit(key)
        else:
            self.height_brush_mode_changed.emit("off")

    def _on_brush_size(self, size: int) -> None:
        self._brush_size_label.setText(f"{size}px")
        self.height_brush_size_changed.emit(size)

    def _on_brush_strength(self, s: int) -> None:
        self._brush_strength_label.setText(str(s))
        self.height_brush_strength_changed.emit(s)

    def deactivate_brush(self) -> None:
        """切走高度页时取消画笔激活状态。"""
        for b in self._brush_btns.values():
            b.blockSignals(True)
            b.setChecked(False)
            b.blockSignals(False)
        self.height_brush_mode_changed.emit("off")
