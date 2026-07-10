"""胜利点对话框 — 数值 + 城市名一次填完.

效果: 设置省份的胜利点数值(0 = 移除)和城市名字;
     名字显示在地图红点旁, 导出后就是游戏地图上的城市名.
调用: ask_vp(parent, pid, cur_vp, cur_name) → (value, name, ok)
"""
from __future__ import annotations

from PyQt5.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QSpinBox,
)

from ui.i18n import tr


def ask_vp(
    parent,
    pid: int,
    cur_vp: int = 0,
    cur_name: str = "",
) -> tuple[int, str, bool]:
    """弹出 VP 设置对话框, 返回 (数值, 城市名, 是否确认)。"""
    dlg = QDialog(parent)
    dlg.setWindowTitle(tr("dlg_vp_title_fmt", pid))
    form = QFormLayout(dlg)

    spin = QSpinBox(dlg)
    spin.setRange(0, 50)
    spin.setValue(cur_vp if cur_vp > 0 else 1)
    form.addRow(tr("dlg_vp_value_label"), spin)

    name_edit = QLineEdit(cur_name, dlg)
    name_edit.setPlaceholderText(tr("dlg_vp_name_placeholder"))
    form.addRow(tr("dlg_vp_name_label"), name_edit)

    buttons = QDialogButtonBox(
        QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=dlg)
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    form.addRow(buttons)

    ok = dlg.exec_() == QDialog.Accepted
    return spin.value(), name_edit.text().strip(), ok
