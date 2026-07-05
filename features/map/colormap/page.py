"""总览贴图颜色 page — 独立 QWidget, 不依赖 ToolPanel.

3 个色块选择器 (陆/海/湖) + 重置按钮.
"""

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QColorDialog, QScrollArea,
)
from PyQt5.QtGui import QColor

from ui.i18n import tr
from ui.styles import (
    make_section as _make_section,
    _DIM_LABEL_STYLE, _LABEL_STYLE, _SECONDARY_BTN_STYLE,
)


class ColormapPage(QWidget):
    """总览贴图颜色页面."""

    # 输出信号
    colormap_color_changed = pyqtSignal(str, int, int, int)
    colormap_reset_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")

        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        tip = QLabel(tr("colormap_tip"))
        tip.setWordWrap(True)
        tip.setStyleSheet(_DIM_LABEL_STYLE)
        lay.addWidget(tip)

        # ── 颜色设置 ──
        color_box = _make_section(tr("colormap_section_colors"))
        cl = color_box.layout()

        self._swatches: dict[str, QPushButton] = {}
        for label_text, attr_name in [(tr("colormap_land_label"), "land"), (tr("colormap_sea_label"), "sea"), (tr("colormap_lake_label"), "lake")]:
            row = QHBoxLayout()
            lbl = QLabel(label_text)
            lbl.setMinimumWidth(60)
            lbl.setStyleSheet(_LABEL_STYLE)
            row.addWidget(lbl)
            swatch = QPushButton()
            swatch.setFixedSize(100, 28)
            swatch.setProperty("color_attr", attr_name)
            swatch.clicked.connect(lambda checked=False, s=swatch, a=attr_name: self._pick_color(s, a))
            row.addWidget(swatch)
            row.addStretch(1)
            cl.addLayout(row)
            self._swatches[attr_name] = swatch

        reset_btn = QPushButton(tr("colormap_reset_btn"))
        reset_btn.setStyleSheet(_SECONDARY_BTN_STYLE)
        reset_btn.clicked.connect(lambda: self.colormap_reset_requested.emit())
        cl.addWidget(reset_btn)
        lay.addWidget(color_box)

        lay.addStretch(1)
        scroll.setWidget(page)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll)

    def _pick_color(self, swatch: QPushButton, attr_name: str) -> None:
        """弹颜色选择器, 选完发信号."""
        qc = QColorDialog.getColor(QColor(128, 128, 128), self, tr("colormap_pick_color_title", attr_name))
        if qc.isValid():
            self.colormap_color_changed.emit(attr_name, qc.red(), qc.green(), qc.blue())
            swatch.setStyleSheet(
                f"background-color: rgb({qc.red()}, {qc.green()}, {qc.blue()});"
                f" border: 1px solid #2c2f36;"
            )
