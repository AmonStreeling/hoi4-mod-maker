import sys

sys.path.insert(0, ".")

from PyQt5.QtWidgets import QApplication

# 原生平台 + 不 show(): grab() 对隐藏控件同样渲染, 有字体且不弹窗
app = QApplication([])
from PyQt5.QtGui import QFont
_f = QFont("Segoe UI", 9)
_f.setFamilies(["Segoe UI", "Microsoft YaHei", "Noto Sans SC"])
app.setFont(_f)
from ui.i18n import set_language
set_language("zh")   # 截图脚本显式定语言 (主程序在 main.py 里做同样的事)
from ui.styles import DARK_STYLESHEET
app.setStyleSheet(DARK_STYLESHEET)

from features.map.land.page import LandPage

page = LandPage()
page.setFixedWidth(420)
page.adjustSize()
pm = page.grab()
pm.save("_landpage_current.png")
print(f"OK {pm.width()}x{pm.height()}")
