"""大陆分区 page — 独立 QWidget, 不依赖 ToolPanel.

功能: 大陆列表 CRUD + 拾取省份指派.
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QInputDialog, QScrollArea, QCheckBox,
)

from ui.i18n import tr
from ui.styles import (
    make_section as _make_section,
    _DIM_LABEL_STYLE, _PRIMARY_BTN_STYLE, _LIST_STYLE,
)


class ContinentPage(QWidget):
    """大陆分区页面."""

    # 输出信号
    continent_pick_toggled = pyqtSignal(bool)
    continent_add_requested = pyqtSignal(str)
    continent_rename_requested = pyqtSignal(int, str)
    continent_remove_requested = pyqtSignal(int)
    assign_by_state_changed = pyqtSignal(bool)

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

        tip = QLabel(tr("continent_tip"))
        tip.setWordWrap(True)
        tip.setStyleSheet(_DIM_LABEL_STYLE)
        lay.addWidget(tip)

        # ── 大陆列表 ──
        list_box = _make_section(tr("continent_list_section"))
        ll = list_box.layout()

        self._continent_list = QListWidget()
        self._continent_list.setStyleSheet(_LIST_STYLE)
        self._continent_list.setMinimumHeight(200)
        ll.addWidget(self._continent_list)

        btn_row = QHBoxLayout()
        add_btn = QPushButton(tr("continent_add_btn"))
        add_btn.clicked.connect(self._on_add_continent)
        rename_btn = QPushButton(tr("continent_rename_btn"))
        rename_btn.clicked.connect(self._on_rename_continent)
        remove_btn = QPushButton(tr("continent_delete_btn"))
        remove_btn.clicked.connect(self._on_remove_continent)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(rename_btn)
        btn_row.addWidget(remove_btn)
        ll.addLayout(btn_row)
        lay.addWidget(list_box)

        # ── 指派省份 ──
        assign_box = _make_section(tr("continent_assign_section"))
        al = assign_box.layout()

        self._continent_pick_btn = QPushButton(tr("continent_pick_btn"))
        self._continent_pick_btn.setCheckable(True)
        self._continent_pick_btn.setStyleSheet(_PRIMARY_BTN_STYLE)
        self._continent_pick_btn.toggled.connect(
            lambda on: self.continent_pick_toggled.emit(on)
        )
        al.addWidget(self._continent_pick_btn)

        self._by_state_cb = QCheckBox(tr("continent_assign_by_state"))
        self._by_state_cb.toggled.connect(self.assign_by_state_changed.emit)
        al.addWidget(self._by_state_cb)

        self._continent_status = QLabel("")
        self._continent_status.setStyleSheet("color: #4f8cff; font-size: 11px;")
        al.addWidget(self._continent_status)
        lay.addWidget(assign_box)

        lay.addStretch(1)
        scroll.setWidget(page)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll)

    # ── 槽函数 ──
    def _on_add_continent(self) -> None:
        name, ok = QInputDialog.getText(self, tr("continent_add_dlg_title"), tr("continent_add_dlg_label"))
        if ok and name.strip():
            self.continent_add_requested.emit(name.strip())

    def _on_rename_continent(self) -> None:
        item = self._continent_list.currentItem()
        if item is None:
            return
        # 优先读 UserRole (refresh 时存的真实名)，回退到旧的文本解析
        old = item.data(Qt.UserRole)
        if not old:
            old = item.text().split(".")[1].strip().split("(")[0].strip() if "." in item.text() else ""
        name, ok = QInputDialog.getText(self, tr("continent_rename_dlg_title"), tr("continent_rename_dlg_label"), text=old)
        if ok and name.strip():
            row = self._continent_list.currentRow()
            self.continent_rename_requested.emit(row, name.strip())

    def _on_remove_continent(self) -> None:
        row = self._continent_list.currentRow()
        if row < 0:
            return
        from PyQt5.QtWidgets import QMessageBox
        item = self._continent_list.currentItem()
        name = item.text() if item else f"#{row}"
        ret = QMessageBox.question(
            self, tr("continent_remove_confirm_title"),
            tr("continent_remove_confirm_msg").format(name=name),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ret == QMessageBox.Yes:
            self.continent_remove_requested.emit(row)
