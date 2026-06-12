"""
导出预检对话框 — 显示项目完成度，支持自动补全后导出。

点"导出MOD"时弹出此对话框，列出所有必需项的状态：
  ✓ 已完成  /  ✗ 缺失（可自动补全）  /  ⚠ 有问题
用户可选择"自动补全并导出"或"取消"。
"""
from __future__ import annotations

import os
import traceback
from dataclasses import dataclass

import numpy as np
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QFileDialog, QGroupBox, QCheckBox,
    QTextEdit, QMessageBox, QWidget,
)

from data.constants import DEFAULT_MOD_OUTPUT_PATH, DEFAULT_MOD_NAME
from ui.i18n import tr


# ── 检查项数据 ──────────────────────────────────────

@dataclass
class CheckItem:
    """单个检查项"""
    name: str           # 显示名
    status: str         # "ok" / "missing" / "warning"
    detail: str         # 详细说明
    can_auto: bool      # 是否可自动补全
    count: int = 0      # 数量（省份数/State数等）


def check_project_readiness(project, canvas) -> list[CheckItem]:
    """检查项目是否可以导出，返回检查项列表。"""
    items: list[CheckItem] = []
    pm = canvas.province_map
    tm = canvas.tile_map
    province_count = int(pm.max())

    # 1. 陆地 / 省份
    if province_count == 0:
        items.append(CheckItem(
            tr("export_check_provinces"), "missing",
            tr("export_check_no_provinces"), False))
        # 没有省份后续检查无意义
        return items

    from data.constants import TILE_LAND
    flat_tm = tm.ravel()
    flat_pm = pm.ravel()
    land_pixels = int(np.sum(flat_tm == TILE_LAND))
    if land_pixels == 0:
        items.append(CheckItem(
            tr("export_check_land"), "missing",
            tr("export_check_no_land"), False))
        return items

    # 检查 ID 连续性（合并省份后可能有空洞）
    existing_ids = set(int(x) for x in np.unique(pm) if x > 0)
    expected_ids = set(range(1, province_count + 1))
    gap_ids = expected_ids - existing_ids
    if gap_ids:
        items.append(CheckItem(
            tr("export_check_provinces"), "warning",
            tr("export_check_province_gaps").format(
                total=len(existing_ids), gaps=len(gap_ids)),
            False, len(existing_ids)))
    else:
        items.append(CheckItem(
            tr("export_check_provinces"), "ok",
            tr("export_check_province_ok").format(count=province_count),
            False, province_count))

    # 2. State
    state_mgr = project.state_mgr
    state_count = len(state_mgr.states) if state_mgr.states else 0
    if state_count == 0:
        items.append(CheckItem(
            tr("export_check_state"), "missing",
            tr("export_check_no_state"),
            True))
    else:
        # 检查孤儿省份
        n = province_count + 1
        land_counts = np.bincount(flat_pm, weights=(flat_tm == TILE_LAND), minlength=n)
        total_counts = np.bincount(flat_pm, minlength=n)
        land_pids = set()
        for pid in range(1, n):
            if total_counts[pid] > 0 and land_counts[pid] > total_counts[pid] / 2:
                land_pids.add(pid)
        assigned = set()
        for s in state_mgr.states.values():
            assigned.update(s.provinces)
        orphans = land_pids - assigned
        if orphans:
            items.append(CheckItem(
                tr("export_check_state"), "warning",
                tr("export_check_state_orphans").format(
                    count=state_count, orphans=len(orphans)),
                True, state_count))
        else:
            items.append(CheckItem(
                tr("export_check_state"), "ok",
                tr("export_check_state_ok").format(count=state_count),
                False, state_count))

    # 3. 国家
    country_mgr = project.country_mgr
    country_count = len(country_mgr.countries) if country_mgr.countries else 0
    if country_count == 0:
        items.append(CheckItem(
            tr("export_check_country"), "missing",
            tr("export_check_no_country"),
            True))
    else:
        # 检查无主 State
        unowned = []
        for sid in state_mgr.states:
            if not country_mgr.get_owner_of_state(sid):
                unowned.append(sid)
        if unowned:
            items.append(CheckItem(
                tr("export_check_country"), "warning",
                tr("export_check_country_unowned").format(
                    count=country_count, unowned=len(unowned)),
                True, country_count))
        else:
            items.append(CheckItem(
                tr("export_check_country"), "ok",
                tr("export_check_country_ok").format(count=country_count),
                False, country_count))

    # 4. 战略区域
    sr_mgr = project.strategic_region_mgr
    sr_count = sr_mgr.count() if sr_mgr else 0
    if sr_count == 0:
        items.append(CheckItem(
            tr("export_check_strategic_region"), "missing",
            tr("export_check_no_strategic_region"),
            True))
    else:
        items.append(CheckItem(
            tr("export_check_strategic_region"), "ok",
            tr("export_check_strategic_region_ok").format(count=sr_count),
            False, sr_count))

    # 5. 大陆
    cont_mgr = project.continent_mgr
    cont_count = cont_mgr.count() if cont_mgr else 0
    if cont_count == 0:
        items.append(CheckItem(
            tr("export_check_continent"), "missing",
            tr("export_check_no_continent"),
            True))
    else:
        items.append(CheckItem(
            tr("export_check_continent"), "ok",
            tr("export_check_continent_ok").format(count=cont_count),
            False, cont_count))

    # 6. 地形
    ter = canvas.terrain_map
    if ter is None or int(ter.max()) == 0:
        items.append(CheckItem(
            tr("export_check_terrain"), "missing",
            tr("export_check_no_terrain"),
            True))
    else:
        items.append(CheckItem(
            tr("export_check_terrain"), "ok",
            tr("export_check_terrain_ok"), False))

    # 7. 高度
    hm = canvas.height_map
    if hm is None or int(hm.max()) == int(hm.min()):
        items.append(CheckItem(
            tr("export_check_heightmap"), "missing",
            tr("export_check_no_heightmap"),
            True))
    else:
        items.append(CheckItem(
            tr("export_check_heightmap"), "ok",
            tr("export_check_heightmap_ok"), False))

    # 8. 美术资产（仅当有导入资产时显示）
    asset_total = len(getattr(project, "assets", {}) or {})
    if asset_total > 0:
        clean_count = project.clean_asset_count()
        dirty_count = project.dirty_asset_count()
        if dirty_count == 0:
            items.append(CheckItem(
                tr("export_check_assets"), "ok",
                tr("export_check_assets_all_clean").format(total=asset_total),
                False, asset_total))
        else:
            items.append(CheckItem(
                tr("export_check_assets"), "warning",
                tr("export_check_assets_dirty").format(
                    total=asset_total, clean=clean_count, dirty=dirty_count),
                False, asset_total))

    return items


