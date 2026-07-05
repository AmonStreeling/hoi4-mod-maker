"""省份密度编辑页面 — 独立模式，画密度热力图控制省份疏密。"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QSlider, QLabel, QFrame,
)
from PyQt5.QtGui import QColor, QPixmap

from ui.styles import (
    make_section as _make_section,
    _DIM, _LABEL_STYLE, _DIM_LABEL_STYLE, _SLIDER_STYLE,
    _PRIMARY_BTN_STYLE, _SECONDARY_BTN_STYLE,
)
from ui.i18n import tr


class DensityPage(QWidget):
    """省份密度编辑页面。"""

    # 输出信号
    density_value_changed = pyqtSignal(float)     # 0.0~1.0
    density_brush_size_changed = pyqtSignal(int)
    density_soft_edge_changed = pyqtSignal(int)    # 0~100%
    density_clear_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(10)

        # 提示
        hint = QLabel(tr("density_hint"))
        hint.setStyleSheet(f"color: {_DIM}; font-size: 12px; padding: 8px;")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        # ── 画笔设置 ──
        brush_box = _make_section(tr("density_section_brush"))
        bl = brush_box.layout()

        # 画笔大小
        size_row = QHBoxLayout()
        size_lbl = QLabel(tr("density_label_brush_size"))
        size_lbl.setStyleSheet(_LABEL_STYLE)
        size_row.addWidget(size_lbl)
        self._size_label = QLabel("30px")
        self._size_label.setStyleSheet(_DIM_LABEL_STYLE)
        size_row.addStretch()
        size_row.addWidget(self._size_label)
        bl.addLayout(size_row)

        self._size_slider = QSlider(Qt.Orientation.Horizontal)
        self._size_slider.setRange(5, 200)
        self._size_slider.setValue(30)
        self._size_slider.setStyleSheet(_SLIDER_STYLE)
        self._size_slider.valueChanged.connect(self._on_size)
        bl.addWidget(self._size_slider)

        # 软边缘
        soft_row = QHBoxLayout()
        soft_lbl = QLabel(tr("density_label_soft_edge"))
        soft_lbl.setStyleSheet(_LABEL_STYLE)
        soft_row.addWidget(soft_lbl)
        self._soft_label = QLabel("50%")
        self._soft_label.setStyleSheet(_DIM_LABEL_STYLE)
        soft_row.addStretch()
        soft_row.addWidget(self._soft_label)
        bl.addLayout(soft_row)

        self._soft_slider = QSlider(Qt.Orientation.Horizontal)
        self._soft_slider.setRange(0, 100)
        self._soft_slider.setValue(50)
        self._soft_slider.setStyleSheet(_SLIDER_STYLE)
        self._soft_slider.valueChanged.connect(self._on_soft)
        bl.addWidget(self._soft_slider)

        lay.addWidget(brush_box)

        # ── 密度值 ──
        val_box = _make_section(tr("density_section_value"))
        vl = val_box.layout()

        # 密度滑块 + 色块预览
        val_row = QHBoxLayout()
        val_lbl = QLabel(tr("density_label_value"))
        val_lbl.setStyleSheet(_LABEL_STYLE)
        val_row.addWidget(val_lbl)

        self._color_preview = QLabel()
        self._color_preview.setFixedSize(20, 20)
        self._color_preview.setStyleSheet("border: 1px solid #2c2f36; border-radius: 3px;")
        val_row.addWidget(self._color_preview)

        self._val_label = QLabel("80%")
        self._val_label.setStyleSheet(_DIM_LABEL_STYLE)
        val_row.addStretch()
        val_row.addWidget(self._val_label)
        vl.addLayout(val_row)

        self._val_slider = QSlider(Qt.Orientation.Horizontal)
        self._val_slider.setRange(0, 100)
        self._val_slider.setValue(80)
        self._val_slider.setStyleSheet(_SLIDER_STYLE)
        self._val_slider.valueChanged.connect(self._on_value)
        vl.addWidget(self._val_slider)

        # 快捷预设
        preset_row = QHBoxLayout()
        preset_row.setSpacing(4)
        for name, val in [
            (tr("density_preset_sparse"), 20),
            (tr("density_preset_medium"), 50),
            (tr("density_preset_dense"), 90),
        ]:
            btn = QPushButton(name)
            btn.setStyleSheet(_SECONDARY_BTN_STYLE + "QPushButton { padding: 5px 8px; font-size: 12px; }")
            btn.clicked.connect(lambda _, v=val: self._val_slider.setValue(v))
            preset_row.addWidget(btn)
        vl.addLayout(preset_row)

        lay.addWidget(val_box)

        # 清空按钮 — 破坏性次要操作，视觉降权直接挂在外层（无需独立 section）
        clear_btn = QPushButton(tr("density_btn_clear"))
        clear_btn.setStyleSheet(
            _SECONDARY_BTN_STYLE
            + f"QPushButton {{ padding: 5px 8px; font-size: 12px; color: {_DIM}; }}"
        )
        clear_btn.setToolTip(tr("density_btn_clear_tip"))
        clear_btn.clicked.connect(self.density_clear_requested.emit)
        lay.addWidget(clear_btn)

        lay.addStretch()

        # 初始化色块预览
        self._update_color_preview(80)

    # ── 槽函数 ──

    def _on_size(self, v: int) -> None:
        self._size_label.setText(f"{v}px")
        self.density_brush_size_changed.emit(v)

    def _on_soft(self, v: int) -> None:
        self._soft_label.setText(f"{v}%")
        self.density_soft_edge_changed.emit(v)

    def _on_value(self, v: int) -> None:
        self._val_label.setText(f"{v}%")
        self._update_color_preview(v)
        self.density_value_changed.emit(v / 100.0)

    def _update_color_preview(self, percent: int) -> None:
        """更新色块预览（与热力图一致：红=密集，蓝=稀疏）。"""
        d = percent / 100.0
        r = int(d * 255)
        b = int((1 - d) * 200)
        px = QPixmap(20, 20)
        px.fill(QColor(r, 0, b))
        self._color_preview.setPixmap(px)
