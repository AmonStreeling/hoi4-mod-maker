"""
主窗口动作处理 — 省份生成/验证/国家对话框/河流/地形/大陆/战略区/后勤。
从 views/main_window.py 拆分，作为 mixin 使用。

文件操作 (新建/打开/保存/导入/导出/测试导出) 在 views/main_window_file_ops.py。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from PyQt5.QtWidgets import (
    QMessageBox, QApplication, QInputDialog, QColorDialog,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor

from ui.i18n import tr, set_language, get_language, available_languages
from views.main_window_file_ops import MainWindowFileOpsMixin

if TYPE_CHECKING:
    from controllers.country import CountryController
    from controllers.default_map import DefaultMapController
    from controllers.logistics import LogisticsController


# ── 后台线程 ──

class _GenerateThread(QThread):
    """后台线程生成省份"""
    finished = pyqtSignal(object, int)
    error = pyqtSignal(str)

    def __init__(self, tile_map, count, province_map=None, incremental=False,
                 sea_scale=0.15, lake_scale=0.3, density_map=None,
                 skip_mismatch_clear=False):
        super().__init__()
        self._tile_map = tile_map.copy()
        self._count = count
        self._province_map = province_map.copy() if province_map is not None else None
        self._incremental = incremental
        self._sea_scale = sea_scale
        self._lake_scale = lake_scale
        self._density_map = density_map.copy() if density_map is not None else None
        self._skip_mismatch_clear = skip_mismatch_clear

    def run(self):
        try:
            if self._incremental and self._province_map is not None:
                from domain.generators.province import generate_provinces_incremental
                pm, cnt = generate_provinces_incremental(
                    self._tile_map, self._province_map,
                    skip_mismatch_clear=self._skip_mismatch_clear,
                )
            else:
                from domain.generators.province import generate_provinces
                pm, cnt = generate_provinces(
                    self._tile_map, self._count,
                    sea_scale=self._sea_scale,
                    density_map=self._density_map,
                )
            self.finished.emit(pm, cnt)
        except Exception as e:
            self.error.emit(str(e))


class _ValidateThread(QThread):
    """后台线程验证省份"""
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, tile_map, province_map):
        super().__init__()
        self._tile_map = tile_map.copy()
        self._province_map = province_map.copy()

    def run(self):
        try:
            from domain.validators.province import validate_provinces
            results = validate_provinces(self._tile_map, self._province_map)
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))


class MainWindowActionsMixin(MainWindowFileOpsMixin):
    """省份生成/验证/国家对话框/河流/地形/大陆/战略区/后勤处理。"""

    # ═══════════════════════ 州自动分组 ═══════════════════

    def _on_auto_states_with_confirm(self, per_state: int) -> None:
        """自动分组前确认（会清空现有州数据）。可撤销 (Ctrl+Z)。"""
        from commands.map.manager_snapshot import ManagerSnapshotCommand
        existing = len(self._project.state_mgr.states)
        if existing > 0:
            reply = QMessageBox.question(
                self, "确认自动分组",
                f"当前已有 {existing} 个州。\n"
                f"自动分组将清空所有现有州数据，重新按每州 {per_state} 个省份分组。\n\n"
                f"是否继续？",
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        # 撤销快照：state_mgr 内部字段
        state_mgr = self._project.state_mgr
        snap_fields = [f for f in ("_states", "_next_id") if hasattr(state_mgr, f)]
        cmd = ManagerSnapshotCommand("自动分组州", state_mgr, snap_fields)
        self._controllers["state"].auto_states(per_state)
        cmd.capture_after()
        self._cmd_history._undo_stack.append(cmd)
        self._cmd_history._redo_stack.clear()
        self._cmd_history._notify()

    # ═══════════════════════ 战略区域自动生成 ═══════════════════

    def _on_auto_sr_with_confirm(self) -> None:
        """自动生成战略区域前确认。可撤销 (Ctrl+Z)。"""
        from commands.map.manager_snapshot import ManagerSnapshotCommand
        existing = self._project.strategic_region_mgr.count()
        if existing > 0:
            reply = QMessageBox.question(
                self, "确认自动生成",
                f"当前已有 {existing} 个战略区域。\n"
                f"自动生成将清空所有现有战略区域数据。\n\n是否继续？",
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        # 撤销快照：strategic_region_mgr 内部字段
        sr_mgr = self._project.strategic_region_mgr
        snap_fields = [f for f in ("_regions", "_next_id") if hasattr(sr_mgr, f)]
        cmd = ManagerSnapshotCommand("自动生成战略区", sr_mgr, snap_fields)
        self._controllers["strategic_region"].auto_generate()
        cmd.capture_after()
        self._cmd_history._undo_stack.append(cmd)
        self._cmd_history._redo_stack.clear()
        self._cmd_history._notify()

    # ═══════════════════════ 省份生成与验证 ═══════════════════

    def _on_clear_new_land_mask(self) -> None:
        """清空扩展陆地遮罩（保留已画陆地像素）。"""
        mask = self._canvas.new_land_mask
        if not mask.any():
            return
        mask[:] = False
        self._status_info.setText(tr("status_extend_mask_cleared"))

    def _on_generate_provinces(self, count: int) -> None:
        incremental = False
        has_provinces = int(self._canvas.province_map.max()) > 0

        # R-NULL: 无省份时扩展遮罩无意义 — 自动清空避免误导
        if not has_provinces and self._canvas.new_land_mask.any():
            self._canvas.new_land_mask[:] = False
            self._status_info.setText(tr("status_no_prov_mask_ignored"))

        if has_provinces:
            reply = QMessageBox.question(
                self, tr("dlg_gen_mode_title"),
                tr("dlg_gen_mode_body"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes,
            )
            if reply == QMessageBox.StandardButton.Cancel:
                return
            incremental = (reply == QMessageBox.StandardButton.Yes)

        self._status_info.setText(tr("status_generating_bg"))
        QApplication.processEvents()

        # 从 Land 页面读取密度参数
        sea_scale = 0.15
        lake_scale = 0.3
        density_map = self._project.map_data.density_map
        if hasattr(self._tool_panel, '_land_page') and self._tool_panel._land_page is not None:
            params = self._tool_panel._land_page.get_generation_params()
            sea_scale = params.get("sea_scale", 0.15)
            lake_scale = params.get("lake_scale", 0.3)

        # 增量模式：用新大陆画笔的 mask 预清除像素
        province_map_for_thread = None
        if incremental:
            province_map_for_thread = self._canvas.province_map.copy()
            mask = self._canvas.new_land_mask
            if mask.any():
                # 保存副本供 _on_generate_done 同步 terrain，并立刻清空让用户可连画下一批
                self._new_land_mask_copy = mask.copy()
                province_map_for_thread[mask] = 0
                self._canvas.new_land_mask[:] = False

        has_new_land_mask = incremental and getattr(self, '_new_land_mask_copy', None) is not None and self._new_land_mask_copy.any()
        self._gen_thread = _GenerateThread(
            self._canvas.tile_map, count,
            province_map=province_map_for_thread,
            incremental=incremental,
            sea_scale=sea_scale,
            lake_scale=lake_scale,
            density_map=density_map,
            skip_mismatch_clear=has_new_land_mask,
        )
        self._gen_thread.finished.connect(self._on_generate_done)
        self._gen_thread.error.connect(self._on_generate_error)
        self._gen_thread.start()

    def _on_generate_done(self, province_map, count: int) -> None:
        was_incremental = getattr(self._gen_thread, '_incremental', False)
        self._canvas.province_map = province_map
        self._project.mark_dirty()
        self._update_province_count()

        # 发事件，级联清理由各 controller 自动处理
        self._event_bus.emit(
            "province_map_regenerated", incremental=was_incremental,
        )

        # 强制刷新画布（增量模式不切模式，保持新大陆画笔工具状态）
        self._canvas.refresh_display()

        # 增量生成后：同步 terrain + 清理被吞省份 + 自动分配 + 清空画笔 mask
        if was_incremental:
            import numpy as np
            from data.constants import TILE_LAND, TILE_SEA, TILE_LAKE
            from data.terrain_types import TERRAIN_PALETTE_INDEX, DEFAULT_TERRAIN_FOR_TILE

            # 同步 terrain_map（用保存的 mask 副本，不依赖 canvas.new_land_mask）
            saved_mask = getattr(self, '_new_land_mask_copy', None)
            if saved_mask is not None and saved_mask.any():
                tm = self._canvas.tile_map
                terrain_map = self._project.map_data.terrain_map
                for tile_type in (TILE_LAND, TILE_SEA, TILE_LAKE):
                    t_name = DEFAULT_TERRAIN_FOR_TILE.get(tile_type)
                    if t_name and t_name in TERRAIN_PALETTE_INDEX:
                        t_mask = saved_mask & (tm == tile_type)
                        if np.any(t_mask):
                            terrain_map[t_mask] = TERRAIN_PALETTE_INDEX[t_name]
                self._new_land_mask_copy = None

            consumed = self._cleanup_consumed_provinces(province_map)
            assigned = self._auto_assign_new_provinces(province_map)
            msg = tr("status_gen_done").format(count=count)
            msg += f" ({assigned} 个新省份已自动分配)"
            if consumed:
                ids_str = ", ".join(str(i) for i in sorted(consumed)[:10])
                if len(consumed) > 10:
                    ids_str += f" ... 共 {len(consumed)} 个"
                msg += f"\n⚠ 被完全吞并的省份: {ids_str}"
            self._status_info.setText(msg)
        else:
            self._status_info.setText(tr("status_gen_done").format(count=count))

    def _cleanup_consumed_provinces(self, province_map) -> set[int]:
        """清理被完全吞并的省份：从 state/country/战略区中移除不存在的省份引用。"""
        import numpy as np

        existing_pids = set(np.unique(province_map).tolist())
        existing_pids.discard(0)
        consumed: set[int] = set()

        state_mgr = self._project.state_mgr
        sr_mgr = self._project.strategic_region_mgr
        country_mgr = self._project.country_mgr

        # 清理 state 引用
        for sid, state in list(state_mgr.states.items()):
            old_provinces = state.provinces
            new_provinces = [p for p in old_provinces if p in existing_pids]
            removed = set(old_provinces) - set(new_provinces)
            if removed:
                consumed.update(removed)
                state.provinces = new_provinces
                if not new_provinces:
                    state_mgr.states.pop(sid, None)

        # 重建 province_to_state 索引
        if consumed and hasattr(state_mgr, '_province_to_state'):
            state_mgr._province_to_state = {
                pid: sid for sid, s in state_mgr.states.items()
                for pid in s.provinces
            }

        # 清理战略区引用
        if sr_mgr:
            for r in sr_mgr.regions.values():
                r.province_ids = [p for p in r.province_ids if p in existing_pids]

        # 清理国家首都引用
        if country_mgr:
            for tag, country in country_mgr.countries.items():
                if country.capital > 0 and country.capital not in existing_pids:
                    consumed.add(country.capital)
                    # 找该国其他省份作为新首都
                    new_cap = 0
                    owned_states = country_mgr.get_states_of_country(tag)
                    if state_mgr and owned_states:
                        for osid in owned_states:
                            s = state_mgr.get_state(osid)
                            if s and s.provinces:
                                new_cap = s.provinces[0]
                                break
                    country.capital = new_cap

        return consumed

    def _auto_assign_new_provinces(self, province_map) -> int:
        """增量生成后，把没有 state 的陆地省份分配到相邻最近的 state/战略区。"""
        import numpy as np
        from data.constants import TILE_LAND

        state_mgr = self._project.state_mgr
        sr_mgr = self._project.strategic_region_mgr
        tile_map = self._canvas.tile_map
        pm = province_map

        # 找未分配 state 的陆地省份
        max_pid = int(pm.max())
        if max_pid == 0:
            return 0

        assigned_count = 0
        # 预计算质心
        flat = pm.ravel()
        n = max_pid + 1
        pid_count = np.bincount(flat, minlength=n)
        ys, xs = np.mgrid[0:pm.shape[0], 0:pm.shape[1]]
        sum_y = np.bincount(flat, weights=ys.ravel().astype(np.float64), minlength=n)
        sum_x = np.bincount(flat, weights=xs.ravel().astype(np.float64), minlength=n)

        # 已有 state 的省份 → 质心
        state_centers: dict[int, tuple[float, float]] = {}  # state_id → (cy, cx)
        for sid, state in state_mgr.states.items():
            total_y, total_x, cnt = 0.0, 0.0, 0
            for p in state.provinces:
                if 0 < p < n and pid_count[p] > 0:
                    total_y += sum_y[p] / pid_count[p]
                    total_x += sum_x[p] / pid_count[p]
                    cnt += 1
            if cnt > 0:
                state_centers[sid] = (total_y / cnt, total_x / cnt)

        # 对每个未分配的陆地省份，找最近 state
        for pid in range(1, max_pid + 1):
            if pid_count[pid] == 0:
                continue
            # 检查是否陆地
            cy = int(sum_y[pid] / pid_count[pid])
            cx = int(sum_x[pid] / pid_count[pid])
            cy = min(cy, pm.shape[0] - 1)
            cx = min(cx, pm.shape[1] - 1)
            if int(tile_map[cy, cx]) != TILE_LAND:
                continue
            # 已有 state → 跳过
            if state_mgr.get_state_of_province(pid) > 0:
                continue

            # 找最近 state
            best_sid, best_dist = 0, float('inf')
            py = sum_y[pid] / pid_count[pid]
            px = sum_x[pid] / pid_count[pid]
            for sid, (sy, sx) in state_centers.items():
                d = (py - sy) ** 2 + (px - sx) ** 2
                if d < best_dist:
                    best_dist = d
                    best_sid = sid
            if best_sid > 0:
                state = state_mgr.get_state(best_sid)
                if state:
                    state.provinces.append(pid)
                    state_mgr._province_to_state[pid] = best_sid
                    assigned_count += 1

            # 战略区域也一样
            if sr_mgr.get_region_of_province(pid) == 0:
                # 找最近的战略区
                best_rid, best_dist = 0, float('inf')
                for rid, region in sr_mgr._regions.items():
                    if not region.province_ids:
                        continue
                    # 用第一个有像素的省份算距离
                    for rp in region.province_ids[:5]:
                        if 0 < rp < n and pid_count[rp] > 0:
                            ry = sum_y[rp] / pid_count[rp]
                            rx = sum_x[rp] / pid_count[rp]
                            d = (py - ry) ** 2 + (px - rx) ** 2
                            if d < best_dist:
                                best_dist = d
                                best_rid = rid
                            break
                if best_rid > 0:
                    sr_mgr._regions[best_rid].province_ids.append(pid)

        return assigned_count

    def _on_generate_error(self, msg: str) -> None:
        QMessageBox.critical(self, tr("dlg_error"), msg)
        self._status_info.setText(tr("status_ready"))

    def _on_smooth_coast(self) -> None:
        """平滑海岸线。有选区时只平滑选区内，否则全图。可撤销 (Ctrl+Z)。"""
        from domain.generators.coastline import smooth_coastline
        from commands.land.brush_stroke import BrushStrokeCommand
        map_data = self._project.map_data

        # 检查画布是否有选区（变换工具框选的区域）
        sel = getattr(self._canvas, '_selection_rect', None)
        has_provinces = int(self._canvas.province_map.max()) > 0

        # 已有省份时强警告：平滑会让 tile/province 边界错位
        if has_provinces:
            ret = QMessageBox.warning(
                self, tr("smooth_coast_after_gen_title"),
                tr("smooth_coast_after_gen_msg"),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if ret != QMessageBox.Yes:
                return
        elif not sel:
            # 无省份 + 全图：常规确认
            ret = QMessageBox.question(
                self, tr("smooth_coast_confirm_title"),
                tr("smooth_coast_confirm_msg"),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if ret != QMessageBox.Yes:
                return
        if sel:
            x0, y0, x1, y1 = sel
            # 转换为整数像素坐标 (region 参数是 y0, x0, y1, x1)
            region = (int(y0), int(x0), int(y1), int(x1))
        else:
            region = None

        # 撤销快照：操作前
        snap_arrays = {"tile_map": map_data.tile_map}
        before = BrushStrokeCommand.snapshot_arrays(snap_arrays)

        new_tile = smooth_coastline(map_data.tile_map, region=region)
        map_data.tile_map[:] = new_tile

        # 撤销快照：操作后 + 入栈
        if BrushStrokeCommand.has_changes(before, snap_arrays):
            after = BrushStrokeCommand.snapshot_arrays(snap_arrays)
            cmd = BrushStrokeCommand("平滑海岸线", before, after)
            cmd.set_target_arrays(self._app._get_all_arrays())
            self._cmd_history._undo_stack.append(cmd)
            self._cmd_history._redo_stack.clear()
            self._cmd_history._notify()

        self._canvas.tile_map = map_data.tile_map
        self._canvas._full_render()
        self._project.mark_dirty()
        if region:
            self._status_info.setText(tr("status_coast_smoothed_region"))
        else:
            self._status_info.setText(tr("status_coast_smoothed"))

    def _on_density_clear(self) -> None:
        """清除密度图，恢复均匀。密度遮罩保持当前显隐状态。"""
        # 防呆: 二次确认 (清空数据无法撤销)
        ret = QMessageBox.question(
            self, tr("density_clear_confirm_title"),
            tr("density_clear_confirm_msg"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ret != QMessageBox.Yes:
            return
        self._project.map_data.density_map = None
        # 刷新遮罩内容（density_map=None 时 overlay 会自动隐藏）
        self._canvas._render_density_overlay()
        self._status_info.setText(tr("status_density_cleared"))

    def _on_quick_init(self) -> None:
        """一键初始化：自动生成州 + 战略区域 + 默认国家。可撤销 (Ctrl+Z)。"""
        from commands.map.quick_init import QuickInitCommand
        pm = self._canvas.province_map
        if int(pm.max()) == 0:
            QMessageBox.warning(self, tr("dlg_quick_init_title"), tr("dlg_quick_init_no_provinces"))
            return

        reply = QMessageBox.question(
            self, tr("dlg_quick_init_title"),
            tr("dlg_quick_init_body"),
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._status_info.setText(tr("status_initializing"))
        QApplication.processEvents()

        # 撤销快照：操作前（捕获三个 manager 的初始状态）
        cmd = QuickInitCommand(
            self._project.state_mgr,
            self._project.country_mgr,
            self._project.strategic_region_mgr,
        )

        try:
            from views.export_dialog import auto_complete_project

            class _FakeCanvas:
                def __init__(self, md):
                    self.map_data = md
                    self.province_map = md.province_map
                    self.tile_map = md.tile_map
                    self.terrain_map = md.terrain_map
                    self.height_map = md.height_map
                    self.river_map = md.river_map

            fc = _FakeCanvas(self._project.map_data)
            log = auto_complete_project(self._project, fc)

            # 捕获 after 状态 + 推入撤销栈
            cmd.capture_after()
            self._cmd_history._undo_stack.append(cmd)
            self._cmd_history._redo_stack.clear()
            self._cmd_history._notify()

            self._canvas.refresh_display()
            msg = tr("dlg_quick_init_done") + "\n".join(f"- {l}" for l in log)
            self._status_info.setText(tr("status_init_done"))
            QMessageBox.information(self, tr("dlg_quick_init_title"), msg)
        except Exception as e:
            import traceback
            QMessageBox.critical(self, tr("dlg_init_failed"), f"{e}\n\n{traceback.format_exc()}")

    def _on_validate(self) -> None:
        self._status_info.setText(tr("status_validating"))
        QApplication.processEvents()

        self._validate_thread = _ValidateThread(
            self._canvas.tile_map, self._canvas.province_map
        )
        self._validate_thread.finished.connect(self._on_validate_done)
        self._validate_thread.error.connect(self._on_validate_error)
        self._validate_thread.start()

    def _on_validate_done(self, results: dict) -> None:
        self._show_validation_results(results)
        self._status_info.setText(tr("status_ready"))

    def _on_validate_error(self, msg: str) -> None:
        QMessageBox.critical(self, tr("dlg_error"), msg)
        self._status_info.setText(tr("status_ready"))

    def _show_validation_results(self, results: dict) -> None:
        """诊断对话框：可点击的问题列表，双击跳转"""
        from PyQt5.QtWidgets import (
            QDialog, QVBoxLayout, QListWidget, QListWidgetItem,
            QLabel, QDialogButtonBox,
        )
        from PyQt5.QtCore import Qt as _Qt

        dlg = QDialog(self)
        dlg.setWindowTitle(tr("validate_title"))
        dlg.resize(520, 520)
        v = QVBoxLayout(dlg)

        province_count = int(self._canvas.province_map.max())
        coastal_count = results.get("coastal_mismatch", 0)
        warn = results.get("count_warning", "")
        info_text = tr("validate_info").format(total=province_count, coastal=coastal_count)
        if warn:
            info_text += f"\n⚠ {warn}"
        v.addWidget(QLabel(info_text))

        v.addWidget(QLabel(tr("validate_double_click_hint")))
        list_w = QListWidget()
        v.addWidget(list_w)

        def add_item(text: str, jump_type: str, data) -> None:
            it = QListWidgetItem(text)
            it.setData(_Qt.ItemDataRole.UserRole, (jump_type, data))
            list_w.addItem(it)

        x_positions = results.get("x_crossing_positions", [])
        for i, (y, x) in enumerate(x_positions[:50]):
            add_item(f"X-crossing #{i+1} at ({x}, {y})", "xy", (x, y))
        if len(x_positions) > 50:
            add_item(tr("validate_more_xcrossing").format(n=len(x_positions)-50), "none", None)

        for pid in results.get("too_small_ids", [])[:50]:
            add_item(tr("validate_too_small_item").format(pid=pid), "pid", pid)
        for pid in results.get("not_contiguous_ids", [])[:50]:
            add_item(tr("validate_not_contiguous_item").format(pid=pid), "pid", pid)
        for pid in results.get("too_large_ids", [])[:50]:
            add_item(tr("validate_too_large_item").format(pid=pid), "pid", pid)
        gaps = results.get("id_gaps", [])
        if gaps:
            add_item(tr("validate_id_gaps").format(n=len(gaps)), "none", None)
        if list_w.count() == 0:
            list_w.addItem(tr("validate_no_issues"))

        def on_double(item: QListWidgetItem) -> None:
            payload = item.data(_Qt.ItemDataRole.UserRole)
            if not payload:
                return
            jump_type, data = payload
            if jump_type == "xy":
                self._canvas.center_on_pixel(data[0], data[1], zoom=4.0)
            elif jump_type == "pid":
                self._canvas.center_on_province(data)

        list_w.itemDoubleClicked.connect(on_double)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(dlg.reject)
        v.addWidget(btns)
        dlg.exec_()

    # ═══════════════════════ Country 对话框 ═══════════════════

    def _on_create_country(self) -> None:
        tag, ok = QInputDialog.getText(self, tr("country_create_btn"), tr("dlg_country_tag_prompt"))
        if not ok or not tag:
            return
        tag = tag.upper().strip()[:3]
        if len(tag) != 3 or not tag.isalpha():
            QMessageBox.warning(self, tr("dlg_error"), tr("country_tag_invalid"))
            return

        name, ok = QInputDialog.getText(self, tr("country_create_btn"), tr("dlg_country_name_prompt").format(tag=tag))
        if not ok:
            return

        import random
        default_color = QColor(
            random.randint(60, 220), random.randint(60, 220), random.randint(60, 220)
        )
        chosen = QColorDialog.getColor(default_color, self, tr("dlg_country_pick_color").format(tag=tag))
        if not chosen.isValid():
            return
        color = (chosen.red(), chosen.green(), chosen.blue())

        ctrl: CountryController = self._controllers["country"]
        if not ctrl.create_country(tag, name or tag, color):
            QMessageBox.warning(self, tr("dlg_error"), tr("dlg_country_create_failed"))

    def _on_quick_create_country(self, tag: str, name: str, party: str) -> None:
        color = getattr(self._tool_panel, '_quick_create_color', (100, 100, 200))
        ctrl: CountryController = self._controllers["country"]
        ctrl.create_country(tag, name, color, party)

    def _on_country_highlight(self, tag: str) -> None:
        """切换选中国家时, 把该国 RGB 传给 canvas, country renderer 会高亮该国像素."""
        if not tag:
            self._canvas.set_highlight_country(None)
            return
        country = self._project.country_mgr.get_country(tag)
        if country is None:
            self._canvas.set_highlight_country(None)
            return
        self._canvas.set_highlight_country(tuple(country.color))

    def _on_country_property_change(self, tag: str, prop: str, val) -> None:
        """修改国家属性。可撤销 (Ctrl+Z)。"""
        from commands.map.manager_snapshot import ManagerSnapshotCommand
        cm = self._project.country_mgr
        cmd = ManagerSnapshotCommand(
            f"修改 {tag} {prop}", cm,
            [f for f in ("_countries",) if hasattr(cm, f)],
        )
        self._controllers["country"].change_property(tag, prop, val)
        cmd.capture_after()
        self._cmd_history._undo_stack.append(cmd)
        self._cmd_history._redo_stack.clear()
        self._cmd_history._notify()

    def _on_country_color_change(self, tag: str) -> None:
        """修改国家颜色。可撤销 (Ctrl+Z)。"""
        from commands.map.manager_snapshot import ManagerSnapshotCommand
        country = self._project.country_mgr.get_country(tag)
        if not country:
            return
        r, g, b = country.color
        chosen = QColorDialog.getColor(QColor(r, g, b), self, tr("dlg_country_change_color").format(tag=tag))
        if not chosen.isValid():
            return
        cm = self._project.country_mgr
        cmd = ManagerSnapshotCommand(
            f"修改 {tag} 颜色", cm,
            [f for f in ("_countries",) if hasattr(cm, f)],
        )
        ctrl: CountryController = self._controllers["country"]
        ctrl.change_color(tag, (chosen.red(), chosen.green(), chosen.blue()))
        cmd.capture_after()
        self._cmd_history._undo_stack.append(cmd)
        self._cmd_history._redo_stack.clear()
        self._cmd_history._notify()

    # ═══════════════════════ River / Terrain / Height ═══════

    def _on_validate_river(self) -> None:
        from domain.managers.river import validate_rivers
        from ui.i18n import get_language
        warnings = validate_rivers(self._canvas.river_map, lang=get_language())
        QMessageBox.information(self, tr("dlg_river_validate_title"), "\n".join(warnings))

    def _on_auto_terrain(self) -> None:
        from services.terrain_service import smart_auto_terrain, TerrainGenConfig
        from commands.map.generate_terrain import GenerateTerrainCommand
        # 防呆: 二次确认 (会覆盖整张 terrain.bmp, 撤销才能恢复)
        ret = QMessageBox.question(
            self, tr("auto_terrain_confirm_title"),
            tr("auto_terrain_confirm_msg"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ret != QMessageBox.Yes:
            return
        self._status_info.setText(tr("status_auto_terrain"))
        self.repaint()
        map_data = self._project.map_data
        # 从 terrain page 获取配置 (如果有)
        config = None
        terrain_page = self._tool_panel._terrain_page
        if hasattr(terrain_page, 'get_gen_config'):
            config = terrain_page.get_gen_config()
        new_terrain = smart_auto_terrain(
            map_data.height_map, map_data.tile_map, config
        )
        cmd = GenerateTerrainCommand(map_data, new_terrain)
        self._cmd_history.execute(cmd)
        # 不再同步覆盖 provincial_terrain (省份属性是用户精挑细选的, 视觉自动生成不该改它).
        # 想从视觉同步到属性 → 切到 provincial_terrain mode 用专门的同步按钮.
        self._project.mark_dirty()
        # 自动生成地形 → colormap 要重生
        self._project.mark_assets_dirty(
            "map/terrain/colormap_rgb_cityemissivemask_a.dds",
        )
        self._canvas.terrain_map = map_data.terrain_map
        self._status_info.setText(tr("status_auto_terrain_done"))

    def _on_realistic_height(self) -> None:
        """一键生成真实感高度图 — 生成器 2 号 (山链/平原/大陆架)。

        每次点击换随机种子 (不满意再点一次即重洗); 可撤销。
        """
        import random
        from domain.generators.heightmap import (
            RealisticHeightmapGenerator, HeightmapParams)
        from commands.map.apply_generator import ApplyGeneratorCommand
        ret = QMessageBox.question(
            self, tr("realistic_height_confirm_title"),
            tr("realistic_height_confirm_msg"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ret != QMessageBox.Yes:
            return
        self._status_info.setText(tr("status_realistic_height"))
        self.repaint()
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtCore import Qt
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            map_data = self._project.map_data
            gen = RealisticHeightmapGenerator()
            seed = random.randrange(100000)
            new_height = gen.generate(map_data, HeightmapParams(seed=seed))
            cmd = ApplyGeneratorCommand(
                map_data, gen.target_layer, new_height,
                label=tr("realistic_height_confirm_title"))
            self._cmd_history.execute(cmd)
        finally:
            QApplication.restoreOverrideCursor()
        self._project.mark_dirty()
        from features.map.preview import renderer as preview_renderer
        preview_renderer.invalidate_cache(self._canvas)
        self._canvas.height_map = map_data.height_map
        self._status_info.setText(
            tr("status_realistic_height_done").format(seed=seed))

    def _on_detail_terrain(self, seed: int) -> None:
        """按气候自动细化地形 — 路线 C 生成器的首个 UI 接入。

        纬度气候带 (丛林/沙漠/森林/雪原) + 海拔叠加 (丘陵/山地/雪线)
        + 噪声斑块。可撤销; 同种子可复现, 换种子重新生成。
        """
        from domain.generators.terrain_detail import (
            TerrainDetailGenerator, TerrainDetailParams)
        from commands.map.generate_terrain import GenerateTerrainCommand
        ret = QMessageBox.question(
            self, tr("detail_terrain_confirm_title"),
            tr("detail_terrain_confirm_msg"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ret != QMessageBox.Yes:
            return
        self._status_info.setText(tr("status_detail_terrain"))
        self.repaint()
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtCore import Qt
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            map_data = self._project.map_data
            gen = TerrainDetailGenerator()
            new_terrain = gen.generate(map_data, TerrainDetailParams(seed=seed))
            cmd = GenerateTerrainCommand(map_data, new_terrain)
            cmd.label = tr("detail_terrain_confirm_title")
            self._cmd_history.execute(cmd)
        finally:
            QApplication.restoreOverrideCursor()
        self._project.mark_dirty()
        # 地形变了 → colormap 资产要重生, 预览缓存作废
        self._project.mark_assets_dirty(
            "map/terrain/colormap_rgb_cityemissivemask_a.dds",
        )
        from features.map.preview import renderer as preview_renderer
        preview_renderer.invalidate_cache(self._canvas)
        self._canvas.terrain_map = map_data.terrain_map
        self._status_info.setText(tr("status_detail_terrain_done"))

    def _on_beautify_terrain(self, seed: int) -> None:
        """保形美化地形: 作者画的布局不变, 按原版实测参数上细节。"""
        from domain.generators.terrain_beautify import (
            TerrainBeautifyGenerator, TerrainBeautifyParams)
        from commands.map.generate_terrain import GenerateTerrainCommand
        ret = QMessageBox.question(
            self, tr("beautify_terrain_confirm_title"),
            tr("beautify_terrain_confirm_msg"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ret != QMessageBox.Yes:
            return
        self._status_info.setText(tr("status_beautify_terrain"))
        self.repaint()
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtCore import Qt
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            map_data = self._project.map_data
            gen = TerrainBeautifyGenerator()
            new_terrain = gen.generate(map_data, TerrainBeautifyParams(seed=seed))
            cmd = GenerateTerrainCommand(map_data, new_terrain)
            cmd.label = tr("beautify_terrain_confirm_title")
            self._cmd_history.execute(cmd)
        finally:
            QApplication.restoreOverrideCursor()
        self._project.mark_dirty()
        self._project.mark_assets_dirty(
            "map/terrain/colormap_rgb_cityemissivemask_a.dds",
        )
        from features.map.preview import renderer as preview_renderer
        preview_renderer.invalidate_cache(self._canvas)
        self._canvas.terrain_map = map_data.terrain_map
        self._status_info.setText(tr("status_beautify_terrain_done"))

    def _on_downgrade_mountain(self, mask=None) -> None:
        """降级山脉 (全图或选区)。mask=None 时全图, 否则只在 mask 内。"""
        from commands.map.downgrade_mountain import DowngradeMountainCommand
        # 防呆: 全图模式才弹窗 (选区是用户已经画了套索, 意图明确)
        if mask is None:
            ret = QMessageBox.question(
                self, tr("downgrade_mountain_confirm_title"),
                tr("downgrade_mountain_confirm_msg"),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if ret != QMessageBox.Yes:
                return
        map_data = self._project.map_data
        strength = self._tool_panel._terrain_page.get_downgrade_strength()
        cmd = DowngradeMountainCommand(map_data, mask=mask, strength=strength)
        self._cmd_history.execute(cmd)
        self._canvas.terrain_map = map_data.terrain_map
        self._canvas.height_map = map_data.height_map
        self._canvas._full_render()
        self._project.mark_dirty()
        self._project.mark_assets_dirty(
            "map/terrain/colormap_rgb_cityemissivemask_a.dds",
        )
        self._project.mark_assets_dirty(
            "map/terrain/world_normal.bin",
        )
        self._status_info.setText(tr("status_downgrade_done"))

    def _on_downgrade_lasso_mode(self, enabled: bool) -> None:
        """切换选区降级套索模式。"""
        self._canvas._downgrade_lasso_mode = enabled
        if enabled:
            self._status_info.setText(tr("status_downgrade_lasso_mode"))
        else:
            self._canvas._refine_lasso_item.setVisible(False)

    def _on_terrain_underlay_toggle(self, enabled: bool) -> None:
        """国家/州模式下的地形底图开关 — 画边界时参考海岸/山脉。"""
        self._canvas.set_terrain_underlay_visible(bool(enabled))

    def _on_terrain_underlay_opacity(self, value: int) -> None:
        """滑块 0..100 → 0.0..1.0 不透明度。"""
        self._canvas.set_terrain_underlay_opacity(value / 100.0)

    def _on_terrain_underlay_source(self, source: str) -> None:
        """切换地形底图源: 'height' (彩色高度图) 或 'terrain' (地形属性 provincial_terrain)."""
        if source == "terrain":
            # 确保 provincial_terrain RGB 已构建 (用户可能从未进过 province_terrain mode)
            if getattr(self._canvas, "_provincial_terrain_color_rgb", None) is None:
                app_ctrl = self._controllers.get("app")
                if app_ctrl is not None and hasattr(app_ctrl, "_refresh_provincial_terrain_colors"):
                    app_ctrl._refresh_provincial_terrain_colors()
        self._canvas.set_terrain_underlay_source(source)

    def _on_terrain_context_overlay(self, enabled: bool) -> None:
        """地形视图下显示/隐藏 国家色 + 州边界 叠加层。

        开启时：缓存 mgrs + 订阅 state_changed/country_changed → 自动重绘（去抖 80ms）。
        关闭时：取消订阅 + 隐藏。
        """
        if enabled:
            self._canvas.show_terrain_context_overlay(
                True,
                country_mgr=self._project.country_mgr,
                state_mgr=self._project.state_mgr,
            )
            bus = getattr(self._project, "event_bus", None)
            if bus is not None:
                bus.subscribe("state_changed", self._on_terrain_ctx_data_changed)
                bus.subscribe("country_changed", self._on_terrain_ctx_data_changed)
                bus.subscribe("province_map_changed", self._on_terrain_ctx_data_changed)
        else:
            self._canvas.show_terrain_context_overlay(False)
            bus = getattr(self._project, "event_bus", None)
            if bus is not None:
                bus.unsubscribe("state_changed", self._on_terrain_ctx_data_changed)
                bus.unsubscribe("country_changed", self._on_terrain_ctx_data_changed)
                bus.unsubscribe("province_map_changed", self._on_terrain_ctx_data_changed)

    def _on_terrain_ctx_data_changed(self, _event) -> None:
        """State/Country 数据变化 → 去抖刷新 overlay (避免拖拽批量修改时卡顿)。"""
        from PyQt5.QtCore import QTimer
        timer = getattr(self, "_terrain_ctx_refresh_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(80)
            timer.timeout.connect(self._refresh_terrain_ctx_overlay_now)
            self._terrain_ctx_refresh_timer = timer
        timer.start()

    def _refresh_terrain_ctx_overlay_now(self) -> None:
        """实际执行 overlay 刷新（被 QTimer 触发）。"""
        if getattr(self._canvas, "_terrain_context_visible", False):
            # 项目可能已重新加载，重新缓存 mgrs
            self._canvas.show_terrain_context_overlay(
                True,
                country_mgr=self._project.country_mgr,
                state_mgr=self._project.state_mgr,
            )

    def _on_downgrade_lasso_drawn(self, points: list) -> None:
        """套索画完 → 多边形转 mask → 调 _on_downgrade_mountain(mask)。"""
        from PyQt5.QtWidgets import QMessageBox
        map_data = self._project.map_data
        h, w = map_data.terrain_map.shape
        mask = _polygon_to_mask(points, h, w)
        if mask.sum() < 400:
            QMessageBox.information(
                self, tr("terrain_btn_downgrade_region"),
                tr("refine_dlg_area_too_small"),
            )
            self._tool_panel._terrain_page.reset_downgrade_lasso_button()
            return
        self._on_downgrade_mountain(mask=mask)
        self._tool_panel._terrain_page.reset_downgrade_lasso_button()

    def _on_auto_height(self) -> None:
        """自动生成高度图（覆盖整图）。可撤销 (Ctrl+Z)。"""
        from services.terrain_service import smart_auto_height
        from commands.land.brush_stroke import BrushStrokeCommand
        # 防呆: 二次确认 (覆盖整张高度图)
        ret = QMessageBox.question(
            self, tr("auto_height_confirm_title"),
            tr("auto_height_confirm_msg"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ret != QMessageBox.Yes:
            return
        self._status_info.setText(tr("status_auto_height"))
        self.repaint()
        config = None
        height_page = self._tool_panel._height_page
        if hasattr(height_page, 'get_height_config'):
            config = height_page.get_height_config()
        map_data = self._project.map_data

        # 撤销快照：操作前
        snap_arrays = {"height_map": map_data.height_map}
        before = BrushStrokeCommand.snapshot_arrays(snap_arrays)

        new_height = smart_auto_height(map_data.tile_map, config)
        # 同时更新 map_data 和 canvas (两边共享同一个数组)
        map_data.height_map[:] = new_height
        self._canvas.height_map = map_data.height_map

        # 撤销快照：操作后 + 入栈
        if BrushStrokeCommand.has_changes(before, snap_arrays):
            after = BrushStrokeCommand.snapshot_arrays(snap_arrays)
            cmd = BrushStrokeCommand("自动生成高度图", before, after)
            cmd.set_target_arrays(self._app._get_all_arrays())
            self._cmd_history._undo_stack.append(cmd)
            self._cmd_history._redo_stack.clear()
            self._cmd_history._notify()

        self._project.mark_dirty()
        # 自动生成高度 → world_normal / colormap 要重生
        self._project.mark_assets_dirty(
            "map/world_normal.bmp",
            "map/terrain/colormap_rgb_cityemissivemask_a.dds",
        )
        self._status_info.setText(tr("status_auto_height_done"))

    def _on_height_from_terrain(self) -> None:
        """从 terrain 反推 height_map (覆盖现有). 优先用省份属性 (provincial_terrain),
        fallback 到像素装饰 (terrain_map). HOI4 实际游戏用省份属性."""
        from services.terrain_service import auto_height_from_terrain
        map_data = self._project.map_data
        has_prov_terrain = bool(map_data.provincial_terrain)
        has_terrain = map_data.terrain_map is not None and int(map_data.terrain_map.max()) > 0
        if not has_prov_terrain and not has_terrain:
            QMessageBox.warning(self, tr("dlg_warning"), tr("height_from_terrain_no_terrain"))
            return
        ret = QMessageBox.question(
            self, tr("height_from_terrain_confirm_title"),
            tr("height_from_terrain_confirm_msg"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ret != QMessageBox.Yes:
            return
        self._status_info.setText(tr("status_height_from_terrain"))
        self.repaint()
        new_height = auto_height_from_terrain(
            map_data.terrain_map, map_data.tile_map,
            provincial_terrain=map_data.provincial_terrain,
            province_map=map_data.province_map,
        )
        map_data.height_map[:] = new_height
        self._canvas.height_map = map_data.height_map
        self._project.mark_dirty()
        self._project.mark_assets_dirty(
            "map/world_normal.bmp",
            "map/terrain/colormap_rgb_cityemissivemask_a.dds",
        )
        self._status_info.setText(tr("status_height_from_terrain_done"))

    def _on_smooth_height(self) -> None:
        from services.terrain_service import smooth_height
        self._canvas.height_map = smooth_height(
            self._canvas.height_map, self._canvas.tile_map
        )
        self._status_info.setText(tr("status_height_smoothed"))

    def _on_import_heightmap(self) -> None:
        """导入高度图（覆盖整图）。可撤销 (Ctrl+Z)。"""
        from PyQt5.QtWidgets import QFileDialog
        from commands.land.brush_stroke import BrushStrokeCommand
        path, _ = QFileDialog.getOpenFileName(
            self, tr("height_import_btn"),
            "", "Images (*.bmp *.png *.jpg *.tif);;All Files (*)"
        )
        if not path:
            return
        # 防呆: 二次确认 (覆盖整张高度图, 建议先保存项目)
        ret = QMessageBox.question(
            self, tr("import_heightmap_confirm_title"),
            tr("import_heightmap_confirm_msg"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ret != QMessageBox.Yes:
            return
        try:
            from PIL import Image
            import numpy as np
            img = Image.open(path).convert("L")
            map_data = self._project.map_data
            h, w = map_data.height_map.shape
            img = img.resize((w, h), Image.BILINEAR)
            new_height = np.array(img, dtype=np.uint8)

            # 撤销快照：操作前
            snap_arrays = {"height_map": map_data.height_map}
            before = BrushStrokeCommand.snapshot_arrays(snap_arrays)

            map_data.height_map[:] = new_height
            self._canvas.height_map = map_data.height_map

            # 入栈
            if BrushStrokeCommand.has_changes(before, snap_arrays):
                after = BrushStrokeCommand.snapshot_arrays(snap_arrays)
                cmd = BrushStrokeCommand("导入高度图", before, after)
                cmd.set_target_arrays(self._app._get_all_arrays())
                self._cmd_history._undo_stack.append(cmd)
                self._cmd_history._redo_stack.clear()
                self._cmd_history._notify()

            self._canvas.refresh_display()
            self._project.mark_dirty()
            self._status_info.setText(tr("height_import_success"))
        except Exception as e:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, tr("dlg_error"), tr("height_import_fail", str(e)))

    # ── 山脉画线 ──

    def _on_ridge_mode(self, enabled: bool) -> None:
        """切换山脉画线模式 — 同步到 canvas。"""
        self._ridge_mode = enabled
        self._canvas._ridge_mode = enabled
        if enabled:
            self._status_info.setText(tr("status_ridge_mode_on"))
        else:
            # 退出模式时取消预览
            if hasattr(self, '_ridge_backup'):
                self._on_ridge_cancel()
            self._status_info.setText(tr("status_ridge_mode_off"))

    def _on_ridge_drawn(self, points: list) -> None:
        """canvas 画线完成 → 进入预览模式（不立即应用）。"""
        if len(points) < 2:
            return
        # 间隔采样
        if len(points) > 100:
            step = len(points) // 100
            points = points[::step] + [points[-1]]

        # 保存原始高度图 + 画线路径
        self._ridge_backup = self._project.map_data.height_map.copy()
        self._ridge_points = points

        # 显示确认/取消按钮
        self._tool_panel._height_page.show_ridge_confirm()

        # 立即生成预览
        self._apply_ridge_preview()
        self._status_info.setText(tr("status_ridge_preview"))

    def _apply_ridge_preview(self) -> None:
        """用当前参数生成山脉预览（不修改 backup）。"""
        if not hasattr(self, '_ridge_backup') or self._ridge_backup is None:
            return
        from services.terrain_service import apply_mountain_ridge
        map_data = self._project.map_data
        peak = getattr(self, '_ridge_peak', 220)
        falloff = getattr(self, '_ridge_falloff', 80)

        preview = apply_mountain_ridge(
            self._ridge_backup, map_data.tile_map,
            self._ridge_points, peak_height=peak, falloff_distance=float(falloff),
        )
        map_data.height_map[:] = preview
        self._canvas.height_map = map_data.height_map
        self._canvas._full_render()

    def _on_ridge_preview(self) -> None:
        """滑块变化 → 刷新预览。"""
        self._apply_ridge_preview()

    def _on_ridge_confirm(self) -> None:
        """确认山脉 → 应用到高度图，清理预览状态。"""
        self._ridge_backup = None
        self._ridge_points = None
        self._tool_panel._height_page.hide_ridge_confirm()
        # 线已经画在 canvas 上，隐藏它
        self._canvas._split_line_item.setVisible(False)
        self._project.mark_dirty()
        self._status_info.setText(tr("status_ridge_applied"))

    def _on_ridge_cancel(self) -> None:
        """取消山脉 → 恢复原始高度图。"""
        if hasattr(self, '_ridge_backup') and self._ridge_backup is not None:
            self._project.map_data.height_map[:] = self._ridge_backup
            self._canvas.height_map = self._project.map_data.height_map
            self._canvas._full_render()
        self._ridge_backup = None
        self._ridge_points = None
        self._tool_panel._height_page.hide_ridge_confirm()
        self._canvas._split_line_item.setVisible(False)
        self._status_info.setText(tr("status_ridge_mode_on"))

    # ── 局部精修（套索选区） ──

    def _on_refine_lasso_mode(self, enabled: bool) -> None:
        """切换局部精修套索模式 — 同步到 canvas。"""
        self._canvas._refine_lasso_mode = enabled
        if enabled:
            self._status_info.setText(tr("status_refine_mode"))
        else:
            self._canvas._refine_lasso_item.setVisible(False)

    def _on_refine_lasso_drawn(self, points: list) -> None:
        """canvas 套索完成 → mask → 弹参数对话框 → 执行 Command。"""
        import numpy as np
        from features.map.height.refine_dialog import RefineDialog
        from commands.map.refine_height_region import RefineHeightRegionCommand
        from PyQt5.QtWidgets import QMessageBox

        # 把 [(y,x), ...] 转成闭合多边形 mask
        map_data = self._project.map_data
        h, w = map_data.height_map.shape
        mask = _polygon_to_mask(points, h, w)

        # 面积太小（<20x20 = 400）直接拒绝
        if mask.sum() < 400:
            QMessageBox.information(
                self, tr("refine_dlg_title"), tr("refine_dlg_area_too_small")
            )
            self._tool_panel._height_page.reset_refine_button()
            return

        self._run_refine_dialog(mask)
        self._tool_panel._height_page.reset_refine_button()

    def _on_refine_whole_map(self) -> None:
        """保形精修整张高度图: 你画的布局(哪高哪低)不变, 全图叠加质感。

        mask = 全图: 陆地走保形精修, 海底则无条件重建为大陆架坡度
        (海底不是创作内容, 混乱遗留数据由算法接管)。
        对话框里勾"从零重新生成"则变成全图重做 (等价一键生成)。
        """
        import numpy as np
        from data.constants import TILE_LAND
        map_data = self._project.map_data
        if not bool((map_data.tile_map == TILE_LAND).any()):
            QMessageBox.information(
                self, tr("refine_dlg_title"), tr("refine_whole_no_land"))
            return
        mask = np.ones(map_data.tile_map.shape, dtype=bool)
        self._run_refine_dialog(mask)

    def _run_refine_dialog(self, mask) -> None:
        """打开精修参数对话框并执行 (局部套索 / 全图共用)。"""
        import numpy as np
        from features.map.height.refine_dialog import RefineDialog
        from commands.map.refine_height_region import RefineHeightRegionCommand

        map_data = self._project.map_data
        # 备份原图供对话框预览使用
        original = map_data.height_map.copy()

        dlg = RefineDialog(
            self,
            height_map=original,
            mask=mask,
            tile_map=map_data.tile_map,
        )
        # 预览：实时把 new_height 灌回 canvas
        def _update_preview(new_hm: np.ndarray) -> None:
            map_data.height_map[:] = new_hm
            self._canvas.height_map = map_data.height_map
            self._canvas._full_render()
        dlg.preview_updated.connect(_update_preview)

        accepted = dlg.exec_() == dlg.DialogCode.Accepted

        # 对话框结束后先恢复原图（一致起点），再按需 push command
        map_data.height_map[:] = original
        self._canvas.height_map = map_data.height_map

        if accepted:
            cmd = RefineHeightRegionCommand(map_data, mask, dlg.params)
            self._cmd_history.execute(cmd)
            from features.map.preview import renderer as preview_renderer
            preview_renderer.invalidate_cache(self._canvas)
            self._canvas.height_map = map_data.height_map
            self._canvas._full_render()
            self._project.mark_dirty()
            self._status_info.setText(tr("status_refine_done"))
        else:
            self._canvas._full_render()
            self._status_info.setText(tr("status_ready"))

    # ═══════════════════════ Continent ═══════════════════════

    def _on_continent_pick_toggled(self, on: bool) -> None:
        from controllers.continent import ContinentController
        ctrl: ContinentController = self._controllers["continent"]
        if on:
            item = self._tool_panel._continent_list.currentItem()
            if item is None:
                self._tool_panel._continent_pick_btn.setChecked(False)
                return
            row = self._tool_panel._continent_list.currentRow()
            ctrl.toggle_pick(True, row)
        else:
            ctrl.toggle_pick(False)

    def _on_continent_add(self, name: str) -> None:
        """添加大洲。可撤销 (Ctrl+Z)。"""
        from controllers.continent import ContinentController
        from commands.map.manager_snapshot import ManagerSnapshotCommand
        ctrl: ContinentController = self._controllers["continent"]
        cm = self._project.continent_mgr
        cmd = ManagerSnapshotCommand(
            "添加大洲", cm,
            [f for f in ("_names", "_province_continent") if hasattr(cm, f)],
        )
        if ctrl.add_continent(name):
            cmd.capture_after()
            self._cmd_history._undo_stack.append(cmd)
            self._cmd_history._redo_stack.clear()
            self._cmd_history._notify()
            self._refresh_continent_list()
        else:
            QMessageBox.warning(self, tr("dlg_error"), tr("dlg_continent_add_failed"))

    def _on_continent_rename(self, index: int, name: str) -> None:
        """重命名大洲。可撤销 (Ctrl+Z)。"""
        from controllers.continent import ContinentController
        from commands.map.manager_snapshot import ManagerSnapshotCommand
        ctrl: ContinentController = self._controllers["continent"]
        cm = self._project.continent_mgr
        cmd = ManagerSnapshotCommand(
            "重命名大洲", cm,
            [f for f in ("_names",) if hasattr(cm, f)],
        )
        if ctrl.rename_continent(index, name):
            cmd.capture_after()
            self._cmd_history._undo_stack.append(cmd)
            self._cmd_history._redo_stack.clear()
            self._cmd_history._notify()
            self._refresh_continent_list()
        else:
            QMessageBox.warning(self, tr("dlg_error"), tr("dlg_continent_rename_failed"))

    def _on_continent_remove(self, index: int) -> None:
        """删除大洲。可撤销 (Ctrl+Z)。"""
        from controllers.continent import ContinentController
        from commands.map.manager_snapshot import ManagerSnapshotCommand
        ctrl: ContinentController = self._controllers["continent"]
        cm = self._project.continent_mgr
        cmd = ManagerSnapshotCommand(
            "删除大洲", cm,
            [f for f in ("_names", "_province_continent") if hasattr(cm, f)],
        )
        if ctrl.remove_continent(index):
            cmd.capture_after()
            self._cmd_history._undo_stack.append(cmd)
            self._cmd_history._redo_stack.clear()
            self._cmd_history._notify()
            self._refresh_continent_list()
        else:
            QMessageBox.warning(self, tr("dlg_error"), tr("dlg_continent_delete_failed"))

    def _refresh_continent_list(self) -> None:
        from PyQt5.QtWidgets import QListWidgetItem
        lst = self._tool_panel._continent_list
        lst.clear()
        cm = self._project.continent_mgr
        for i, name in enumerate(cm.names):
            count = sum(1 for ci in cm._province_continent.values() if ci == i)
            item = QListWidgetItem(f"{i+1}. {name}  ({count} {tr('unit_provinces')})")
            item.setData(Qt.UserRole, name)
            lst.addItem(item)

    # ═══════════════════════ Strategic Region ═══════════════

    def _on_sr_pick_toggled(self, on: bool) -> None:
        ctrl = self._controllers["strategic_region"]
        if on:
            lst = self._tool_panel._sr_list
            item = lst.currentItem()
            if item is None:
                self._tool_panel._sr_pick_btn.setChecked(False)
                return
            rid = int(item.data(Qt.UserRole) or 0)
            ctrl.toggle_pick(True, rid)
        else:
            ctrl.toggle_pick(False)

    def _track_sr_op(self, label: str):
        """工厂方法：为 sr_mgr 当前状态创建 snapshot Command（操作后调 cmd.capture_after()+ push）。"""
        from commands.map.manager_snapshot import ManagerSnapshotCommand
        sr_mgr = self._project.strategic_region_mgr
        return ManagerSnapshotCommand(
            label, sr_mgr,
            [f for f in ("_regions", "_next_id") if hasattr(sr_mgr, f)],
        )

    def _commit_cmd(self, cmd) -> None:
        """通用：snapshot 操作 capture_after + push 撤销栈。"""
        cmd.capture_after()
        self._cmd_history._undo_stack.append(cmd)
        self._cmd_history._redo_stack.clear()
        self._cmd_history._notify()

    def _on_sr_new(self) -> None:
        """新建战略区。可撤销 (Ctrl+Z)。"""
        cmd = self._track_sr_op("新建战略区")
        self._controllers["strategic_region"].create_region()
        self._commit_cmd(cmd)
        self._refresh_sr_list()

    def _on_sr_delete(self) -> None:
        """删除战略区。可撤销 (Ctrl+Z)。"""
        lst = self._tool_panel._sr_list
        item = lst.currentItem()
        if item is None:
            return
        rid = int(item.data(Qt.UserRole) or 0)
        cmd = self._track_sr_op(f"删除战略区 #{rid}")
        self._controllers["strategic_region"].delete_region(rid)
        self._commit_cmd(cmd)
        self._refresh_sr_list()

    def _get_sr_current_rid(self) -> int:
        lst = self._tool_panel._sr_list
        item = lst.currentItem()
        return int(item.data(Qt.UserRole) or 0) if item else 0

    def _on_sr_selected(self, row: int) -> None:
        lst = self._tool_panel._sr_list
        item = lst.item(row)
        if item is None:
            return
        rid = int(item.data(Qt.UserRole) or 0)
        r = self._project.strategic_region_mgr.get(rid)
        if r is None:
            return
        # 高亮该区域所有省份
        self._controllers["strategic_region"].select_region(rid)
        # 更新编辑字段
        self._tool_panel._sr_name_edit.blockSignals(True)
        # 旧数据 name 可能是 STRATEGICREGION_{id} 形式，显示为空让用户填
        display_name = r.name if (r.name and r.name != f"STRATEGICREGION_{rid}") else ""
        self._tool_panel._sr_name_edit.setText(display_name)
        self._tool_panel._sr_name_edit.blockSignals(False)
        self._tool_panel._sr_name_en_edit.blockSignals(True)
        self._tool_panel._sr_name_en_edit.setText(getattr(r, "name_en", "") or "")
        self._tool_panel._sr_name_en_edit.blockSignals(False)
        idx = self._tool_panel._sr_weather_combo.findData(r.weather_preset)
        if idx >= 0:
            self._tool_panel._sr_weather_combo.blockSignals(True)
            self._tool_panel._sr_weather_combo.setCurrentIndex(idx)
            self._tool_panel._sr_weather_combo.blockSignals(False)
        nidx = self._tool_panel._sr_naval_combo.findData(r.naval_terrain or "")
        if nidx >= 0:
            self._tool_panel._sr_naval_combo.blockSignals(True)
            self._tool_panel._sr_naval_combo.setCurrentIndex(nidx)
            self._tool_panel._sr_naval_combo.blockSignals(False)
        self._tool_panel._sr_prov_count.setText(tr("sr_prov_count").format(len(r.province_ids)))

    def _on_sr_name_changed(self, name: str) -> None:
        """改战略区名称。可撤销 (Ctrl+Z)。"""
        rid = self._get_sr_current_rid()
        if rid <= 0:
            return
        cmd = self._track_sr_op(f"改战略区 #{rid} 名称")
        self._controllers["strategic_region"].set_name(rid, name)
        self._commit_cmd(cmd)
        self._refresh_sr_list()

    def _on_sr_name_en_changed(self, name_en: str) -> None:
        """改战略区英文名。可撤销 (Ctrl+Z)。"""
        rid = self._get_sr_current_rid()
        if rid <= 0:
            return
        r = self._project.strategic_region_mgr.get(rid)
        if r is None:
            return
        cmd = self._track_sr_op(f"改战略区 #{rid} 英文名")
        r.name_en = name_en
        self._commit_cmd(cmd)

    def _on_sr_weather_changed(self, preset: str) -> None:
        """改战略区天气。可撤销 (Ctrl+Z)。"""
        rid = self._get_sr_current_rid()
        if rid <= 0:
            return
        cmd = self._track_sr_op(f"改战略区 #{rid} 天气")
        self._controllers["strategic_region"].set_weather(rid, preset)
        self._commit_cmd(cmd)

    def _on_sr_naval_changed(self, naval: str) -> None:
        """改战略区海军地形。可撤销 (Ctrl+Z)。"""
        rid = self._get_sr_current_rid()
        if rid <= 0:
            return
        cmd = self._track_sr_op(f"改战略区 #{rid} 海军地形")
        self._controllers["strategic_region"].set_naval(rid, naval)
        self._commit_cmd(cmd)

    def _refresh_sr_list(self) -> None:
        from PyQt5.QtWidgets import QListWidgetItem
        from domain.managers.strategic_region import PRESET_LABELS
        lst = self._tool_panel._sr_list
        lst.clear()
        for r in sorted(self._project.strategic_region_mgr.regions.values(), key=lambda x: x.id):
            label = (
                f"#{r.id} {r.name}  ({len(r.province_ids)}{tr('unit_provinces')}, "
                f"{PRESET_LABELS.get(r.weather_preset, r.weather_preset)})"
            )
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, r.id)
            lst.addItem(item)

    # ═══════════════════════ Logistics 对话框 ═══════════════

    _adjacency_dialog = None
    _railway_dialog = None
    _adjacency_rule_dialog = None

    def _open_adjacency_dialog(self) -> None:
        if self._adjacency_dialog is not None:
            self._adjacency_dialog.raise_()
            self._adjacency_dialog.activateWindow()
            return
        from features.map.logistics.adjacency_dialog import AdjacencyDialog
        dlg = AdjacencyDialog(
            self._project.adjacency_mgr, parent=self,
            province_map=self._canvas.province_map,
            tile_map=self._canvas.tile_map,
        )
        dlg.pick_mode_changed.connect(self._on_adjacency_pick_mode)
        dlg.finished.connect(self._on_adjacency_dialog_closed)
        self._adjacency_dialog = dlg
        dlg.show()

    def _on_adjacency_pick_mode(self, on: bool, target: str) -> None:
        ctrl: LogisticsController = self._controllers["logistics"]
        ctrl.set_adjacency_pick(on, target)

    def _on_adjacency_dialog_closed(self, *_args) -> None:
        self._adjacency_dialog = None
        ctrl: LogisticsController = self._controllers["logistics"]
        if ctrl.pick_target and ctrl.pick_target.startswith("adj_"):
            ctrl.pick_target = None

    def _open_railway_dialog(self) -> None:
        if self._railway_dialog is not None:
            self._railway_dialog.raise_()
            self._railway_dialog.activateWindow()
            return
        from features.map.logistics.railway_dialog import RailwayDialog
        dlg = RailwayDialog(self._project.railway_mgr, parent=self)
        dlg.finished.connect(self._on_railway_dialog_closed)
        self._railway_dialog = dlg
        dlg.show()

    def _on_railway_dialog_closed(self, *_args) -> None:
        self._railway_dialog = None

    # ═══════════════════════ Default Map ═══════════════════

    def _on_dm_tree_add(self) -> None:
        v, ok = QInputDialog.getInt(
            self, tr("defmap_add_btn"), tr("dlg_defmap_palette_prompt"), value=4, min=1, max=13
        )
        if ok:
            ctrl: DefaultMapController = self._controllers["default_map"]
            if ctrl.add_tree_index(v):
                self._refresh_dm_tree_list()

    def _on_dm_tree_del(self) -> None:
        lst = self._tool_panel._dm_tree_list
        row = lst.currentRow()
        ctrl: DefaultMapController = self._controllers["default_map"]
        if ctrl.remove_tree_index(row):
            self._refresh_dm_tree_list()

    def _on_dm_tree_reset(self) -> None:
        # 防呆: 二次确认 (重置 tree 设置)
        ret = QMessageBox.question(
            self, tr("default_map_reset_confirm_title"),
            tr("default_map_reset_confirm_msg"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ret != QMessageBox.Yes:
            return
        ctrl: DefaultMapController = self._controllers["default_map"]
        ctrl.reset_tree_indices()
        self._refresh_dm_tree_list()

    def _refresh_dm_tree_list(self) -> None:
        from PyQt5.QtWidgets import QListWidgetItem
        lst = self._tool_panel._dm_tree_list
        lst.clear()
        for idx in self._project.default_map_settings.tree_palette_indices:
            lst.addItem(QListWidgetItem(str(idx)))

    # ═══════════════════════ 杂项 ═══════════════════════════

    def _on_toggle_language(self) -> None:
        # 在已加载的所有语言之间循环（zh → en → ja → ... → zh）
        langs = available_languages()
        if not langs:
            return
        cur = get_language()
        try:
            next_idx = (langs.index(cur) + 1) % len(langs)
        except ValueError:
            next_idx = 0
        new_lang = langs[next_idx]
        set_language(new_lang)
        # 保存语言设置到 json
        import json, os
        config_path = os.path.join(os.path.expanduser("~"), ".hoi4_map_maker.json")
        config = {}
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except Exception:
                pass
        config["language"] = new_lang
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False)

        # 立即刷新 UI
        self._retranslate_ui()

    def _retranslate_ui(self) -> None:
        """语言切换后刷新整个界面文字（无需重启）。"""
        # 窗口标题
        self.setWindowTitle(tr("app_title"))
        # 重建菜单栏
        self.menuBar().clear()
        self._init_menu()
        # 刷新工具面板
        self._tool_panel.retranslateUi()
        # 刷新欢迎页
        if hasattr(self, '_welcome_page') and self._welcome_page:
            self._welcome_page.retranslateUi()

    def _on_about(self) -> None:
        QMessageBox.about(
            self, tr("action_about"),
            tr("dlg_about_body"),
        )


def _polygon_to_mask(points: list, h: int, w: int):
    """把 [(y,x), ...] 闭合多边形转成 (h,w) bool mask。

    用 matplotlib.path.Path 的 contains_points — 比手写扫描线稳，已在项目
    requirements.txt 里的 Pillow/NumPy 生态中可用替代。这里用纯 numpy + 射线法。
    """
    import numpy as np
    if len(points) < 3:
        return np.zeros((h, w), dtype=bool)

    ys = np.array([p[0] for p in points], dtype=np.float32)
    xs = np.array([p[1] for p in points], dtype=np.float32)

    # 包围盒加速
    y_min = max(0, int(ys.min()) - 1)
    y_max = min(h, int(ys.max()) + 2)
    x_min = max(0, int(xs.min()) - 1)
    x_max = min(w, int(xs.max()) + 2)

    mask = np.zeros((h, w), dtype=bool)
    if y_max <= y_min or x_max <= x_min:
        return mask

    # 射线法（向右发射），逐行扫描 bbox 内像素
    # 对多边形每条边 (y0,x0)->(y1,x1)，看当前扫描行 y 是否穿过该边，
    # 穿过则算交点 x_cross，统计 x_cross < 当前列 x 的次数
    # 奇数次 → 在多边形内
    n = len(points)
    for y in range(y_min, y_max):
        x_crossings = []
        for i in range(n):
            y0, x0 = ys[i], xs[i]
            y1, x1 = ys[(i + 1) % n], xs[(i + 1) % n]
            # 检查这条边是否穿过水平线 y + 0.5
            y_line = y + 0.5
            if (y0 <= y_line) == (y1 <= y_line):
                continue
            # 线性插值 x
            if y1 == y0:
                continue
            t = (y_line - y0) / (y1 - y0)
            x_cross = x0 + t * (x1 - x0)
            x_crossings.append(x_cross)
        if not x_crossings:
            continue
        x_crossings.sort()
        row = mask[y]
        # 成对填充
        for i in range(0, len(x_crossings) - 1, 2):
            xa = max(x_min, int(np.ceil(x_crossings[i])))
            xb = min(x_max, int(np.floor(x_crossings[i + 1])) + 1)
            if xb > xa:
                row[xa:xb] = True
    return mask
