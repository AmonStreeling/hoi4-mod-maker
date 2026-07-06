"""state feature 页面 — 独立 QWidget, 不依赖 ToolPanel."""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QLabel, QSpinBox, QListWidget, QListWidgetItem,
    QComboBox, QLineEdit, QCheckBox,
)

from domain.managers.state import StateManager

from ui.i18n import tr
from ui.styles import (
    make_section as _make_section,
    _DIM, _SECTION_STYLE, _LABEL_STYLE, _DIM_LABEL_STYLE,
    _PRIMARY_BTN_STYLE, _SPINBOX_STYLE, _LINEEDIT_STYLE,
    _COMBOBOX_STYLE, _LIST_STYLE,
)


def _format_state_item(sid: int, name: str, count: int, tag: str) -> str:
    """格式化 state list item 文本（含国家归属）。"""
    if tag:
        return tr("state_list_item_fmt").format(sid=sid, name=name, tag=tag, count=count)
    return tr("state_list_item_fmt_no_owner").format(sid=sid, name=name, count=count)




class StatePage(QWidget):
    """州编辑页面."""

    # 输出信号
    auto_states_requested = pyqtSignal(int)
    state_selected = pyqtSignal(int)
    state_property_changed = pyqtSignal(int, str, object)
    state_detail_requested = pyqtSignal(int)
    batch_create_state_toggled = pyqtSignal(bool)
    batch_create_state_confirmed = pyqtSignal()
    assign_mode_changed = pyqtSignal(bool)
    state_delete_requested = pyqtSignal(int)
    show_names_toggled = pyqtSignal(bool)
    resplit_state_requested = pyqtSignal(int, int)  # (state_id, 目标省份数)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_state_id = 0
        # 缓存当前 state 列表数据用于搜索过滤（每次 update_state_list 覆盖）
        self._state_items_cache: list[tuple[int, str, int, str]] = []
        self._search_text: str = ""
        self._init_ui()

    def _init_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(10)

        # ── 快速开始 ──
        quick_box = _make_section(tr("state_quick_section"))
        ql = quick_box.layout()
        auto_row = QHBoxLayout()
        auto_btn = QPushButton(tr("state_auto_btn"))
        auto_btn.setStyleSheet(_PRIMARY_BTN_STYLE)
        auto_btn.clicked.connect(self._on_auto_states)
        auto_row.addWidget(auto_btn, 2)
        spin_lbl = QLabel(tr("state_per_spin_label"))
        spin_lbl.setStyleSheet(_LABEL_STYLE)
        auto_row.addWidget(spin_lbl)
        self._state_per_spin = QSpinBox()
        self._state_per_spin.setRange(5, 30)
        self._state_per_spin.setValue(15)
        self._state_per_spin.setStyleSheet(_SPINBOX_STYLE)
        self._state_per_spin.setToolTip(tr("state_per_spin_tip"))
        auto_row.addWidget(self._state_per_spin, 1)
        ql.addLayout(auto_row)

        self._show_names_chk = QCheckBox(tr("state_show_names_label"))
        self._show_names_chk.setChecked(True)
        self._show_names_chk.toggled.connect(self.show_names_toggled.emit)
        ql.addWidget(self._show_names_chk)
        lay.addWidget(quick_box)

        # ── 手动编辑 ──
        edit_box = _make_section(tr("state_edit_section"))
        el = edit_box.layout()

        self._assign_chk = QCheckBox(tr("state_assign_drag_label"))
        self._assign_chk.setChecked(False)
        self._assign_chk.setToolTip(tr("state_assign_drag_label") + " — 再次点击退出")
        self._assign_chk.setStyleSheet(
            "QCheckBox { color: #e8eaed; font-size: 13px; font-weight: 600; padding: 6px; }"
            "QCheckBox:checked { color: #86efac; }"
        )
        self._assign_chk.toggled.connect(self._on_assign_toggled)
        el.addWidget(self._assign_chk)

        batch_row = QHBoxLayout()
        self._batch_btn = QPushButton(tr("state_batch_select_btn_short"))
        self._batch_btn.setCheckable(True)
        self._batch_btn.setStyleSheet(_PRIMARY_BTN_STYLE)
        self._batch_btn.setToolTip(tr("state_batch_select_tip") + "（再次点击退出）")
        self._batch_btn.toggled.connect(self._on_batch_toggled)
        batch_row.addWidget(self._batch_btn)

        self._batch_confirm_btn = QPushButton(tr("state_batch_confirm_btn_short"))
        self._batch_confirm_btn.setStyleSheet(
            "QPushButton { background: #22c55e; color: white; padding: 6px;"
            " border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background: #2ad66a; }"
        )
        self._batch_confirm_btn.clicked.connect(self.batch_create_state_confirmed.emit)
        batch_row.addWidget(self._batch_confirm_btn)
        el.addLayout(batch_row)
        lay.addWidget(edit_box)

        # ── 州列表（含搜索）──
        list_box = _make_section(tr("state_list_section"))

        self._state_search = QLineEdit()
        self._state_search.setPlaceholderText(tr("state_search_placeholder"))
        self._state_search.setStyleSheet(_LINEEDIT_STYLE)
        self._state_search.textChanged.connect(self._on_search_changed)
        list_box.layout().addWidget(self._state_search)

        self._state_list = QListWidget()
        self._state_list.setStyleSheet(_LIST_STYLE)
        self._state_list.setMinimumHeight(200)
        self._state_list.currentRowChanged.connect(self._on_state_list_clicked)
        list_box.layout().addWidget(self._state_list)
        lay.addWidget(list_box)

        # ── 选中州属性 ──
        info_box = _make_section(tr("state_props_section"))
        il = info_box.layout()

        name_row = QHBoxLayout()
        name_lbl = QLabel(tr("state_name_label"))
        name_lbl.setStyleSheet(_LABEL_STYLE)
        name_row.addWidget(name_lbl)
        self._state_name_edit = QLineEdit()
        self._state_name_edit.setStyleSheet(_LINEEDIT_STYLE)
        self._state_name_edit.editingFinished.connect(self._on_state_name_changed)
        name_row.addWidget(self._state_name_edit)
        il.addLayout(name_row)

        mp_row = QHBoxLayout()
        mp_lbl = QLabel(tr("state_manpower_label"))
        mp_lbl.setStyleSheet(_LABEL_STYLE)
        mp_row.addWidget(mp_lbl)
        self._state_manpower_spin = QSpinBox()
        self._state_manpower_spin.setRange(0, 100000000)
        self._state_manpower_spin.setSingleStep(10000)
        self._state_manpower_spin.setStyleSheet(_SPINBOX_STYLE)
        self._state_manpower_spin.valueChanged.connect(self._on_state_manpower_changed)
        mp_row.addWidget(self._state_manpower_spin)
        il.addLayout(mp_row)

        cat_row = QHBoxLayout()
        cat_lbl = QLabel(tr("state_category_label"))
        cat_lbl.setStyleSheet(_LABEL_STYLE)
        cat_row.addWidget(cat_lbl)
        self._state_category_combo = QComboBox()
        self._state_category_combo.setStyleSheet(_COMBOBOX_STYLE)
        self._state_category_combo.addItems(StateManager.CATEGORIES)
        self._state_category_combo.currentTextChanged.connect(self._on_state_category_changed)
        cat_row.addWidget(self._state_category_combo)
        il.addLayout(cat_row)

        detail_btn = QPushButton(tr("state_detail_btn"))
        detail_btn.setToolTip(tr("state_detail_btn_tip"))
        detail_btn.clicked.connect(self._on_state_detail_clicked)
        il.addWidget(detail_btn)

        # 重新分割州内省份 (数量可调)
        resplit_row = QHBoxLayout()
        resplit_lbl = QLabel(tr("state_resplit_count_label"))
        resplit_lbl.setStyleSheet(_LABEL_STYLE)
        resplit_row.addWidget(resplit_lbl)
        self._resplit_spin = QSpinBox()
        self._resplit_spin.setRange(1, 500)
        self._resplit_spin.setValue(10)
        self._resplit_spin.setStyleSheet(_SPINBOX_STYLE)
        self._resplit_spin.setToolTip(tr("state_resplit_count_tip"))
        resplit_row.addWidget(self._resplit_spin)
        il.addLayout(resplit_row)
        resplit_btn = QPushButton(tr("state_resplit_btn"))
        resplit_btn.setToolTip(tr("state_resplit_btn_tip"))
        resplit_btn.clicked.connect(self._on_resplit_clicked)
        il.addWidget(resplit_btn)

        # 删除当前州按钮 (危险操作, 用红色按钮 + 二次确认)
        delete_btn = QPushButton(tr("state_delete_btn"))
        delete_btn.setStyleSheet(
            "QPushButton { background: #b91c1c; color: white; padding: 6px;"
            " border-radius: 4px; font-weight: 600; }"
            "QPushButton:hover { background: #dc2626; }"
            "QPushButton:disabled { background: #4b5563; color: #9ca3af; }"
        )
        delete_btn.clicked.connect(self._on_state_delete_clicked)
        il.addWidget(delete_btn)
        self._state_delete_btn = delete_btn

        lay.addWidget(info_box)

        lay.addStretch()

    # ── 槽函数 ──
    def _on_auto_states(self) -> None:
        per_state = self._state_per_spin.value()
        self.auto_states_requested.emit(per_state)

    def _on_assign_toggled(self, checked: bool) -> None:
        """分配模式切换：文字变激活态 + 通知 controller。"""
        self._assign_chk.setText(
            tr("state_assign_drag_label_active") if checked
            else tr("state_assign_drag_label")
        )
        self.assign_mode_changed.emit(checked)

    def _on_batch_toggled(self, checked: bool) -> None:
        """框选建州切换：文字变激活态 + 通知 controller。"""
        self._batch_btn.setText(
            tr("state_batch_select_btn_short_active") if checked
            else tr("state_batch_select_btn_short")
        )
        self.batch_create_state_toggled.emit(checked)

    def _on_state_list_clicked(self, row: int) -> None:
        item = self._state_list.item(row)
        if item is not None:
            state_id = item.data(Qt.UserRole)
            if state_id is not None:
                self._current_state_id = int(state_id)
                # 重分割数量默认 = 该州当前省份数
                for sid, _name, count, _tag in self._state_items_cache:
                    if sid == state_id and count > 0:
                        self._resplit_spin.setValue(min(count, 500))
                        break
                self.state_selected.emit(state_id)

    def _on_state_name_changed(self) -> None:
        item = self._state_list.currentItem()
        if item is not None:
            state_id = item.data(Qt.UserRole)
            if state_id is not None:
                self.state_property_changed.emit(
                    state_id, "name", self._state_name_edit.text()
                )

    def _on_state_manpower_changed(self, value: int) -> None:
        item = self._state_list.currentItem()
        if item is not None:
            state_id = item.data(Qt.UserRole)
            if state_id is not None:
                self.state_property_changed.emit(state_id, "manpower", value)

    def _on_state_category_changed(self, text: str) -> None:
        item = self._state_list.currentItem()
        if item is not None:
            state_id = item.data(Qt.UserRole)
            if state_id is not None:
                self.state_property_changed.emit(state_id, "category", text)

    def _on_state_detail_clicked(self) -> None:
        if self._current_state_id > 0:
            self.state_detail_requested.emit(self._current_state_id)

    def _on_resplit_clicked(self) -> None:
        if self._current_state_id > 0:
            self.resplit_state_requested.emit(
                self._current_state_id, self._resplit_spin.value()
            )

    def _on_state_delete_clicked(self) -> None:
        if self._current_state_id <= 0:
            return
        from PyQt5.QtWidgets import QMessageBox
        ret = QMessageBox.question(
            self, tr("state_delete_confirm_title"),
            tr("state_delete_confirm_msg").format(sid=self._current_state_id),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ret == QMessageBox.Yes:
            self.state_delete_requested.emit(self._current_state_id)

    def _on_search_changed(self, text: str) -> None:
        """搜索框输入 → 持久化 + 重建可见列表。"""
        self._search_text = text.strip().lower()
        self._rebuild_state_list()

    def _rebuild_state_list(self) -> None:
        """根据 cache + search_text 重建可见列表项（保留 currentRow 选中）。"""
        self._state_list.blockSignals(True)
        prev_id = self._current_state_id
        self._state_list.clear()
        q = self._search_text
        for sid, name, count, tag in self._state_items_cache:
            label = _format_state_item(sid, name, count, tag)
            if q and q not in label.lower() and q not in str(sid):
                continue
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, sid)
            self._state_list.addItem(item)
            if sid == prev_id:
                self._state_list.setCurrentItem(item)
        self._state_list.blockSignals(False)

    # ── 公共更新方法 ──
    def update_state_list(self, states) -> None:
        """刷新 State 列表。
        兼容旧签名 (id, name, count) 和新签名 (id, name, count, owner_tag)。"""
        self._state_items_cache = []
        for it in states:
            if len(it) == 3:
                sid, name, count = it
                tag = ""
            else:
                sid, name, count, tag = it
            self._state_items_cache.append((sid, name, count, tag))
        self._rebuild_state_list()

    def update_state_info(self, name: str, manpower: int, category: str) -> None:
        """填充 State 属性字段"""
        self._state_name_edit.blockSignals(True)
        self._state_name_edit.setText(name)
        self._state_name_edit.blockSignals(False)

        self._state_manpower_spin.blockSignals(True)
        self._state_manpower_spin.setValue(manpower)
        self._state_manpower_spin.blockSignals(False)

        self._state_category_combo.blockSignals(True)
        idx = self._state_category_combo.findText(category)
        if idx >= 0:
            self._state_category_combo.setCurrentIndex(idx)
        self._state_category_combo.blockSignals(False)
