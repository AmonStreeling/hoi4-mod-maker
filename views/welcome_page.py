"""
欢迎页面 — 启动时显示，提供新建/打开/最近项目入口。
"""
from __future__ import annotations

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QListWidget, QListWidgetItem, QDialog,
    QSpinBox, QDialogButtonBox, QFormLayout,
)
from PyQt5.QtCore import pyqtSignal, Qt, QSettings
from PyQt5.QtGui import QFont

from ui.i18n import tr


# ── 色板 (与 ui/styles.py 保持一致) ──
_BG = "#1e1e2e"
_INPUT_BG = "#252535"
_BORDER = "#3a3a4a"
_TEXT = "#e0e0f0"
_DIM = "#8888a8"
_ACCENT = "#6c6cf0"
_ACCENT_HOVER = "#7c7cff"

_MAX_RECENT = 10


def _load_recent_projects() -> list[str]:
    """从 QSettings 读取最近项目列表。"""
    settings = QSettings("HOI4MapMaker", "RecentProjects")
    paths = settings.value("paths", [])
    if isinstance(paths, str):
        return [paths] if paths else []
    return list(paths or [])


def save_recent_project(path: str) -> None:
    """添加路径到最近项目列表（去重、限数量）。"""
    recent = _load_recent_projects()
    if path in recent:
        recent.remove(path)
    recent.insert(0, path)
    recent = recent[:_MAX_RECENT]
    settings = QSettings("HOI4MapMaker", "RecentProjects")
    settings.setValue("paths", recent)