# ── 自动补全逻辑 ──────────────────────────────────────

def auto_complete_project(project, canvas) -> list[str]:
    """自动补全缺失数据，返回补全操作日志。"""
    log: list[str] = []
    pm = canvas.province_map
    tm = canvas.tile_map
    province_count = int(pm.max())
    if province_count == 0:
        return [tr("export_auto_no_provinces")]

    # 1. 自动生成 State
    state_mgr = project.state_mgr
    if not state_mgr.states:
        state_mgr.auto_split(pm, tm, per_state=15)
        log.append(tr("export_auto_gen_states").format(count=len(state_mgr.states)))

    # 2. 自动创建国家
    country_mgr = project.country_mgr
    if not country_mgr.countries:
        country_mgr.create_country("AAA", name="Default Nation", color=(100, 100, 200))
        log.append(tr("export_auto_create_country"))

    # 3. 分配无主 State 给第一个国家
    first_tag = next(iter(country_mgr.countries))
    unowned = []
    for sid in state_mgr.states:
        if not country_mgr.get_owner_of_state(sid):
            unowned.append(sid)
    if unowned:
        for sid in unowned:
            country_mgr.assign_state(sid, first_tag)
            state = state_mgr.get_state(sid)
            if state:
                state.owner_tag = first_tag
        log.append(tr("export_auto_assign_states").format(
            count=len(unowned), tag=first_tag))

    # 4. 设首都
    for tag, country in country_mgr.countries.items():
        if country.capital <= 0:
            owned_states = country_mgr.get_states_of_country(tag)
            if owned_states:
                first_state = state_mgr.get_state(owned_states[0])
                if first_state and first_state.provinces:
                    country.capital = first_state.provinces[0]
                    log.append(tr("export_auto_set_capital").format(
                        tag=tag, pid=country.capital))

    # 5. 自动生成战略区域
    sr_mgr = project.strategic_region_mgr
    if sr_mgr.count() == 0:
        sr_mgr.auto_generate(pm, tm, state_mgr=state_mgr)
        log.append(tr("export_auto_gen_sr").format(count=sr_mgr.count()))

    # 6. 大陆（至少有一个默认的）
    cont_mgr = project.continent_mgr
    if cont_mgr.count() == 0:
        cont_mgr.add_continent("default_continent")
        log.append(tr("export_auto_create_continent"))

    return log


