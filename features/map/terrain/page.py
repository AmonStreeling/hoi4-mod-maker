"""terrain feature 页面 — 独立 QWidget, 不依赖 ToolPanel.

按 provincial terrain type 分组显示全部 graphical terrain 变体.
每个按钮带 atlas0.dds 的真实贴图缩略图，让制作者直观看到游戏里的材质。
"""

import os

from PyQt5.QtCore import Qt, QSize, pyqtSignal
from PyQt5.QtGui import QPixmap, QIcon, QPainter, QPen, QColor
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QGridLayout, QHBoxLayout, QGroupBox,
    QPushButton, QLabel, QScrollArea, QButtonGroup,
    QSlider, QCheckBox, QSpinBox, QLineEdit,
)

from data.terrain_types import (
    TERRAIN_TYPES, PAINTABLE_GROUPS, GRAPHICAL_TERRAINS,
    graphical_terrain_display_name,
)

from ui.styles import (
    make_section as _make_section,
    _DIM, _SECTION_STYLE, _PRIMARY_BTN_STYLE, _TOOL_BTN_STYLE,
    _SLIDER_STYLE, _LABEL_STYLE, _DIM_LABEL_STYLE, _SPINBOX_STYLE,
    _SECONDARY_BTN_STYLE, _LINEEDIT_STYLE,
)
from ui.i18n import tr

# 从 vanilla atlas0.dds 提取的每个 texture tile 的真实平均色 (RGB)
_ATLAS_COLORS: dict[int, tuple[int, int, int]] = {
    0:  (129, 140, 102),
    1:  (153, 159, 119),
    2:  (147, 150, 116),
    3:  (139, 137, 115),
    4:  (77,   96,  83),
    5:  (106, 128, 106),
    6:  (135, 157, 149),
    7:  (131, 133, 120),
    8:  (133, 147, 118),
    9:  (185, 176, 128),
    10: (134, 121, 105),
    11: (105,  98,  95),
    12: (195, 184, 133),
    13: (156, 135, 103),
    14: (154, 137, 112),
    15: (90,   79,  68),
}

# 分组显示顺序
_GROUP_ORDER = ["plains", "forest", "hills", "mountain", "desert", "marsh", "jungle", "urban"]

# 分组中文名
def _group_cn(key: str) -> str:
    """获取地形分组的翻译名称."""
    _TR_MAP = {
        "plains": "terrain_group_plains",
        "forest": "terrain_group_forest",
        "hills": "terrain_group_hills",
        "mountain": "terrain_group_mountain",
        "desert": "terrain_group_desert",
        "marsh": "terrain_group_marsh",
        "jungle": "terrain_group_jungle",
        "urban": "terrain_group_urban",
    }
    tr_key = _TR_MAP.get(key)
    return tr(tr_key) if tr_key else key

# atlas 贴图缩略图目录
_TILES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "..", "..", "..", "data", "atlas_tiles")




