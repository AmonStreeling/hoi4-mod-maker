"""province feature 页面 — 独立 QWidget, 不依赖 ToolPanel.

默认点击 = 查看省份数据
合并/扩张 需要手动开启，操作完自动关闭回到查看模式。
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QIntValidator
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QLabel, QLineEdit,
)

from ui.styles import (
    make_section as _make_section,
    _DIM, _ACCENT, _BORDER, _SECTION_STYLE, _LABEL_STYLE, _DIM_LABEL_STYLE,
    _SECONDARY_BTN_STYLE, _LINEEDIT_STYLE,
)
from ui.i18n import tr

# 模式激活时的按钮样式（醒目橙色）
_ACTIVE_MODE_BTN_STYLE = """
    QPushButton {
        background: #e67e22;
        border: 2px solid #f39c12;
        color: white;
        padding: 7px 12px;
        font-size: 13px;
        font-weight: bold;
        border-radius: 5px;
    }
    QPushButton:hover {
        background: #f39c12;
    }
"""

# 模式激活时的提示样式（橙色背景）
_ACTIVE_HINT_STYLE = """
    color: white;
    font-size: 13px;
    font-weight: bold;
    padding: 10px;
    background: rgba(230, 126, 34, 0.25);
    border: 1px solid rgba(230, 126, 34, 0.5);
    border-radius: 4px;
