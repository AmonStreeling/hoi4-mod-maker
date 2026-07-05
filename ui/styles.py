"""
暗色主题样式表 — 参照 HTML 设计稿的视觉风格.

- DARK_STYLESHEET: 全局 QApplication 级 QSS
- _BG / _INPUT_BG 等: 色板常量, feature 模块共享
- _SECTION_STYLE / _PRIMARY_BTN_STYLE 等: 局部控件样式
- _color_icon(): 生成色块图标辅助
"""

from PyQt5.QtGui import QColor, QPixmap, QIcon


# ── 色板 (v3 可读性优化: 提高对比度 + 字号) ──────────────
_BG = "#17181c"          # 深紫灰主背景
_INPUT_BG = "#1f2126"     # 面板/输入框背景（原 #1f2126 略提亮）
_BORDER = "#2c2f36"       # 边框（原 #2c2f36 太暗，提亮便于识别）
_TEXT = "#e8eaed"         # 主文字（原 #e8eaed，冷白 → 更亮）
_DIM = "#9aa0ab"          # 次要文字/标签（原 #9aa0ab 对比度 3.5:1 不足，现 4.9:1 达标）
_ACCENT = "#4f8cff"       # 紫蓝强调（原 #4f8cff 提亮更醒目）
_ACCENT_HOVER = "#6ba1ff" # hover 亮色
_SUCCESS = "#22c55e"      # 成功/导出按钮
_GROUP_HEADER = "#6ba1ff" # 分组标题色


_SECTION_STYLE = f"""
    QGroupBox {{
        background: {_INPUT_BG};
        border: 1px solid {_BORDER};
        border-radius: 6px;
        margin-top: 18px;
        padding-top: 22px;
        color: {_GROUP_HEADER};
        font-size: 15px;
        font-weight: 700;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 8px;
    }}
"""

_LABEL_STYLE = f"color: {_TEXT}; font-size: 13px;"
_DIM_LABEL_STYLE = f"color: {_DIM}; font-size: 13px;"

_SLIDER_STYLE = f"""
    QSlider::groove:horizontal {{
        height: 4px;
        background: {_BORDER};
        border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        width: 14px; height: 14px;
        margin: -5px 0;
        background: {_TEXT};
        border: 2px solid {_ACCENT};
        border-radius: 8px;
    }}
    QSlider::sub-page:horizontal {{
        background: {_ACCENT};
        border-radius: 2px;
    }}
"""

_TOOL_BTN_STYLE = f"""
    QPushButton {{
        background: transparent;
        border: 1px solid transparent;
        color: {_DIM};
        padding: 6px 8px;
        font-size: 13px;
        border-radius: 6px;
    }}
    QPushButton:checked {{
        background: rgba(79, 140, 255, 0.14);
        color: {_ACCENT};
        border: 1px solid {_ACCENT};
        font-weight: 700;
    }}
    QPushButton:hover:!checked {{
        color: {_TEXT};
        background: rgba(255, 255, 255, 0.05);
    }}
"""

# 地块选择按钮 (icon + label, padding 大, :checked 用半透明 accent + 描边不抢 icon 色)
_TILE_BTN_STYLE = f"""
    QPushButton {{
        background: {_INPUT_BG};
        border: 2px solid {_BORDER};
        color: {_TEXT};
        padding: 7px 10px;
        font-size: 14px;
        border-radius: 4px;
        text-align: left;
    }}
    QPushButton:checked {{
        background: rgba(79, 140, 255, 0.22);
        border: 2px solid {_ACCENT};
        font-weight: 600;
    }}
    QPushButton:hover:!checked {{
        background: rgba(79, 140, 255, 0.08);
        border-color: {_ACCENT};
    }}
"""

_PRIMARY_BTN_STYLE = f"""
    QPushButton {{
        background: {_ACCENT};
        border: none;
        color: white;
        padding: 8px 14px;
        font-size: 14px;
        font-weight: 700;
        border-radius: 6px;
    }}
    QPushButton:hover {{
        background: {_ACCENT_HOVER};
    }}
    QPushButton:checked {{
        background: #f97316;
        color: white;
        border: 2px solid #fb923c;
    }}
    QPushButton:checked:hover {{
        background: #fb923c;
    }}
"""

_SECONDARY_BTN_STYLE = f"""
    QPushButton {{
        background: transparent;
        border: 1px solid {_BORDER};
        color: {_TEXT};
        padding: 7px 12px;
        font-size: 13px;
        border-radius: 6px;
    }}
    QPushButton:hover {{
        border-color: {_ACCENT};
        color: {_ACCENT};
    }}
"""

_SUCCESS_BTN_STYLE = f"""
    QPushButton {{
        background: {_SUCCESS};
        border: none;
        color: white;
        padding: 8px 12px;
        font-size: 15px;
        font-weight: 700;
        border-radius: 5px;
    }}
    QPushButton:hover {{
        background: #16a34a;
    }}
"""