class TerrainPage(QWidget):
    """地形编辑页面."""

    # 输出信号
    terrain_index_changed = pyqtSignal(int)
    terrain_brush_mode_changed = pyqtSignal(bool)
    terrain_brush_size_changed = pyqtSignal(int)
    terrain_soft_edge_changed = pyqtSignal(bool)
    auto_terrain_requested = pyqtSignal()
    detail_terrain_requested = pyqtSignal(int)   # 按气候细化, 参数=种子
    beautify_terrain_requested = pyqtSignal(int) # 保形美化, 参数=种子
    downgrade_mountain_requested = pyqtSignal()
    downgrade_lasso_mode_toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(4)

        # ── 概念隔离 hint（顶部）──
        concept_hint = QLabel(tr("terrain_concept_hint"))
        concept_hint.setWordWrap(True)
        concept_hint.setTextFormat(Qt.RichText)
        concept_hint.setStyleSheet(
            f"color: {_DIM}; font-size: 11px; padding: 6px 8px;"
            f" background: rgba(108, 108, 240, 0.08);"
            f" border-left: 3px solid #6c6cf0; border-radius: 3px;"
        )
        outer.addWidget(concept_hint)

        # ── 智能生成设置 ──
        gen_box = _make_section(tr("terrain_section_auto_gen"))
        gl = gen_box.layout()

        auto_btn = QPushButton(tr("terrain_btn_auto_gen"))
        auto_btn.setStyleSheet(_PRIMARY_BTN_STYLE)
        auto_btn.clicked.connect(self.auto_terrain_requested.emit)
        gl.addWidget(auto_btn)

        detail_btn = QPushButton(tr("terrain_btn_detail_gen"))
        detail_btn.setStyleSheet(_PRIMARY_BTN_STYLE)
        detail_btn.setToolTip(tr("terrain_btn_detail_gen_tooltip"))
        detail_btn.clicked.connect(
            lambda: self.detail_terrain_requested.emit(self._seed_spin.value()))
        gl.addWidget(detail_btn)

        beautify_btn = QPushButton(tr("terrain_btn_beautify"))
        beautify_btn.setStyleSheet(_PRIMARY_BTN_STYLE)
        beautify_btn.setToolTip(tr("terrain_btn_beautify_tooltip"))
        beautify_btn.clicked.connect(
            lambda: self.beautify_terrain_requested.emit(self._seed_spin.value()))
        gl.addWidget(beautify_btn)

        # 种子
        seed_row = QHBoxLayout()
        seed_lbl = QLabel(tr("terrain_label_seed"))
        seed_lbl.setStyleSheet(_LABEL_STYLE)
        seed_row.addWidget(seed_lbl)
        self._seed_spin = QSpinBox()
        self._seed_spin.setRange(0, 99999)
        self._seed_spin.setValue(42)
        self._seed_spin.setStyleSheet(_SPINBOX_STYLE)
        seed_row.addWidget(self._seed_spin)
        rand_btn = QPushButton(tr("terrain_btn_random"))
        rand_btn.setStyleSheet(_SECONDARY_BTN_STYLE)
        rand_btn.setMaximumWidth(60)
        rand_btn.clicked.connect(self._randomize_seed)
        seed_row.addWidget(rand_btn)
        gl.addLayout(seed_row)

        # 噪声强度
        noise_row = QHBoxLayout()
        noise_lbl = QLabel(tr("terrain_label_noise"))
        noise_lbl.setStyleSheet(_LABEL_STYLE)
        noise_row.addWidget(noise_lbl)
        self._noise_label = QLabel("20")
        self._noise_label.setStyleSheet(_DIM_LABEL_STYLE)
        noise_row.addStretch()
        noise_row.addWidget(self._noise_label)
        gl.addLayout(noise_row)

        self._noise_slider = QSlider(Qt.Orientation.Horizontal)
        self._noise_slider.setRange(0, 50)
        self._noise_slider.setValue(20)
        self._noise_slider.setStyleSheet(_SLIDER_STYLE)
        self._noise_slider.valueChanged.connect(
            lambda v: self._noise_label.setText(str(v))
        )
        gl.addWidget(self._noise_slider)

        # 散点密度
        scatter_row = QHBoxLayout()
        scatter_lbl = QLabel(tr("terrain_label_scatter"))
        scatter_lbl.setStyleSheet(_LABEL_STYLE)
        scatter_row.addWidget(scatter_lbl)
        self._scatter_label = QLabel("65%")
        self._scatter_label.setStyleSheet(_DIM_LABEL_STYLE)
        scatter_row.addStretch()
        scatter_row.addWidget(self._scatter_label)
        gl.addLayout(scatter_row)

        self._scatter_slider = QSlider(Qt.Orientation.Horizontal)
        self._scatter_slider.setRange(0, 100)
        self._scatter_slider.setValue(65)
        self._scatter_slider.setStyleSheet(_SLIDER_STYLE)
        self._scatter_slider.valueChanged.connect(
            lambda v: self._scatter_label.setText(f"{v}%")
        )
        gl.addWidget(self._scatter_slider)

        # 山脉多少（阈值偏移）— 负数少山，正数多山
        off_row = QHBoxLayout()
        off_lbl = QLabel(tr("terrain_label_mountain_amount"))
        off_lbl.setStyleSheet(_LABEL_STYLE)
        off_row.addWidget(off_lbl)
        self._mountain_amount_label = QLabel("0")
        self._mountain_amount_label.setStyleSheet(_DIM_LABEL_STYLE)
        off_row.addStretch()
        off_row.addWidget(self._mountain_amount_label)
        gl.addLayout(off_row)

        self._mountain_amount_slider = QSlider(Qt.Orientation.Horizontal)
        self._mountain_amount_slider.setRange(-50, 50)
        self._mountain_amount_slider.setValue(0)
        self._mountain_amount_slider.setStyleSheet(_SLIDER_STYLE)
        self._mountain_amount_slider.valueChanged.connect(
            lambda v: self._mountain_amount_label.setText(
                f"{v:+d}  ({tr('terrain_mountain_less') if v < 0 else tr('terrain_mountain_more') if v > 0 else tr('terrain_mountain_default')})"
            )
        )
        gl.addWidget(self._mountain_amount_slider)

        # 降级强度滑块 (0-100%, 默认 50%)
        ds_row = QHBoxLayout()
        ds_lbl = QLabel(tr("terrain_label_downgrade_strength"))
        ds_lbl.setStyleSheet(_LABEL_STYLE)
        ds_row.addWidget(ds_lbl)
        self._downgrade_strength_label = QLabel("50%")
        self._downgrade_strength_label.setStyleSheet(_DIM_LABEL_STYLE)
        ds_row.addStretch()
        ds_row.addWidget(self._downgrade_strength_label)
        gl.addLayout(ds_row)

        self._downgrade_strength_slider = QSlider(Qt.Orientation.Horizontal)
        self._downgrade_strength_slider.setRange(0, 100)
        self._downgrade_strength_slider.setValue(50)
        self._downgrade_strength_slider.setStyleSheet(_SLIDER_STYLE)
        self._downgrade_strength_slider.valueChanged.connect(
            lambda v: self._downgrade_strength_label.setText(f"{v}%")
        )
        gl.addWidget(self._downgrade_strength_slider)

        # 一键降级山脉按钮
        self._downgrade_btn = QPushButton(tr("terrain_btn_downgrade"))
        self._downgrade_btn.setStyleSheet(_SECONDARY_BTN_STYLE)
        self._downgrade_btn.setToolTip(tr("terrain_btn_downgrade_tip"))
        self._downgrade_btn.clicked.connect(self.downgrade_mountain_requested.emit)
        gl.addWidget(self._downgrade_btn)

        # 选区降级按钮（套索选区）
        self._downgrade_lasso_btn = QPushButton(tr("terrain_btn_downgrade_region"))
        self._downgrade_lasso_btn.setCheckable(True)
        self._downgrade_lasso_btn.setStyleSheet(_SECONDARY_BTN_STYLE)
        self._downgrade_lasso_btn.setToolTip(tr("terrain_btn_downgrade_region_tip"))
        self._downgrade_lasso_btn.toggled.connect(self.downgrade_lasso_mode_toggled.emit)
        gl.addWidget(self._downgrade_lasso_btn)

        outer.addWidget(gen_box)

        # ── 编辑模式 ──
        mode_box = _make_section(tr("terrain_section_edit_mode"))
        mode_lay = mode_box.layout()
        mode_row = QHBoxLayout()
        self._terrain_mode_group = QButtonGroup(self)
        self._terrain_mode_group.setExclusive(True)
        province_btn = QPushButton(tr("terrain_mode_province"))
        province_btn.setCheckable(True)
        province_btn.setChecked(True)
        province_btn.setStyleSheet(_TOOL_BTN_STYLE)
        province_btn.setMinimumWidth(60)
        province_btn.setToolTip(tr("terrain_mode_province_tip"))
        self._terrain_mode_group.addButton(province_btn, 0)
        mode_row.addWidget(province_btn)
        brush_btn = QPushButton(tr("terrain_mode_brush"))
        brush_btn.setCheckable(True)
        brush_btn.setStyleSheet(_TOOL_BTN_STYLE)
        brush_btn.setMinimumWidth(60)
        brush_btn.setToolTip(tr("terrain_mode_brush_tip"))
        self._terrain_mode_group.addButton(brush_btn, 1)
        mode_row.addWidget(brush_btn)
        self._terrain_mode_group.idClicked.connect(self._on_mode_switched)
        mode_lay.addLayout(mode_row)
        outer.addWidget(mode_box)

        # 画笔控件 (画笔模式下可见)
        self._brush_box = _make_section(tr("terrain_section_brush"))
        bl = self._brush_box.layout()

        size_row = QHBoxLayout()
        size_lbl = QLabel(tr("terrain_label_size"))
        size_lbl.setStyleSheet(_LABEL_STYLE)
        size_row.addWidget(size_lbl)
        self._brush_size_label = QLabel("20px")
        self._brush_size_label.setStyleSheet(_DIM_LABEL_STYLE)
        size_row.addStretch()
        size_row.addWidget(self._brush_size_label)
        bl.addLayout(size_row)

        self._brush_size_slider = QSlider(Qt.Orientation.Horizontal)
        self._brush_size_slider.setRange(1, 200)
        self._brush_size_slider.setValue(20)
        self._brush_size_slider.setStyleSheet(_SLIDER_STYLE)
        self._brush_size_slider.valueChanged.connect(self._on_brush_size)
        bl.addWidget(self._brush_size_slider)

        self._soft_edge_cb = QCheckBox(tr("terrain_cb_soft_edge"))
        self._soft_edge_cb.setStyleSheet(f"color: {_DIM}; font-size: 12px;")
        self._soft_edge_cb.toggled.connect(self.terrain_soft_edge_changed.emit)
        bl.addWidget(self._soft_edge_cb)

        self._brush_box.hide()  # 默认省份模式，隐藏画笔设置
        outer.addWidget(self._brush_box)

        # ── 搜索框（过滤地形按钮）──
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText(tr("terrain_search_placeholder"))
        self._search_input.setStyleSheet(_LINEEDIT_STYLE)
        self._search_input.textChanged.connect(self._on_search_changed)
        outer.addWidget(self._search_input)

        # 用于过滤的引用
        self._terrain_btn_entries: list[tuple[QPushButton, str]] = []
        self._terrain_group_entries: list[tuple[QGroupBox, list[tuple[QPushButton, str]]]] = []

        # 可滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")
        scroll_content = QWidget()
        lay = QVBoxLayout(scroll_content)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        for group_type in _GROUP_ORDER:
            variants = PAINTABLE_GROUPS.get(group_type, [])
            if not variants:
                continue

            group_name = _group_cn(group_type)
            box = _make_section(f"{group_name} ({len(variants)})")
            group_btn_list: list[tuple[QPushButton, str]] = []
            # 加粗分组边框
            box.setStyleSheet(box.styleSheet() + """
                QGroupBox {
                    border: 2px solid #555;
                }
            """)
            grid = QGridLayout()
            grid.setSpacing(4)

            for i, gt in enumerate(variants):
                btn = QPushButton(graphical_terrain_display_name(gt))
                btn.setToolTip(
                    f"{tr('terrain_tip_index')}: {gt.palette_index}  {tr('terrain_tip_texture')}: {gt.texture}\n"
                    f"{tr('terrain_tip_type')}: {gt.type}  ID: {gt.id}"
                )

                # 加载 atlas 贴图缩略图作为图标 (带黑框)
                tile_path = os.path.normpath(
                    os.path.join(_TILES_DIR, f"texture_{gt.texture}.png")
                )
                if os.path.exists(tile_path):
                    pix = QPixmap(tile_path)
                    painter = QPainter(pix)
                    painter.setPen(QPen(QColor(0, 0, 0), 2))
                    painter.drawRect(0, 0, pix.width() - 1, pix.height() - 1)
                    painter.end()
                    btn.setIcon(QIcon(pix))
                    btn.setIconSize(QSize(40, 40))

                # 用 atlas 贴图的真实平均色做背景
                r, g, b = _ATLAS_COLORS.get(gt.texture, (128, 128, 128))
                if gt.perm_snow:
                    r = min(255, r + 50)
                    g = min(255, g + 50)
                    b = min(255, b + 70)
                brightness = r * 0.299 + g * 0.587 + b * 0.114
                fg = "#000000" if brightness > 130 else "#ffffff"
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: rgb({r},{g},{b});
                        border: 2px solid transparent;
                        color: {fg};
                        padding: 4px 6px;
                        font-size: 12px;
                        font-weight: 600;
                        border-radius: 4px;
                        min-height: 44px;
                        text-align: left;
                    }}
                    QPushButton:hover {{
                        border-color: white;
                    }}
                """)
                btn.clicked.connect(
                    lambda _, idx=gt.palette_index: self.terrain_index_changed.emit(idx)
                )
                grid.addWidget(btn, i, 0)
                # 记录按钮 + 可搜索文本（display name + 内部 id + 类型 + 分组名）
                search_text = " ".join([
                    graphical_terrain_display_name(gt) or "",
                    gt.id or "",
                    gt.type or "",
                    group_name,
                ])
                entry = (btn, search_text)
                self._terrain_btn_entries.append(entry)
                group_btn_list.append(entry)

            box.layout().addLayout(grid)
            lay.addWidget(box)
            self._terrain_group_entries.append((box, group_btn_list))

        lay.addStretch()
        scroll.setWidget(scroll_content)
        outer.addWidget(scroll)

    # ── 槽函数 ──

    def _on_mode_switched(self, mode_id: int) -> None:
        is_brush = mode_id == 1
        self.terrain_brush_mode_changed.emit(is_brush)
        self._brush_box.setVisible(is_brush)

    def _on_search_changed(self, text: str) -> None:
        """按输入文本过滤地形按钮 + 空组自动隐藏。"""
        q = text.strip().lower()
        for box, btns in self._terrain_group_entries:
            any_visible = False
            for btn, search_text in btns:
                match = (not q) or (q in search_text.lower())
                btn.setVisible(match)
                if match:
                    any_visible = True
            box.setVisible(any_visible)

    def _on_brush_size(self, size: int) -> None:
        self._brush_size_label.setText(f"{size}px")
        self.terrain_brush_size_changed.emit(size)

    def _randomize_seed(self) -> None:
        import random
        self._seed_spin.setValue(random.randint(0, 99999))

    def reset_downgrade_lasso_button(self) -> None:
        """套索画完后外部调这个取消勾选。"""
        if self._downgrade_lasso_btn.isChecked():
            self._downgrade_lasso_btn.blockSignals(True)
            self._downgrade_lasso_btn.setChecked(False)
            self._downgrade_lasso_btn.blockSignals(False)

    def get_downgrade_strength(self) -> float:
        """返回当前降级强度 (0.0..1.0)。"""
        return self._downgrade_strength_slider.value() / 100.0

    def get_gen_config(self):
        """返回当前 UI 参数构建的 TerrainGenConfig。"""
        from services.terrain_service import TerrainGenConfig
        return TerrainGenConfig(
            noise_amplitude=float(self._noise_slider.value()),
            scatter_strength=self._scatter_slider.value() / 100.0,
            threshold_offset=int(self._mountain_amount_slider.value()),
            seed=self._seed_spin.value(),
        )
