# -*- coding: utf-8 -*-
"""视觉方案 mockup — 同一 LandPage 套不同主题出图。用法: py -3.10 本文件 A|B"""
import sys

sys.path.insert(0, ".")
THEME = sys.argv[1] if len(sys.argv) > 1 else "A"

from PyQt5.QtWidgets import QApplication

app = QApplication([])
from PyQt5.QtGui import QFont
_f = QFont("Segoe UI", 9)
_f.setFamilies(["Segoe UI", "Microsoft YaHei", "Noto Sans SC"])
app.setFont(_f)

import ui.styles as S

if THEME == "A":
    # ── 军事图房: 炭黑 + 羊皮纸 + 黄铜 ──
    BG, CARD, BORDER = "#16171a", "#1e1f24", "#3d3a2e"
    TEXT, DIM, ACCENT, ACCENT_TXT = "#e8e2d0", "#a89f88", "#c9a45c", "#1c1708"
else:
    # ── 现代专业工具: 中性深灰 + 冷静蓝 ──
    BG, CARD, BORDER = "#17181c", "#1f2126", "#2c2f36"
    TEXT, DIM, ACCENT, ACCENT_TXT = "#e8eaed", "#9aa0ab", "#4f8cff", "#ffffff"

R = "8px"

S._BG, S._INPUT_BG, S._BORDER = BG, CARD, BORDER
S._TEXT, S._DIM, S._ACCENT = TEXT, DIM, ACCENT

S._LABEL_STYLE = f"color: {TEXT}; font-size: 13px; background: transparent;"
S._DIM_LABEL_STYLE = f"color: {DIM}; font-size: 13px; background: transparent;"
S._SLIDER_STYLE = f"""
    QSlider::groove:horizontal {{
        height: 4px; background: {BORDER}; border-radius: 2px;
    }}
    QSlider::sub-page:horizontal {{
        background: {ACCENT}; border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        width: 14px; height: 14px; margin: -5px 0;
        background: {TEXT}; border: 2px solid {ACCENT}; border-radius: 8px;
    }}
"""
_BTN_BASE = (
    f"border-radius: 6px; padding: 7px 12px; font-size: 13px;"
)
S._PRIMARY_BTN_STYLE = f"""
    QPushButton {{
        background: {ACCENT}; color: {ACCENT_TXT}; border: none;
        font-weight: 700; {_BTN_BASE}
    }}
    QPushButton:hover {{ background: {TEXT}; color: {BG}; }}
"""
S._SECONDARY_BTN_STYLE = f"""
    QPushButton {{
        background: transparent; color: {TEXT};
        border: 1px solid {BORDER}; {_BTN_BASE}
    }}
    QPushButton:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}
"""
S._TOOL_BTN_STYLE = f"""
    QPushButton {{
        background: transparent; color: {DIM};
        border: 1px solid transparent; {_BTN_BASE}
    }}
    QPushButton:hover {{ color: {TEXT}; }}
    QPushButton:checked {{
        background: rgba(127, 127, 127, 0.14);
        color: {ACCENT}; border: 1px solid {ACCENT}; font-weight: 700;
    }}
"""
S._TILE_BTN_STYLE = S._TOOL_BTN_STYLE
S._SPINBOX_STYLE = f"""
    QSpinBox {{
        background: {BG}; color: {TEXT}; border: 1px solid {BORDER};
        border-radius: 6px; padding: 5px 8px; font-size: 13px;
    }}
    QSpinBox:focus {{ border-color: {ACCENT}; }}
"""
S._CARD_STYLE = f"""
    QFrame#card {{
        background: {CARD}; border: 1px solid {BORDER}; border-radius: {R};
    }}
"""
S._CARD_TITLE_STYLE = (
    f"color: {TEXT}; font-size: 14px; font-weight: 700; background: transparent;"
)
S._CARD_STEP_STYLE = (
    f"color: {ACCENT_TXT}; font-size: 12px; font-weight: 700;"
    f" background: {ACCENT}; border-radius: 9px; padding: 1px 8px;"
)

app.setStyleSheet(f"""
QWidget {{ background: {BG}; color: {TEXT}; }}
QLabel {{ background: transparent; }}
""")

from features.map.land.page import LandPage

page = LandPage()
page.setFixedWidth(420)
page.adjustSize()
pm = page.grab()
pm.save(f"_landpage_theme_{THEME}.png")
print("OK", THEME, pm.width(), pm.height())
