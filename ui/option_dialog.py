"""
OptionChooserDialog — "说人话的选择题"对话框。

治"按钮太多不知道点哪个": 页面只留一个入口按钮, 点开后每个选项是
一张大卡片 (标题 + 一句什么时候用它的说明), 点卡片即选定。

用法:
    key = OptionChooserDialog.choose(parent, "生成 / 优化高度", [
        ("realistic", "从零生成真实地势", "我还没画高度..."),
        ("refine", "保形精修", "我已画好哪里高哪里低..."),
    ])
    if key == "realistic": ...
"""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton,
)

from ui.i18n import tr
from ui.styles import _BORDER, _TEXT, _DIM, _ACCENT, _INPUT_BG


_CARD_STYLE = f"""
    QPushButton {{
        background: {_INPUT_BG};
        border: 1px solid {_BORDER};
        border-radius: 6px;
        padding: 12px 14px;
        text-align: left;
        color: {_TEXT};
    }}
    QPushButton:hover {{
        border-color: {_ACCENT};
        background: rgba(108, 108, 240, 0.12);
    }}
"""


class OptionChooserDialog(QDialog):
    """大卡片单选对话框。选中的 key 存 self.selected。"""

    def __init__(self, parent, title: str,
                 options: list[tuple[str, str, str]]) -> None:
        super().__init__(parent)
        self.selected: str | None = None
        self.setWindowTitle(title)
        self.setMinimumWidth(440)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        for key, name, desc in options:
            btn = QPushButton()
            btn.setStyleSheet(_CARD_STYLE)
            btn.setMinimumHeight(64)
            # 富文本布局: 标题一行 + 说明一行 (说明用暗色小字)
            inner = QVBoxLayout(btn)
            inner.setContentsMargins(12, 8, 12, 8)
            inner.setSpacing(3)
            name_lbl = QLabel(f"<b>{name}</b>")
            name_lbl.setStyleSheet("background: transparent; font-size: 14px;")
            name_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            desc_lbl = QLabel(desc)
            desc_lbl.setWordWrap(True)
            desc_lbl.setStyleSheet(
                f"background: transparent; color: {_DIM}; font-size: 12px;")
            desc_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            inner.addWidget(name_lbl)
            inner.addWidget(desc_lbl)
            btn.clicked.connect(
                lambda _checked=False, k=key: self._pick(k))
            lay.addWidget(btn)

        cancel = QPushButton(tr("btn_cancel"))
        cancel.clicked.connect(self.reject)
        lay.addWidget(cancel, alignment=Qt.AlignmentFlag.AlignRight)

    def _pick(self, key: str) -> None:
        self.selected = key
        self.accept()

    @staticmethod
    def choose(parent, title: str,
               options: list[tuple[str, str, str]]) -> str | None:
        """弹出对话框, 返回选中的 key; 取消返回 None。

        parent 可以传任意控件 (如侧栏页面) — 内部取其顶层窗口做锚点,
        并显式居中: 直接用侧栏小控件当父级会让对话框弹在奇怪的位置。
        """
        anchor = parent.window() if parent is not None else None
        dlg = OptionChooserDialog(anchor, title, options)
        dlg.adjustSize()
        if anchor is not None:
            dlg.move(anchor.frameGeometry().center() - dlg.rect().center())
        dlg.exec_()
        return dlg.selected
