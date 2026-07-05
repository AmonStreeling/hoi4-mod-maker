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

from typing import Callable

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton, QFrame,
)

from ui.i18n import tr
from ui.styles import _BORDER, _TEXT, _DIM, _ACCENT, _INPUT_BG

# 卡片用 QFrame 而不是 QPushButton: QPushButton 的高度不会跟随内部
# 换行文字长高（文字被裁掉）, QFrame + 布局能正确按内容计算高度。
_CARD_STYLE = f"""
    QFrame#optionCard {{
        background: {_INPUT_BG};
        border: 1px solid {_BORDER};
        border-radius: 6px;
    }}
    QFrame#optionCard:hover {{
        border: 1px solid {_ACCENT};
        background: rgba(79, 140, 255, 0.12);
    }}
"""


class _OptionCard(QFrame):
    """一张可点击的选项卡片: 标题 + 换行说明。"""

    def __init__(self, key: str, name: str, desc: str,
                 on_pick: Callable[[str], None]) -> None:
        super().__init__()
        self._key = key
        self._on_pick = on_pick
        self.setObjectName("optionCard")
        self.setStyleSheet(_CARD_STYLE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 10)
        v.setSpacing(4)

        name_lbl = QLabel(name)
        name_lbl.setStyleSheet(
            f"background: transparent; color: {_TEXT};"
            " font-size: 14px; font-weight: 700;")
        v.addWidget(name_lbl)

        desc_lbl = QLabel(desc)
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet(
            f"background: transparent; color: {_DIM}; font-size: 12px;")
        v.addWidget(desc_lbl)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_pick(self._key)
        super().mouseReleaseEvent(event)


class OptionChooserDialog(QDialog):
    """大卡片单选对话框。选中的 key 存 self.selected。"""

    def __init__(self, parent, title: str,
                 options: list[tuple[str, str, str]]) -> None:
        super().__init__(parent)
        self.selected: str | None = None
        self.setWindowTitle(title)
        # 固定宽度: 说明文字在已知宽度下换行, 高度才能算对
        self.setFixedWidth(460)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        for key, name, desc in options:
            lay.addWidget(_OptionCard(key, name, desc, self._pick))

        cancel = QPushButton(tr("btn_cancel"))
        cancel.clicked.connect(self.reject)
        lay.addWidget(cancel, alignment=Qt.AlignmentFlag.AlignRight)

        # 高度钉死为"宽度 460 时的内容高度": 不给布局留可分配的多余空间,
        # 否则卡片之间会被拉出大空隙; heightForWidth 才能算对换行文字的高度
        lay.activate()
        if lay.hasHeightForWidth():
            self.setFixedHeight(lay.heightForWidth(self.width()))
        else:
            self.setFixedHeight(self.sizeHint().height())

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