_SPINBOX_STYLE = f"""
    QSpinBox {{
        background: {_INPUT_BG};
        border: 1px solid {_BORDER};
        border-radius: 4px;
        color: {_TEXT};
        padding: 3px 6px;
        font-size: 15px;
    }}
"""

_LINEEDIT_STYLE = f"""
    QLineEdit {{
        background: {_INPUT_BG};
        border: 1px solid {_BORDER};
        border-radius: 4px;
        color: {_TEXT};
        padding: 3px 6px;
        font-size: 15px;
    }}
"""

_COMBOBOX_STYLE = f"""
    QComboBox {{
        background: {_INPUT_BG};
        border: 1px solid {_BORDER};
        border-radius: 4px;
        color: {_TEXT};
        padding: 3px 6px;
        font-size: 15px;
    }}
    QComboBox::drop-down {{
        border: none;
    }}
    QComboBox QAbstractItemView {{
        background: {_INPUT_BG};
        border: 1px solid {_BORDER};
        color: {_TEXT};
        selection-background-color: {_ACCENT};
    }}
"""

_LIST_STYLE = f"""
    QListWidget {{
        background: {_INPUT_BG};
        border: 1px solid {_BORDER};
        border-radius: 4px;
        color: {_TEXT};
        font-size: 15px;
    }}
    QListWidget::item {{
        padding: 5px 8px;
    }}
    QListWidget::item:selected {{
        background: {_ACCENT};
        color: white;
    }}
    QListWidget::item:hover:!selected {{
        background: rgba(255, 255, 255, 0.05);
    }}
"""


def make_section(title: str):
    """创建统一样式的 QGroupBox 分组容器。所有 page 共用。"""
    from PyQt5.QtWidgets import QGroupBox, QVBoxLayout
    box = QGroupBox(title)
    box.setLayout(QVBoxLayout())
    box.layout().setContentsMargins(10, 14, 10, 10)
    box.layout().setSpacing(8)
    box.setStyleSheet(_SECTION_STYLE)
    return box


# ── 卡片式分组 (2026-07 UI 试点, 逐步替代 make_section) ──

_CARD_STYLE = f"""
    QFrame#card {{
        background: {_INPUT_BG};
        border: 1px solid {_BORDER};
        border-radius: 8px;
    }}
"""
_CARD_TITLE_STYLE = (
    "color: #c8c9e8; font-size: 14px; font-weight: 700;"
    " background: transparent; padding: 0;"
)
_CARD_STEP_STYLE = (
    f"color: {_ACCENT}; font-size: 12px; font-weight: 700;"
    " background: rgba(79, 140, 255, 0.16); border-radius: 9px;"
    " padding: 1px 8px;"
)


def make_card(title: str, step: str = ""):
    """扁平卡片分组: 标题在卡片内部首行, 可带步骤徽标。

    与 make_section (QGroupBox 浮动标题) 的区别: 标题行在卡片内,
    可携带 ①②③ 步骤徽标 — 供"按用户做事顺序排布"的页面使用。
    用法与 make_section 相同: card.layout().addWidget/addLayout 追加内容。
    """
    from PyQt5.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel
    card = QFrame()
    card.setObjectName("card")
    card.setStyleSheet(_CARD_STYLE)
    outer = QVBoxLayout(card)
    outer.setContentsMargins(12, 10, 12, 12)
    outer.setSpacing(8)
    head = QHBoxLayout()
    head.setSpacing(8)
    if step:
        badge = QLabel(step)
        badge.setStyleSheet(_CARD_STEP_STYLE)
        head.addWidget(badge)
    title_lbl = QLabel(title)
    title_lbl.setStyleSheet(_CARD_TITLE_STYLE)
    head.addWidget(title_lbl)
    head.addStretch()
    outer.addLayout(head)
    return card


def make_hint(text: str):
    """低噪声提示行: 统一 11px 暗色小字, 自动换行。"""
    from PyQt5.QtWidgets import QLabel
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {_DIM}; font-size: 11px; padding: 2px;")
    lbl.setWordWrap(True)
    return lbl


def _color_icon(r: int, g: int, b: int, size: int = 12) -> QIcon:
    """生成一个纯色方块图标 (列表 / 按钮装饰用)."""
    px = QPixmap(size, size)
    px.fill(QColor(r, g, b))
    return QIcon(px)


