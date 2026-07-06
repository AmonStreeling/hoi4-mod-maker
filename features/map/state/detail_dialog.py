"""
State 详情对话框 — 编辑一个 State 的进阶字段:
- impassable / controller / local_supplies
- resources (6 种战略资源)
- buildings (state 级建筑等级)
- extra_cores / claims (TAG 列表)

省份级建筑 (bunker/coastal_bunker/naval_base) 暂未在此 UI 暴露,
需按省份编辑, 下个迭代做专门的省份建筑工具.
"""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout,
    QLabel, QLineEdit, QCheckBox, QSpinBox, QDoubleSpinBox, QComboBox,
    QPushButton, QGroupBox, QListWidget, QInputDialog, QTabWidget, QWidget,
    QScrollArea,
)

from ui.i18n import tr


# HOI4 战略资源 (vanilla 1.18 完整列表)
RESOURCE_NAMES = ["oil", "aluminium", "rubber", "tungsten", "steel", "chromium", "coal"]
RESOURCE_LABELS = {
    "oil": "state_dlg_res_oil", "aluminium": "state_dlg_res_aluminium",
    "rubber": "state_dlg_res_rubber", "tungsten": "state_dlg_res_tungsten",
    "steel": "state_dlg_res_steel", "chromium": "state_dlg_res_chromium",
    "coal": "state_dlg_res_coal",
}

# HOI4 state 级建筑 (value 0 = 不写)
STATE_BUILDINGS = [
    "infrastructure",
    "arms_factory",
    "industrial_complex",
    "dockyard",
    "air_base",
    "anti_air_building",
    "radar_station",
    "synthetic_refinery",
    "fuel_silo",
    "nuclear_reactor",
    "rocket_site",
    "mass_transit",
    "supply_node",
]
BUILDING_LABELS = {
    "infrastructure": "state_dlg_bld_infrastructure",
    "arms_factory": "state_dlg_bld_arms_factory",
    "industrial_complex": "state_dlg_bld_industrial_complex",
    "dockyard": "state_dlg_bld_dockyard",
    "air_base": "state_dlg_bld_air_base",
    "anti_air_building": "state_dlg_bld_anti_air",
    "radar_station": "state_dlg_bld_radar",
    "synthetic_refinery": "state_dlg_bld_synthetic",
    "fuel_silo": "state_dlg_bld_fuel_silo",
    "nuclear_reactor": "state_dlg_bld_nuclear",
    "rocket_site": "state_dlg_bld_rocket",
    "mass_transit": "state_dlg_bld_mass_transit",
    "supply_node": "state_dlg_bld_supply_node",
}
BUILDING_MAX = {
    "infrastructure": 5,
    "air_base": 10,
    "anti_air_building": 5,
    "radar_station": 4,
    "nuclear_reactor": 3,
    "rocket_site": 10,
    "mass_transit": 3,
    "supply_node": 1,
    # 其他默认 30 (vanilla 实际上限视 state_category 而定)
}