# ── 后台导出线程 ──────────────────────────────────────

class ExportWorker(QThread):
    """后台执行导出，避免界面冻结。"""
    progress = pyqtSignal(str)       # 进度文本
    finished = pyqtSignal(object)    # 成功时发 ExportReport
    failed = pyqtSignal(str)         # 失败时发错误信息

    def __init__(
        self, output_dir: str, canvas, project,
        scope: dict[str, bool] | None = None, parent=None,
    ) -> None:
        super().__init__(parent)
        self.output_dir = output_dir
        self.canvas = canvas
        self.project = project
        self.scope = scope or {}

    def run(self) -> None:
        try:
            self.progress.emit(tr("export_worker_pre_check"))
            from services.export_service import export_mod
            report = export_mod(
                self.output_dir,
                self.canvas,
                self.project.state_mgr,
                self.project.country_mgr,
                self.project.continent_mgr,
                adjacency_mgr=self.project.adjacency_mgr,
                railway_mgr=self.project.railway_mgr,
                supply_mgr=self.project.supply_mgr,
                colormap_settings=self.project.colormap_settings,
                default_map_settings=self.project.default_map_settings,
                adjacency_rule_mgr=self.project.adjacency_rule_mgr,
                strategic_region_mgr=self.project.strategic_region_mgr,
                scope=self.scope,
                assets=self.project.assets,
                dirty_assets=self.project.dirty_assets,
            )
            self.finished.emit(report)
        except Exception as e:
            self.failed.emit(f"{e}\n\n{traceback.format_exc()}")


# ── 对话框 ──────────────────────────────────────────