class _SizePickerDialog(QDialog):
    """地图尺寸选择对话框。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("welcome_size_picker_title"))
        self.setMinimumSize(300, 160)
        self.resize(300, 160)

        layout = QFormLayout(self)

        self._width_spin = QSpinBox()
        self._width_spin.setRange(256, 16384)
        self._width_spin.setValue(5632)
        self._width_spin.setSingleStep(256)
        layout.addRow(tr("welcome_width"), self._width_spin)

        self._height_spin = QSpinBox()
        self._height_spin.setRange(256, 16384)
        self._height_spin.setValue(2048)
        self._height_spin.setSingleStep(256)
        layout.addRow(tr("welcome_height"), self._height_spin)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    @property
    def chosen_size(self) -> tuple[int, int]:
        return self._width_spin.value(), self._height_spin.value()


class WelcomePage(QWidget):
    """启动欢迎页，新建/打开/最近项目。"""

    new_project_requested = pyqtSignal(int, int)   # width, height
    open_project_requested = pyqtSignal()
    open_recent_requested = pyqtSignal(str)         # path
    import_mod_requested = pyqtSignal()              # 导入MOD地图
    open_vanilla_requested = pyqtSignal()            # 打开原版游戏地图(只读参考)
    language_changed = pyqtSignal(str)               # 语言 code, eg. "zh" / "en" / "ja"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(f"WelcomePage {{ background: {_BG}; }}")
        self._init_ui()

    _CARD_WIDTH = 280
    _CARD_SPACING = 40

    def _init_ui(self) -> None:
        # 布局：左占位 | stretch | 主菜单(居中) | 间距 | 社区卡片 | stretch
        # 左占位宽度 = 卡片宽 + 间距，使主菜单保持屏幕正中
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 左侧平衡占位（和右侧卡片+间距等宽）
        left_spacer = QWidget()
        left_spacer.setFixedWidth(self._CARD_WIDTH + self._CARD_SPACING)
        left_spacer.setStyleSheet("background: transparent;")
        outer.addWidget(left_spacer)
        outer.addStretch(1)

        # ══════ 主菜单（居中主体） ══════
        left = QVBoxLayout()
        left.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left.setSpacing(16)

        # 标题
        title = QLabel(tr("welcome_title"))
        title_font = QFont("Segoe UI", 28, QFont.Weight.Bold)
        title_font.setFamilies(["Segoe UI", "Microsoft YaHei", "Noto Sans SC"])
        title.setFont(title_font)
        title.setStyleSheet(f"color: {_TEXT}; background: transparent;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left.addWidget(title)

        # 版本
        from version import VERSION
        version = QLabel(f"v{VERSION}")
        version.setStyleSheet(f"color: {_DIM}; font-size: 14px; background: transparent;")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left.addWidget(version)

        # 语言切换（自动按 ui/i18n/ 下已有语言文件夹填充）
        lang_row = QHBoxLayout()
        lang_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        from ui.i18n import get_language, available_languages, language_display_name
        cur = get_language()

        def _lang_btn(text: str, lang: str) -> QPushButton:
            active = (lang == cur)
            btn = QPushButton(text)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {_ACCENT if active else 'transparent'};
                    border: 1px solid {_ACCENT if active else _BORDER};
                    color: {'white' if active else _DIM};
                    padding: 4px 12px;
                    font-size: 13px;
                    border-radius: 4px;
                    min-width: 60px;
                }}
                QPushButton:hover {{
                    border-color: {_ACCENT};
                }}
            """)
            btn.clicked.connect(lambda _checked=False, _l=lang: self._switch_lang(_l))
            return btn

        for lang in available_languages():
            lang_row.addWidget(_lang_btn(language_display_name(lang), lang))
        left.addLayout(lang_row)

        left.addSpacing(24)

        # 按钮样式
        btn_style = f"""
            QPushButton {{
                background: {_INPUT_BG};
                border: 1px solid {_BORDER};
                color: {_TEXT};
                padding: 12px 32px;
                font-size: 15px;
                border-radius: 6px;
                min-width: 200px;
            }}
            QPushButton:hover {{
                border-color: {_ACCENT};
                background: rgba(108, 108, 240, 0.12);
            }}
        """

        btn_new = QPushButton(tr("action_new"))
        btn_new.setStyleSheet(btn_style)
        btn_new.clicked.connect(self._on_new)
        left.addWidget(btn_new, alignment=Qt.AlignmentFlag.AlignCenter)

        btn_open = QPushButton(tr("action_open"))
        btn_open.setStyleSheet(btn_style)
        btn_open.clicked.connect(lambda: self.open_project_requested.emit())
        left.addWidget(btn_open, alignment=Qt.AlignmentFlag.AlignCenter)

        btn_import = QPushButton(tr("welcome_import_mod"))
        btn_import.setStyleSheet(btn_style)
        btn_import.clicked.connect(lambda: self.import_mod_requested.emit())
        left.addWidget(btn_import, alignment=Qt.AlignmentFlag.AlignCenter)

        btn_vanilla = QPushButton(tr("welcome_open_vanilla"))
        btn_vanilla.setStyleSheet(btn_style)
        btn_vanilla.clicked.connect(lambda: self.open_vanilla_requested.emit())
        left.addWidget(btn_vanilla, alignment=Qt.AlignmentFlag.AlignCenter)

        btn_guide = QPushButton(tr("action_guide"))
        btn_guide.setStyleSheet(btn_style)
        btn_guide.clicked.connect(self._on_guide)
        left.addWidget(btn_guide, alignment=Qt.AlignmentFlag.AlignCenter)

        left.addSpacing(12)

        # 最近项目
        recent_label = QLabel(tr("welcome_recent"))
        recent_label.setStyleSheet(f"color: {_DIM}; font-size: 12px; background: transparent;")
        recent_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left.addWidget(recent_label)

        self._recent_list = QListWidget()
        # 软约束: 最小 640x220, 窗口大时可自适应
        self._recent_list.setMinimumSize(640, 220)
        self._recent_list.setToolTip(tr("welcome_recent_tooltip"))
        self._recent_list.setStyleSheet(f"""
            QListWidget {{
                background: {_INPUT_BG};
                border: 1px solid {_BORDER};
                border-radius: 6px;
                color: {_TEXT};
                font-size: 13px;
            }}
            QListWidget::item {{
                padding: 6px 8px;
            }}
            QListWidget::item:selected {{
                background: {_ACCENT};
                color: white;
            }}
            QListWidget::item:hover:!selected {{
                background: rgba(255, 255, 255, 0.05);
            }}
        """)
        self._recent_list.itemDoubleClicked.connect(self._on_recent_clicked)
        left.addWidget(self._recent_list, alignment=Qt.AlignmentFlag.AlignCenter)

        self._populate_recent()
        outer.addLayout(left)

        outer.addSpacing(self._CARD_SPACING)

        # ══════ 社区卡片（紧贴主菜单右边，垂直居中） ══════
        right = QVBoxLayout()
        right.setSpacing(0)
        right.addStretch(1)

        info_card = QWidget()
        info_card.setFixedWidth(self._CARD_WIDTH)
        info_card.setStyleSheet(f"""
            QWidget {{
                background: {_INPUT_BG};
                border: 1px solid {_BORDER};
                border-radius: 8px;
            }}
        """)
        card_lay = QVBoxLayout(info_card)
        card_lay.setContentsMargins(24, 24, 24, 24)
        card_lay.setSpacing(16)

        # 社区支持
        community_title = QLabel(tr("welcome_community_title"))
        community_title.setStyleSheet(f"color: {_ACCENT}; font-size: 15px; font-weight: bold; background: transparent; border: none;")
        card_lay.addWidget(community_title)

        community = QLabel(tr("welcome_community"))
        community.setWordWrap(True)
        community.setTextFormat(Qt.TextFormat.RichText)
        community.setOpenExternalLinks(True)
        community.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction | Qt.TextInteractionFlag.TextSelectableByMouse
        )
        community.setStyleSheet(f"color: {_TEXT}; font-size: 13px; line-height: 1.8; background: transparent; border: none;")
        card_lay.addWidget(community)

        # 分隔线
        sep = QLabel()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {_BORDER}; border: none;")
        card_lay.addWidget(sep)

        # GitHub + 反馈
        links = QLabel(tr("welcome_links"))
        links.setWordWrap(True)
        links.setTextFormat(Qt.TextFormat.RichText)
        links.setOpenExternalLinks(True)
        links.setStyleSheet(f"color: {_TEXT}; font-size: 13px; background: transparent; border: none;")
        card_lay.addWidget(links)

        right.addWidget(info_card)
        right.addStretch(1)
        outer.addLayout(right)
        outer.addStretch(1)

    def _populate_recent(self) -> None:
        self._recent_list.clear()
        for path in _load_recent_projects():
            item = QListWidgetItem(path)
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(path)  # 悬停显示完整路径（万一还是超出）
            self._recent_list.addItem(item)
        if self._recent_list.count() == 0:
            empty = QListWidgetItem(tr("welcome_no_recent"))
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self._recent_list.addItem(empty)

    def _on_new(self) -> None:
        dlg = _SizePickerDialog(self)
        if dlg.exec_() == QDialog.DialogCode.Accepted:
            w, h = dlg.chosen_size
            self.new_project_requested.emit(w, h)

    def _on_guide(self) -> None:
        from views.guide_dialog import GuideDialog
        dlg = GuideDialog(self)
        dlg.exec_()

    def _switch_lang(self, lang: str) -> None:
        from ui.i18n import set_language, get_language
        if lang == get_language():
            return
        set_language(lang)
        # 保存语言设置到 json
        import json, os as _os
        config_path = _os.path.join(_os.path.expanduser("~"), ".hoi4_map_maker.json")
        config = {}
        if _os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    config = json.load(f)
            except Exception:
                pass
        config["language"] = lang
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False)
        self.language_changed.emit(lang)

    def retranslateUi(self) -> None:
        """语言切换后重建整个欢迎页。"""
        # 删除旧 layout 和所有子 widget
        old_layout = self.layout()
        if old_layout:
            from PyQt5 import sip
            while old_layout.count():
                item = old_layout.takeAt(0)
                w = item.widget()
                if w:
                    w.setParent(None)
                    w.deleteLater()
                sub = item.layout()
                if sub:
                    self._clear_layout(sub)
            sip.delete(old_layout)
        self._init_ui()

    @staticmethod
    def _clear_layout(layout) -> None:
        """递归清除 layout 下的所有 widget 和子 layout。"""
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
            sub = item.layout()
            if sub:
                WelcomePage._clear_layout(sub)

    def _on_recent_clicked(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self.open_recent_requested.emit(path)