class StateDetailDialog(QDialog):
    """编辑单个 State 的进阶字段. 模态."""

    def __init__(self, state, country_tags: list[str], parent=None):
        super().__init__(parent)
        self._state = state
        self._country_tags = country_tags
        self.setWindowTitle(tr("state_dlg_title_fmt", state.name, state.id))
        self.setMinimumSize(520, 600)

        self._build_ui()
        self._load_from_state()

    # ─────────── UI 构建 ───────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        tabs = QTabWidget()
        root.addWidget(tabs, 1)

        # 每个 tab 包滚动区域: 内容(建筑13行/VP多行)超过窗口高度时可滚动, 不再被裁掉
        tabs.addTab(self._wrap_scroll(self._build_basic_tab()), tr("state_dlg_tab_basic"))
        tabs.addTab(self._wrap_scroll(self._build_resources_tab()), tr("state_dlg_tab_resources"))
        tabs.addTab(self._wrap_scroll(self._build_buildings_tab()), tr("state_dlg_tab_buildings"))
        tabs.addTab(self._wrap_scroll(self._build_cores_tab()), tr("state_dlg_tab_cores"))

        # 底部按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        ok_btn = QPushButton(tr("state_dlg_save"))
        ok_btn.clicked.connect(self._on_accept)
        cancel_btn = QPushButton(tr("state_dlg_cancel"))
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        root.addLayout(btn_row)

    @staticmethod
    def _wrap_scroll(inner: QWidget) -> QScrollArea:
        """tab 内容套滚动区域, 高度不够时出滚动条。"""
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        area.setWidget(inner)
        return area

    def _build_basic_tab(self) -> QWidget:
        w = QWidget()
        lay = QFormLayout(w)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText(tr("state_dlg_name_hint"))
        lay.addRow(tr("state_dlg_name_label"), self._name_edit)

        self._name_en_edit = QLineEdit()
        self._name_en_edit.setPlaceholderText(tr("state_dlg_name_en_hint"))
        lay.addRow(tr("state_dlg_name_en_label"), self._name_en_edit)

        self._manpower_spin = QSpinBox()
        self._manpower_spin.setRange(0, 100_000_000)
        self._manpower_spin.setSingleStep(10000)
        lay.addRow(tr("state_dlg_manpower_label"), self._manpower_spin)

        self._impassable_check = QCheckBox(tr("state_dlg_impassable"))
        lay.addRow("", self._impassable_check)

        self._controller_combo = QComboBox()
        self._controller_combo.addItem(tr("state_dlg_controller_same"), "")
        for tag in self._country_tags:
            self._controller_combo.addItem(tag, tag)
        lay.addRow(tr("state_dlg_controller_label"), self._controller_combo)

        self._supplies_spin = QDoubleSpinBox()
        self._supplies_spin.setRange(0.0, 100.0)
        self._supplies_spin.setSingleStep(0.5)
        self._supplies_spin.setDecimals(2)
        lay.addRow(tr("state_dlg_supplies_label"), self._supplies_spin)

        # VP 城市命名（中英两列，英文可选）
        vp_box = QGroupBox(tr("state_dlg_vp_names"))
        vp_lay = QGridLayout(vp_box)
        vp_lay.addWidget(QLabel(tr("state_dlg_vp_province")), 0, 0)
        vp_lay.addWidget(QLabel(tr("state_dlg_vp_value")), 0, 1)
        vp_lay.addWidget(QLabel(tr("state_dlg_vp_city_name")), 0, 2)
        vp_lay.addWidget(QLabel(tr("state_dlg_vp_city_name_en")), 0, 3)
        self._vp_name_edits: dict[int, QLineEdit] = {}
        self._vp_name_en_edits: dict[int, QLineEdit] = {}
        row_idx = 1
        vp_names_en = getattr(self._state, "vp_names_en", {}) or {}
        for vpid, vpval in self._state.victory_points.items():
            vp_lay.addWidget(QLabel(str(vpid)), row_idx, 0)
            vp_lay.addWidget(QLabel(str(vpval)), row_idx, 1)
            edit = QLineEdit()
            edit.setPlaceholderText(self._state.name or f"State {self._state.id}")
            edit.setText(self._state.vp_names.get(vpid, ""))
            self._vp_name_edits[vpid] = edit
            vp_lay.addWidget(edit, row_idx, 2)
            edit_en = QLineEdit()
            edit_en.setPlaceholderText(f"State {self._state.id}")
            edit_en.setText(vp_names_en.get(vpid, ""))
            self._vp_name_en_edits[vpid] = edit_en
            vp_lay.addWidget(edit_en, row_idx, 3)
            row_idx += 1
        if not self._state.victory_points:
            vp_lay.addWidget(QLabel(tr("state_dlg_vp_none")), 1, 0, 1, 4)
        lay.addRow(vp_box)

        return w

    def _build_resources_tab(self) -> QWidget:
        w = QWidget()
        lay = QGridLayout(w)
        lay.setColumnStretch(0, 0)
        lay.setColumnStretch(1, 1)
        lay.addWidget(QLabel(f"<b>{tr('state_dlg_resources_hint')}</b>"), 0, 0, 1, 2)

        self._resource_spins: dict[str, QSpinBox] = {}
        for i, key in enumerate(RESOURCE_NAMES):
            lay.addWidget(QLabel(f"{tr(RESOURCE_LABELS[key])} ({key}):"), i + 1, 0)
            spin = QSpinBox()
            spin.setRange(0, 10000)
            lay.addWidget(spin, i + 1, 1)
            self._resource_spins[key] = spin
        lay.setRowStretch(len(RESOURCE_NAMES) + 1, 1)
        return w

    def _build_buildings_tab(self) -> QWidget:
        w = QWidget()
        lay = QGridLayout(w)
        lay.addWidget(
            QLabel(
                f"<b>{tr('state_dlg_buildings_hint')}</b><br>"
                f"<span style='color:#888'>{tr('state_dlg_buildings_sub')}</span>"
            ),
            0, 0, 1, 2,
        )
        self._building_spins: dict[str, QSpinBox] = {}
        for i, key in enumerate(STATE_BUILDINGS):
            lay.addWidget(QLabel(tr(BUILDING_LABELS.get(key, key)) + ":"), i + 1, 0)
            spin = QSpinBox()
            spin.setRange(0, BUILDING_MAX.get(key, 30))
            lay.addWidget(spin, i + 1, 1)
            self._building_spins[key] = spin

        # 省份级建筑入口
        last_row = len(STATE_BUILDINGS) + 1
        lay.addWidget(QLabel(""), last_row, 0)  # 空行
        prov_btn = QPushButton(tr("state_dlg_edit_prov_buildings"))
        prov_btn.clicked.connect(self._on_edit_province_buildings)
        lay.addWidget(prov_btn, last_row + 1, 0, 1, 2)
        lay.setRowStretch(last_row + 2, 1)
        return w

    def _on_edit_province_buildings(self) -> None:
        """打开省份级建筑对话框."""
        from features.map.state.province_buildings_dialog import (
            ProvinceBuildingsDialog,
        )
        # 用 state.provinces 作为全部省份列表 (省份内部已经过滤过 land)
        land_pids = list(self._state.provinces)
        dlg = ProvinceBuildingsDialog(self._state, land_pids, parent=self)
        dlg.exec_()

    def _build_cores_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        # 额外核心
        cores_box = QGroupBox(tr("state_dlg_cores_group"))
        cores_lay = QVBoxLayout(cores_box)
        self._cores_list = QListWidget()
        cores_lay.addWidget(self._cores_list)
        row = QHBoxLayout()
        add_core_btn = QPushButton(tr("state_dlg_add"))
        add_core_btn.clicked.connect(self._on_add_core)
        del_core_btn = QPushButton(tr("state_dlg_delete_selected"))
        del_core_btn.clicked.connect(self._on_del_core)
        row.addWidget(add_core_btn)
        row.addWidget(del_core_btn)
        cores_lay.addLayout(row)
        lay.addWidget(cores_box)

        # 宣称
        claims_box = QGroupBox(tr("state_dlg_claims_group"))
        claims_lay = QVBoxLayout(claims_box)
        self._claims_list = QListWidget()
        claims_lay.addWidget(self._claims_list)
        row2 = QHBoxLayout()
        add_claim_btn = QPushButton(tr("state_dlg_add"))
        add_claim_btn.clicked.connect(self._on_add_claim)
        del_claim_btn = QPushButton(tr("state_dlg_delete_selected"))
        del_claim_btn.clicked.connect(self._on_del_claim)
        row2.addWidget(add_claim_btn)
        row2.addWidget(del_claim_btn)
        claims_lay.addLayout(row2)
        lay.addWidget(claims_box)

        return w

    # ─────────── 加载/保存 ───────────

    def _load_from_state(self) -> None:
        s = self._state
        # 如果旧数据 name 是 key 形式（STATE_123），UI 显示空让用户填显示名
        display_name = s.name if (s.name and s.name != f"STATE_{s.id}") else ""
        self._name_edit.setText(display_name)
        self._name_en_edit.setText(getattr(s, "name_en", "") or "")
        self._manpower_spin.setValue(int(s.manpower or 0))
        self._impassable_check.setChecked(bool(getattr(s, "impassable", False)))

        ctl = getattr(s, "controller_tag", "") or ""
        idx = self._controller_combo.findData(ctl)
        self._controller_combo.setCurrentIndex(idx if idx >= 0 else 0)

        self._supplies_spin.setValue(float(getattr(s, "local_supplies", 0.0) or 0.0))

        # 资源
        res = getattr(s, "resources", {}) or {}
        for key, spin in self._resource_spins.items():
            spin.setValue(int(res.get(key, 0) or 0))

        # 建筑
        bld = getattr(s, "buildings", {}) or {}
        for key, spin in self._building_spins.items():
            spin.setValue(int(bld.get(key, 0) or 0))

        # 核心 / 宣称
        self._cores_list.clear()
        for tag in getattr(s, "extra_cores", []) or []:
            self._cores_list.addItem(tag)
        self._claims_list.clear()
        for tag in getattr(s, "claims", []) or []:
            self._claims_list.addItem(tag)

    def _on_accept(self) -> None:
        s = self._state
        # name 留空就留空（不自动填 key；导出时按 name_en 或默认 "State {id}" 兜底）
        s.name = self._name_edit.text().strip()
        s.name_en = self._name_en_edit.text().strip()
        s.manpower = int(self._manpower_spin.value())
        s.impassable = bool(self._impassable_check.isChecked())
        s.controller_tag = self._controller_combo.currentData() or ""
        s.local_supplies = float(self._supplies_spin.value())

        s.resources = {
            k: int(spin.value())
            for k, spin in self._resource_spins.items()
            if int(spin.value()) > 0
        }
        s.buildings = {
            k: int(spin.value())
            for k, spin in self._building_spins.items()
            if int(spin.value()) > 0
        }
        s.extra_cores = [
            self._cores_list.item(i).text() for i in range(self._cores_list.count())
        ]
        s.claims = [
            self._claims_list.item(i).text() for i in range(self._claims_list.count())
        ]

        # VP 城市名（中英）
        if not hasattr(s, "vp_names_en") or s.vp_names_en is None:
            s.vp_names_en = {}
        for vpid, edit in self._vp_name_edits.items():
            s.vp_names[vpid] = edit.text().strip()
        for vpid, edit in self._vp_name_en_edits.items():
            s.vp_names_en[vpid] = edit.text().strip()

        self.accept()

    # ─────────── 核心 / 宣称 操作 ───────────

    def _ask_tag(self, title: str) -> str:
        if self._country_tags:
            tag, ok = QInputDialog.getItem(
                self, title, tr("state_dlg_select_tag"), self._country_tags, 0, True
            )
        else:
            tag, ok = QInputDialog.getText(self, title, tr("state_dlg_input_tag"))
        return tag.strip().upper() if ok else ""

    def _on_add_core(self) -> None:
        tag = self._ask_tag(tr("state_dlg_add_core_title"))
        if not tag:
            return
        # 去重
        existing = [self._cores_list.item(i).text() for i in range(self._cores_list.count())]
        if tag in existing:
            return
        self._cores_list.addItem(tag)

    def _on_del_core(self) -> None:
        row = self._cores_list.currentRow()
        if row >= 0:
            self._cores_list.takeItem(row)

    def _on_add_claim(self) -> None:
        tag = self._ask_tag(tr("state_dlg_add_claim_title"))
        if not tag:
            return
        existing = [self._claims_list.item(i).text() for i in range(self._claims_list.count())]
        if tag in existing:
            return
        self._claims_list.addItem(tag)

    def _on_del_claim(self) -> None:
        row = self._claims_list.currentRow()
        if row >= 0:
            self._claims_list.takeItem(row)
