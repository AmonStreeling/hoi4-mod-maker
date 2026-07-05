"""省份属性地形 page — 选地形类型按钮 + 操作说明。

操作：选地形类型 → 点击画布上的 province → 该 province gameplay 地形 = 该类型。
不动 terrain.bmp 视觉、不动 height_map 高度。
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QButtonGroup, QCheckBox,
)

from data.terrain_types import TERRAIN_TYPES, terrain_display_name
from ui.styles import (
    make_section as _make_section,
    _DIM, _DIM_LABEL_STYLE,
)
from ui.i18n import tr


# 8 种 land 类型（不含 ocean/lakes）
_LAND_TYPES = ["plains", "forest", "hills", "mountain",
               "desert", "marsh", "jungle", "urban"]


class ProvincialTerrainPage(QWidget):
    """省份属性地形选择页面。"""

    type_changed = pyqtSignal(str)
    assign_mode_changed = pyqtSignal(bool)  # True=分配模式（点改地形）/ False=查看模式（点只看信息）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        intro = QLabel(tr("pterrain_intro"))
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {_DIM}; font-size: 12px; padding: 4px;")
        intro.setTextFormat(Qt.TextFormat.RichText)
        outer.addWidget(intro)

        # 分配模式开关
        self._assign_chk = QCheckBox(tr("pterrain_assign_mode"))
        self._assign_chk.setChecked(False)  # 默认关闭，避免误改
        self._assign_chk.setStyleSheet(
            f"QCheckBox {{ color: #e8eaed; font-size: 14px; font-weight: 600; padding: 6px; }}"
            f"QCheckBox:checked {{ color: #86efac; }}"  # 开启后变绿
        )
        self._assign_chk.toggled.connect(self.assign_mode_changed)
        outer.addWidget(self._assign_chk)

        type_box = _make_section(tr("pterrain_section_types"))
        type_layout = type_box.layout()
        grid = QGridLayout()
        grid.setSpacing(4)

        self._btn_group = QButtonGroup(self)
        self._btn_group.setExclusive(True)

        for i, tname in enumerate(_LAND_TYPES):
            terrain = TERRAIN_TYPES.get(tname)
            if terrain is None:
                continue
            r, g, b = terrain.color
            btn = QPushButton(f"{terrain_display_name(terrain)}\n({tname})")
            btn.setCheckable(True)
            btn.setMinimumHeight(50)
            btn.setStyleSheet(
                f"QPushButton {{ background: rgb({r},{g},{b}); color: #fff; "
                f"border: 1px solid #333; border-radius: 4px; padding: 4px; "
                f"font-size: 11px; font-weight: 500; }} "
                f"QPushButton:checked {{ border: 2px solid #fff; }}"
            )
            btn.setProperty("type_name", tname)
            self._btn_group.addButton(btn, i)
            grid.addWidget(btn, i // 2, i % 2)

        type_layout.addLayout(grid)
        outer.addWidget(type_box)

        first = self._btn_group.button(0)
        if first:
            first.setChecked(True)

        self._btn_group.buttonClicked.connect(self._on_type_clicked)

        plains_name = terrain_display_name(TERRAIN_TYPES["plains"]) if "plains" in TERRAIN_TYPES else "plains"
        self._status_label = QLabel(tr("pterrain_current_label", plains_name, "plains"))
        self._status_label.setStyleSheet(_DIM_LABEL_STYLE)
        outer.addWidget(self._status_label)

        outer.addStretch()

    def _on_type_clicked(self, btn: QPushButton) -> None:
        tname = btn.property("type_name")
        if tname:
            terrain = TERRAIN_TYPES.get(tname)
            name = terrain_display_name(terrain) if terrain else tname
            self._status_label.setText(tr("pterrain_current_label", name, tname))
            self.type_changed.emit(tname)

    def current_type(self) -> str:
        btn = self._btn_group.checkedButton()
        if btn is None:
            return "plains"
        return btn.property("type_name") or "plains"