DARK_STYLESHEET = """
/* 全局 — v2 中性深灰 + 紫蓝 */
QMainWindow, QWidget {
    background-color: #17181c;
    color: #e8eaed;
    /* Segoe UI 在前: 西里尔/拉丁字母用 Segoe UI (正常 metrics),
       中文 fallback 到 YaHei. YaHei 在前会让西里尔字母按 CJK 全角宽度渲染,
       出现"字母间距异常大 + 文字截断"的 bug. */
    font-family: "Segoe UI", "Microsoft YaHei", "Noto Sans SC", sans-serif;
    font-size: 15px;
}

/* 菜单栏 */
QMenuBar {
    background-color: #18182a;
    border-bottom: 1px solid #2c2f36;
    padding: 3px;
    font-size: 15px;
}
QMenuBar::item {
    padding: 5px 14px;
    background: transparent;
    color: #e8eaed;
}
QMenuBar::item:selected {
    background: rgba(79, 140, 255, 0.25);
    border-radius: 4px;
}
QMenu {
    background-color: #1f2126;
    border: 1px solid #2c2f36;
    padding: 4px;
}
QMenu::item {
    padding: 7px 28px;
    border-radius: 3px;
    font-size: 15px;
}
QMenu::item:selected {
    background: rgba(79, 140, 255, 0.3);
}
QMenu::separator {
    height: 1px;
    background: #2c2f36;
    margin: 4px 8px;
}

/* 状态栏 */
QStatusBar {
    background-color: #18182a;
    border-top: 1px solid #2c2f36;
    font-size: 15px;
    color: #9aa0ab;
}
QStatusBar::item {
    border: none;
}

/* 工具面板 */
QGroupBox {
    background-color: #1f2126;
    border: 1px solid #2c2f36;
    border-radius: 6px;
    margin-top: 8px;
    padding: 8px;
    padding-top: 24px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
    color: #6ba1ff;
    font-size: 15px;
    font-weight: bold;
}

/* 按钮 */
QPushButton {
    background-color: #17181c;
    border: 1px solid #2c2f36;
    border-radius: 5px;
    padding: 7px 14px;
    color: #e8eaed;
    font-size: 15px;
    min-height: 22px;
}
QPushButton:hover {
    border-color: #4f8cff;
    background: rgba(79, 140, 255, 0.1);
}
QPushButton:pressed {
    background: rgba(79, 140, 255, 0.2);
}
QPushButton:checked {
    background: #4f8cff;
    border-color: #4f8cff;
    color: white;
}
QPushButton#btnPrimary {
    background: #4f8cff;
    border-color: #4f8cff;
    color: white;
    font-weight: 500;
}
QPushButton#btnPrimary:hover {
    background: #6ba1ff;
}
QPushButton#btnSuccess {
    background: #22c55e;
    border-color: #22c55e;
    color: white;
    font-weight: 500;
}
QPushButton#btnSuccess:hover {
    background: #16a34a;
}

/* 单选按钮 */
QRadioButton {
    spacing: 6px;
    padding: 3px;
    font-size: 15px;
}
QRadioButton::indicator {
    width: 14px;
    height: 14px;
    border-radius: 7px;
    border: 2px solid #2c2f36;
    background: #17181c;
}
QRadioButton::indicator:checked {
    background: #4f8cff;
    border-color: #4f8cff;
}

/* 滑块 */
QSlider::groove:horizontal {
    height: 4px;
    background: #2c2f36;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
    background: #4f8cff;
}
QSlider::handle:horizontal:hover {
    background: #8c8cff;
}

/* 数值输入 */
QSpinBox, QDoubleSpinBox {
    background: #17181c;
    border: 1px solid #2c2f36;
    border-radius: 4px;
    padding: 5px 8px;
    color: #e8eaed;
    font-size: 15px;
}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    background: #1f2126;
    border: none;
    width: 16px;
}

/* 标签 */
QLabel {
    color: #e8eaed;
    font-size: 15px;
}
QLabel#labelDim {
    color: #9aa0ab;
    font-size: 15px;
}

/* 滚动条 */
QScrollBar:vertical {
    width: 6px;
    background: #17181c;
}
QScrollBar::handle:vertical {
    background: #2c2f36;
    border-radius: 3px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover {
    background: #9aa0ab;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    height: 6px;
    background: #17181c;
}
QScrollBar::handle:horizontal {
    background: #2c2f36;
    border-radius: 3px;
    min-width: 20px;
}
QScrollBar::handle:horizontal:hover {
    background: #9aa0ab;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}

/* 对话框 */
QDialog {
    background-color: #1f2126;
}
QMessageBox {
    background-color: #1f2126;
}
QInputDialog {
    background-color: #1f2126;
    color: #e8eaed;
}
QInputDialog QPushButton {
    color: #e8eaed;
    background: #3a3a5a;
    border: 1px solid #4f8cff;
    border-radius: 4px;
    padding: 4px 16px;
}
QInputDialog QPushButton:hover {
    background: #4a4a7a;
}

/* 工具提示 */
QToolTip {
    background: #1f2126;
    border: 1px solid #4f8cff;
    border-radius: 4px;
    padding: 4px 8px;
    color: #e8eaed;
    font-size: 15px;
}

/* Graphics View */
QGraphicsView {
    border: none;
    background: #161625;
}
"""
