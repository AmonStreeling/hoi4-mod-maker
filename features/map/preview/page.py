"""
预览页 — 侧栏面板: 刷新按钮 + 游戏目录状态。

页面只发信号, 不直接碰画布 (与其他 page 一致):
- refresh_requested: 用户点了"刷新预览"
- game_dir_changed(str): 用户选择了新的游戏目录
"""

from __future__ import annotations

import os

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QFileDialog, QCheckBox,
)

from services.game_assets import get_default_assets
from ui.i18n import tr
from ui.styles import _SECTION_STYLE, _SUCCESS_BTN_STYLE, _DIM


class PreviewPage(QWidget):
    refresh_requested = pyqtSignal()
    game_dir_changed = pyqtSignal(str)
    political_toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        title = QLabel(tr("preview_page_title"))
        title.setStyleSheet(_SECTION_STYLE)
        layout.addWidget(title)

        desc = QLabel(tr("preview_page_desc"))
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {_DIM}; font-size: 12px;")
        layout.addWidget(desc)

        self._refresh_btn = QPushButton(tr("preview_refresh_btn"))
        self._refresh_btn.setStyleSheet(_SUCCESS_BTN_STYLE)
        self._refresh_btn.clicked.connect(self.refresh_requested.emit)
        layout.addWidget(self._refresh_btn)

        hint = QLabel(tr("preview_refresh_hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {_DIM}; font-size: 11px;")
        layout.addWidget(hint)

        # 政治视图: 底图上叠加国家势力色 (需要先建国家并分配领土)
        self._political_chk = QCheckBox(tr("preview_political_label"))
        self._political_chk.toggled.connect(self.political_toggled.emit)
        layout.addWidget(self._political_chk)
        political_hint = QLabel(tr("preview_political_hint"))
        political_hint.setWordWrap(True)
        political_hint.setStyleSheet(f"color: {_DIM}; font-size: 11px;")
        layout.addWidget(political_hint)

        # ── 游戏目录状态 ──
        dir_title = QLabel(tr("preview_game_dir_title"))
        dir_title.setStyleSheet(_SECTION_STYLE)
        layout.addWidget(dir_title)

        self._dir_label = QLabel("")
        self._dir_label.setWordWrap(True)
        self._dir_label.setStyleSheet("font-size: 11px;")
        layout.addWidget(self._dir_label)

        self._choose_dir_btn = QPushButton(tr("preview_choose_dir_btn"))
        self._choose_dir_btn.clicked.connect(self._on_choose_dir)
        layout.addWidget(self._choose_dir_btn)

        layout.addStretch()
        self.refresh_dir_status()

    def refresh_dir_status(self) -> None:
        """更新游戏目录状态显示。"""
        assets = get_default_assets()
        if assets.available():
            self._dir_label.setText(
                tr("preview_game_dir_found").format(path=assets.install_dir))
            self._dir_label.setStyleSheet("color: #86EFAC; font-size: 11px;")
        else:
            self._dir_label.setText(tr("preview_game_dir_missing"))
            self._dir_label.setStyleSheet("color: #FCA5A5; font-size: 11px;")

    def _on_choose_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, tr("preview_choose_dir_title"))
        if not path:
            return
        if not os.path.isfile(os.path.join(
                path, "common", "terrain", "00_terrain.txt")):
            self._dir_label.setText(tr("preview_game_dir_invalid"))
            self._dir_label.setStyleSheet("color: #FCA5A5; font-size: 11px;")
            return
        self.game_dir_changed.emit(path)
        self.refresh_dir_status()
