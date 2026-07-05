"""
模式操作提示条 — 每个编辑模式首次切换时显示一行操作说明。
"""
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from PyQt5.QtCore import Qt, QSettings

from ui.i18n import tr

_ACCENT = "#4f8cff"
_HINT_BG = "rgba(79, 140, 255, 0.10)"
_BORDER = "#2c2f36"
_TEXT = "#e8eaed"
_DIM = "#9aa0ab"

_SETTINGS_GROUP = "ModeHints"


class ModeHintBar(QWidget):
    """可关闭的模式提示条，自适应高度。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(32)
        self.setStyleSheet(f"""
            ModeHintBar {{
                background: {_HINT_BG};
                border-bottom: 1px solid {_BORDER};
            }}
        """)
        self._settings = QSettings("HOI4MapMaker", _SETTINGS_GROUP)
        self._current_mode = ""

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 6, 8, 6)
        lay.setSpacing(8)

        self._icon = QLabel("💡")
        self._icon.setFixedWidth(20)
        self._icon.setStyleSheet("font-size: 14px; background: transparent;")
        lay.addWidget(self._icon, 0, Qt.AlignTop)

        self._text = QLabel()
        self._text.setStyleSheet(f"color: {_TEXT}; font-size: 13px; background: transparent;")
        self._text.setWordWrap(True)
        lay.addWidget(self._text, 1)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(24, 24)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {_DIM};
                font-size: 14px;
            }}
            QPushButton:hover {{
                color: {_TEXT};
            }}
        """)
        close_btn.clicked.connect(self._dismiss)
        lay.addWidget(close_btn, 0, Qt.AlignTop)

        self.hide()

    def on_mode_changed(self, mode: str) -> None:
        """模式切换时调用，首次显示提示。"""
        self._current_mode = mode
        hint_key = f"hint_mode_{mode}"
        hint_text = tr(hint_key)

        # key 没翻译 = 没有提示
        if hint_text == hint_key:
            self.hide()
            return

        # 检查是否已经看过
        if self._settings.value(f"seen_{mode}", False, type=bool):
            self.hide()
            return

        self._text.setText(hint_text)
        self.show()

    def _dismiss(self) -> None:
        """关闭并记录已看过。"""
        if self._current_mode:
            self._settings.setValue(f"seen_{self._current_mode}", True)
        self.hide()

    @staticmethod
    def reset_all_hints() -> None:
        """重置所有模式提示（帮助菜单调用）。"""
        settings = QSettings("HOI4MapMaker", _SETTINGS_GROUP)
        settings.clear()