class ExportDialog(QDialog):
    """导出预检对话框 — 检查 → 自动补全 → 选目录 → 导出。"""

    def __init__(self, project, canvas, parent=None) -> None:
        super().__init__(parent)
        self.project = project
        self.canvas = canvas
        self._worker: ExportWorker | None = None

        self.setWindowTitle(tr("export_dlg_title"))
        self.setMinimumWidth(560)
        self.setMinimumHeight(420)
        self._build_ui()
        self._run_check()

    # ── UI 构建 ──

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # 标题
        title = QLabel(tr("export_pre_check_title"))
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(title)

        # 检查结果区域
        self._check_group = QGroupBox(tr("export_project_readiness"))
        self._check_layout = QVBoxLayout(self._check_group)
        layout.addWidget(self._check_group)

        # 导出范围选择
        scope_group = QGroupBox(tr("export_scope"))
        scope_layout = QVBoxLayout(scope_group)

        # 预设按钮行: 全选 / 只地图 / 清空
        preset_row = QHBoxLayout()
        for preset_key, label_key in (
            ("all", "export_scope_btn_select_all"),
            ("map_only", "export_scope_btn_map_only"),
            ("none", "export_scope_btn_clear"),
        ):
            btn = QPushButton(tr(label_key))
            btn.setStyleSheet(
                "QPushButton { padding: 4px 12px; border-radius: 3px; }"
            )
            btn.clicked.connect(
                lambda _checked=False, p=preset_key: self._apply_scope_preset(p)
            )
            preset_row.addWidget(btn)
        preset_row.addStretch()
        scope_layout.addLayout(preset_row)

        self._scope_checks = {}
        scope_items = [
            ("map", tr("export_scope_map"), True),
            ("states", tr("export_scope_states"), True),
            ("countries", tr("export_scope_countries"), True),
            ("strategic_regions", tr("export_scope_strategic_regions"), True),
            ("localisation", tr("export_scope_localisation"), True),
            ("supply", tr("export_scope_supply"), True),
            ("gfx", tr("export_scope_gfx"), True),
            ("replace_path", tr("export_scope_replace_path"), True),
            ("descriptor", tr("export_scope_descriptor"), True),
            ("compact_ids", tr("export_scope_compact_ids"), True),
        ]
        for key, label, default in scope_items:
            cb = QCheckBox(label)
            cb.setChecked(default)
            scope_layout.addWidget(cb)
            self._scope_checks[key] = cb
        layout.addWidget(scope_group)

        # 日志区域（初始隐藏）
        self._log_box = QGroupBox(tr("export_log"))
        log_layout = QVBoxLayout(self._log_box)
        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setMaximumHeight(150)
        log_layout.addWidget(self._log_text)
        self._log_box.setVisible(False)
        layout.addWidget(self._log_box)

        # 进度条（初始隐藏）
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 0)  # indeterminate
        self._progress_bar.setVisible(False)
        layout.addWidget(self._progress_bar)

        self._progress_label = QLabel("")
        self._progress_label.setVisible(False)
        layout.addWidget(self._progress_label)

        # 按钮行
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._btn_auto = QPushButton(tr("export_btn_auto"))
        self._btn_auto.setStyleSheet(
            "QPushButton { background: #6c6cf0; color: white; padding: 8px 20px;"
            " border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background: #7c7cff; }"
            "QPushButton:disabled { background: #444; color: #888; }"
        )
        self._btn_auto.clicked.connect(self._on_auto_export)
        btn_layout.addWidget(self._btn_auto)

        self._btn_export_direct = QPushButton(tr("export_btn_direct"))
        self._btn_export_direct.setStyleSheet(
            "QPushButton { background: #22c55e; color: white; padding: 8px 20px;"
            " border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background: #2ad66a; }"
            "QPushButton:disabled { background: #444; color: #888; }"
        )
        self._btn_export_direct.clicked.connect(self._on_direct_export)
        btn_layout.addWidget(self._btn_export_direct)

        self._btn_cancel = QPushButton(tr("btn_cancel"))
        self._btn_cancel.setStyleSheet(
            "QPushButton { padding: 8px 16px; border-radius: 4px; }"
        )
        self._btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self._btn_cancel)

        layout.addLayout(btn_layout)

    # ── 检查 ──

    def _run_check(self) -> None:
        """执行检查并显示结果。"""
        # 清空旧结果
        while self._check_layout.count():
            child = self._check_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        self._items = check_project_readiness(self.project, self.canvas)

        has_missing = False
        has_blocking = False

        for item in self._items:
            row = QHBoxLayout()

            # 状态图标
            if item.status == "ok":
                icon = "✓"
                color = "#22c55e"
            elif item.status == "warning":
                icon = "⚠"
                color = "#f59e0b"
            else:
                icon = "✗"
                color = "#ef4444"
                has_missing = True
                if not item.can_auto:
                    has_blocking = True

            icon_label = QLabel(icon)
            icon_label.setStyleSheet(f"color: {color}; font-size: 16px; font-weight: bold;")
            icon_label.setFixedWidth(24)
            row.addWidget(icon_label)

            # 名称 + 详情
            text = f"<b>{item.name}</b> — {item.detail}"
            if item.can_auto and item.status != "ok":
                text += f' <span style="color: #6c6cf0;">[{tr("export_can_auto")}]</span>'
            info = QLabel(text)
            info.setWordWrap(True)
            info.setTextFormat(Qt.RichText)
            row.addWidget(info, 1)

            container = QWidget()
            container.setLayout(row)
            self._check_layout.addWidget(container)

        # 有不可自动修复的阻断性错误 → 禁用导出
        if has_blocking:
            self._btn_auto.setEnabled(False)
            self._btn_export_direct.setEnabled(False)

        # 没有缺失项 → 隐藏"自动补全"按钮
        if not has_missing:
            self._btn_auto.setText(tr("export_btn_export"))
            self._btn_export_direct.setVisible(False)

    # ── 预设 ──

    # "只地图" 预设勾选的 scope key — 只生成 map/ 目录下的纯地图文件
    # (BMP + definition.csv + buildings + adjacencies + strategicregions + supply_nodes/railways)
    # 不写 states/countries/localisation/gfx/replace_path/descriptor —
    # 适合已有 MOD 框架, 只需要地图素材的用户
    # compact_ids 也保留: 只地图导出同样需要 definition.csv 编号连续
    _MAP_ONLY_KEYS = frozenset({"map", "strategic_regions", "supply", "compact_ids"})

    def _apply_scope_preset(self, preset: str) -> None:
        """一键设置 scope 勾选状态. preset = "all" | "map_only" | "none"."""
        for key, cb in self._scope_checks.items():
            if preset == "all":
                cb.setChecked(True)
            elif preset == "none":
                cb.setChecked(False)
            elif preset == "map_only":
                cb.setChecked(key in self._MAP_ONLY_KEYS)

    # ── 导出动作 ──

    def _on_auto_export(self) -> None:
        """自动补全后导出。"""
        # 先执行自动补全
        log = auto_complete_project(self.project, self.canvas)
        if log:
            self._log_box.setVisible(True)
            self._log_text.setPlainText("\n".join(
                f"[{tr('export_log_prefix')}] {l}" for l in log))

        # 刷新检查
        self._run_check()

        # 选目录并导出
        self._do_export()

    def _on_direct_export(self) -> None:
        """不补全直接导出。"""
        # 警告
        missing = [i for i in self._items if i.status == "missing"]
        if missing:
            names = tr("export_separator").join(i.name for i in missing)
            reply = QMessageBox.warning(
                self, tr("dlg_confirm"),
                tr("export_confirm_skip").format(names=names),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self._do_export()

    def _do_export(self) -> None:
        """选择目录 → 启动后台导出。"""
        # 压实被关掉且编号有空洞 → 导出的 MOD 属性会错位, 必须用户确认
        if not self._scope_checks["compact_ids"].isChecked():
            ids = np.unique(self.canvas.province_map)
            nonzero = ids[ids > 0]
            gaps = int(nonzero[-1]) - len(nonzero) if len(nonzero) else 0
            if gaps > 0:
                reply = QMessageBox.warning(
                    self, tr("dlg_confirm"),
                    tr("export_compact_off_warn").format(gaps=gaps),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return

        output_dir = QFileDialog.getExistingDirectory(
            self, tr("export_choose_dir"), DEFAULT_MOD_OUTPUT_PATH)
        if not output_dir:
            return

        # 禁用按钮，显示进度
        self._btn_auto.setEnabled(False)
        self._btn_export_direct.setEnabled(False)
        self._btn_cancel.setEnabled(False)
        self._progress_bar.setVisible(True)
        self._progress_label.setVisible(True)
        self._progress_label.setText(tr("export_exporting"))

        self._output_dir = output_dir
        scope = {k: cb.isChecked() for k, cb in self._scope_checks.items()}
        self._worker = ExportWorker(output_dir, self.canvas, self.project,
                                    scope=scope, parent=self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_export_done)
        self._worker.failed.connect(self._on_export_failed)
        self._worker.start()

    def _on_progress(self, text: str) -> None:
        self._progress_label.setText(text)

    def _on_export_done(self, report) -> None:
        self._progress_bar.setVisible(False)
        self._progress_label.setVisible(False)

        # 运行 MOD 验证
        from export.verify_mod import ModVerifier
        verify_errors, verify_warnings = ModVerifier.verify_quiet(self._output_dir)

        # 构建结果文本
        lines = [tr("export_result_success").format(path=self._output_dir)]
        if report.stats:
            lines.append(tr("export_result_stats_header"))
            stat_labels = {
                "provinces": tr("export_stat_provinces"),
                "states": tr("export_stat_states"),
                "countries": tr("export_stat_countries"),
                "files": tr("export_stat_files"),
            }
            for k, v in report.stats.items():
                lines.append(f"  {stat_labels.get(k, k)}: {v}")
        if report.fixed:
            lines.append(tr("export_result_fixed_header"))
            for f in report.fixed:
                lines.append(f"  [{tr('export_result_fixed_tag')}] {f}")
        if report.warnings:
            lines.append(tr("export_result_warnings_header"))
            for w in report.warnings:
                lines.append(f"  [{tr('export_result_warning_tag')}] {w}")

        # 追加验证结果
        if not verify_errors and not verify_warnings:
            lines.append(tr("export_verify_header"))
            lines.append(tr("export_verify_all_pass"))
        else:
            if verify_errors:
                lines.append(tr("export_verify_errors_header").format(
                    count=len(verify_errors)))
                for e in verify_errors:
                    lines.append(f"  ❌ {e}")
            if verify_warnings:
                lines.append(tr("export_verify_warnings_header").format(
                    count=len(verify_warnings)))
                for w in verify_warnings:
                    lines.append(f"  ⚠ {w}")

        # 显示详细结果对话框
        self._show_export_result(lines, verify_errors)

    def _show_export_result(
        self, lines: list[str], verify_errors: list[str]
    ) -> None:
        """用可滚动对话框显示导出结果和验证报告。"""
        dlg = QDialog(self)
        dlg.setWindowTitle(
            tr("export_result_title_errors") if verify_errors
            else tr("export_result_title_ok")
        )
        dlg.setMinimumWidth(560)
        dlg.setMinimumHeight(400)

        layout = QVBoxLayout(dlg)

        # 标题标签
        if verify_errors:
            header = QLabel(tr("export_done_has_errors"))
            header.setStyleSheet(
                "font-size: 15px; font-weight: bold; color: #ef4444;"
            )
        else:
            header = QLabel(tr("export_done_all_pass"))
            header.setStyleSheet(
                "font-size: 15px; font-weight: bold; color: #22c55e;"
            )
        layout.addWidget(header)

        # 可滚动文本区域
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setPlainText("\n".join(lines))
        layout.addWidget(text_edit)

        # 关闭按钮
        btn_close = QPushButton(tr("export_result_close"))
        btn_close.setStyleSheet(
            "QPushButton { padding: 8px 20px; border-radius: 4px;"
            " font-weight: bold; }"
        )
        btn_close.clicked.connect(dlg.accept)
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(btn_close)
        layout.addLayout(btn_layout)

        dlg.exec_()
        self.accept()

    def _on_export_failed(self, error_msg: str) -> None:
        self._progress_bar.setVisible(False)
        self._progress_label.setVisible(False)
        self._btn_auto.setEnabled(True)
        self._btn_export_direct.setEnabled(True)
        self._btn_cancel.setEnabled(True)

        QMessageBox.critical(self, tr("export_failed_title"), error_msg)