"""

_NORMAL_HINT_STYLE = f"color: {_DIM}; font-size: 12px; padding: 8px;"




class ProvincePage(QWidget):
    """省份编辑页面."""

    # 输出信号
    split_mode_toggled = pyqtSignal(bool)
    lasso_province_toggled = pyqtSignal(bool)
    merge_mode_toggled = pyqtSignal(bool)
    find_province_requested = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(10)

        # ── 省份查找（顶部）──
        find_row = QHBoxLayout()
        find_row.setSpacing(4)
        find_icon = QLabel("🔍")
        find_icon.setStyleSheet(f"color: {_DIM}; font-size: 14px; padding: 0 4px;")
        find_row.addWidget(find_icon)

        self._find_input = QLineEdit()
        self._find_input.setPlaceholderText(tr("province_search_placeholder"))
        self._find_input.setStyleSheet(_LINEEDIT_STYLE)
        self._find_input.setValidator(QIntValidator(1, 99999999, self))
        self._find_input.returnPressed.connect(self._on_find_clicked)
        find_row.addWidget(self._find_input, stretch=1)

        self._find_btn = QPushButton(tr("province_btn_find"))
        self._find_btn.setStyleSheet(_SECONDARY_BTN_STYLE)
        self._find_btn.setToolTip(tr("province_btn_find_tip"))
        self._find_btn.clicked.connect(self._on_find_clicked)
        find_row.addWidget(self._find_btn)
        lay.addLayout(find_row)

        # 提示 (动态更新)
        self._province_hint = QLabel(tr("province_hint_default"))
        self._province_hint.setStyleSheet(f"color: {_DIM}; font-size: 12px; padding: 8px;")
        self._province_hint.setWordWrap(True)
        lay.addWidget(self._province_hint)

        # ── 省份信息（单行紧凑） ──
        self._prov_info_label = QLabel(tr("province_info_compact_default"))
        self._prov_info_label.setStyleSheet(
            f"color: #aaa; font-size: 11px; padding: 4px 8px;"
            f" background: #1a1a22; border: 1px solid #2a2a3c; border-radius: 4px;"
        )
        lay.addWidget(self._prov_info_label)

        # ── 省份统计 ──
        self._stats_label = QLabel()
        self._stats_label.setWordWrap(True)
        self._stats_label.setStyleSheet(f"color: {_DIM}; font-size: 12px; padding: 4px 8px;")
        lay.addWidget(self._stats_label)

        # ── 工具按钮（横排） ──
        tools_box = _make_section(tr("province_section_tools"))
        tools_row = QHBoxLayout()

        self._merge_btn = QPushButton(tr("province_btn_merge"))
        self._merge_btn.setCheckable(True)
        self._merge_btn.setStyleSheet(_SECONDARY_BTN_STYLE)
        self._merge_btn.setToolTip(tr("province_btn_merge_tip"))
        tools_row.addWidget(self._merge_btn)

        self._expand_btn = QPushButton(tr("province_btn_expand"))
        self._expand_btn.setCheckable(True)
        self._expand_btn.setStyleSheet(_SECONDARY_BTN_STYLE)
        self._expand_btn.setToolTip(tr("province_btn_expand_tip"))
        tools_row.addWidget(self._expand_btn)

        self._split_btn = QPushButton(tr("province_btn_split"))
        self._split_btn.setCheckable(True)
        self._split_btn.setStyleSheet(_SECONDARY_BTN_STYLE)
        self._split_btn.setToolTip(tr("province_btn_split_tip"))
        tools_row.addWidget(self._split_btn)

        tools_box.layout().addLayout(tools_row)
        lay.addWidget(tools_box)

        # ── 信号连接 ──
        self._merge_btn.toggled.connect(self._on_merge_toggled)
        self._expand_btn.toggled.connect(self._on_expand_toggled)
        self._split_btn.toggled.connect(self._on_split_toggled)

        lay.addStretch()

    # ── 槽函数 ──
    def _clear_other_modes(self, *keep: QPushButton) -> None:
        """关闭除 keep 之外的所有模式按钮。"""
        for btn in (self._merge_btn, self._expand_btn, self._split_btn):
            if btn not in keep and btn.isChecked():
                btn.setChecked(False)

    def _on_merge_toggled(self, on: bool) -> None:
        if on:
            self._clear_other_modes(self._merge_btn)
        self.merge_mode_toggled.emit(on)
        self._update_mode_visuals()

    def _on_expand_toggled(self, on: bool) -> None:
        if on:
            self._clear_other_modes(self._expand_btn)
        self.lasso_province_toggled.emit(on)
        self._update_mode_visuals()

    def _on_split_toggled(self, on: bool) -> None:
        if on:
            self._clear_other_modes(self._split_btn)
        self.split_mode_toggled.emit(on)
        self._update_mode_visuals()

    def _on_find_clicked(self) -> None:
        txt = self._find_input.text().strip()
        if not txt:
            return
        try:
            pid = int(txt)
        except ValueError:
            return
        if pid <= 0:
            return
        self.find_province_requested.emit(pid)
        # 重置输入框红色边框（如果上次查无）
        self._find_input.setStyleSheet(_LINEEDIT_STYLE)

    def mark_find_not_found(self) -> None:
        """外部 handler 在 ID 不存在时调用 — 输入框边框变红。"""
        self._find_input.setStyleSheet(
            _LINEEDIT_STYLE + "QLineEdit { border: 1px solid #ef4444; }"
        )

    def _update_mode_visuals(self) -> None:
        """根据当前激活模式更新按钮样式和提示条。"""
        merging = self._merge_btn.isChecked()
        expanding = self._expand_btn.isChecked()
        splitting = self._split_btn.isChecked()

        # 按钮样式：激活时变橙色
        for btn, active in [
            (self._merge_btn, merging),
            (self._expand_btn, expanding),
            (self._split_btn, splitting),
        ]:
            btn.setStyleSheet(_ACTIVE_MODE_BTN_STYLE if active else _SECONDARY_BTN_STYLE)

        # 提示条
        if merging:
            self._province_hint.setText(tr("province_hint_merge"))
            self._province_hint.setStyleSheet(_ACTIVE_HINT_STYLE)
        elif expanding:
            self._province_hint.setText(tr("province_hint_expand"))
            self._province_hint.setStyleSheet(_ACTIVE_HINT_STYLE)
        elif splitting:
            self._province_hint.setText(tr("province_hint_split"))
            self._province_hint.setStyleSheet(_ACTIVE_HINT_STYLE)
        else:
            self._province_hint.setText(tr("province_hint_default"))
            self._province_hint.setStyleSheet(_NORMAL_HINT_STYLE)

    # ── 公共更新方法 ──
    def update_province_info(
        self, pid: int, ptype: str, terrain: str, pixels: int, coastal: bool
    ) -> None:
        """更新省份信息面板（单行紧凑格式，加字段标签）"""
        parts = [
            f"ID: {pid}",
            f"{tr('province_info_type')}: {ptype}",
            f"{tr('province_info_terrain')}: {terrain}",
            f"{pixels}px",
        ]
        if coastal:
            parts.append(tr("province_info_coastal"))
        self._prov_info_label.setText(" | ".join(parts))

    def update_province_gaps(self, gap_ids: list[int]) -> None:
        """更新省份 ID 空洞提示。"""
        if not gap_ids:
            self._stats_label.setText("")
            self._stats_label.setStyleSheet(f"color: {_DIM}; font-size: 12px; padding: 4px 8px;")
            return

        if len(gap_ids) <= 10:
            ids_str = ", ".join(str(i) for i in gap_ids)
        else:
            ids_str = ", ".join(str(i) for i in gap_ids[:10]) + f" ... 共 {len(gap_ids)} 个"

        self._stats_label.setText(
            f"缺失省份 ID: {ids_str}\n需要用切割或增量生成补回"
        )
        self._stats_label.setStyleSheet(
            "color: #f59e0b; font-size: 12px; font-weight: bold; padding: 8px;"
            " background: rgba(245, 158, 11, 0.12); border: 1px solid rgba(245, 158, 11, 0.3);"
            " border-radius: 4px;"
        )
