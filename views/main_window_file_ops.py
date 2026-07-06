"""
主窗口文件操作 — 新建/打开/保存/导入/导出。
从 views/main_window_actions.py 拆分，作为 mixin 使用。
"""
from __future__ import annotations

import numpy as np
from PyQt5.QtWidgets import (
    QFileDialog, QMessageBox, QApplication, QInputDialog,
)
from PyQt5.QtGui import QColor

from ui.i18n import tr
from data.constants import (
    TILE_SEA, TILE_LAND,
    DEFAULT_MOD_OUTPUT_PATH,
)


def _populate_imported_data(project, result: dict) -> None:
    """把导入的 states 和 strategic regions 数据填充到 project 的 manager 里。"""
    from domain.managers.state import StateData

    # 填充 states
    for sd in result.get("states", []):
        state = StateData(
            id=sd["id"],
            name=sd.get("name", f"STATE_{sd['id']}"),
            provinces=sd.get("provinces", []),
            manpower=sd.get("manpower", 100000),
            category=sd.get("category", "town"),
            owner_tag=sd.get("owner", ""),
            victory_points=sd.get("victory_points", {}),
            vp_names=sd.get("vp_names", {}),
        )
        project.state_mgr.states[sd["id"]] = state
        for pid in state.provinces:
            project.state_mgr._province_to_state[pid] = sd["id"]
    # 更新 _next_id
    if project.state_mgr.states:
        project.state_mgr._next_id = max(project.state_mgr.states.keys()) + 1

    # 填充 strategic regions — 直接构造对象，不走 create_region（auto_id 会冲突）
    from domain.managers.strategic_region import StrategicRegion
    sr_mgr = project.strategic_region_mgr
    for rd in result.get("strategic_regions", []):
        r = StrategicRegion(
            id=rd["id"],
            name=rd.get("name", f"STRATEGICREGION_{rd['id']}"),
            province_ids=rd.get("provinces", []),
            weather_preset=rd.get("weather_preset", "temperate"),
            naval_terrain=rd.get("naval_terrain", ""),
        )
        sr_mgr._regions[r.id] = r
    if sr_mgr._regions:
        sr_mgr._next_id = max(sr_mgr._regions.keys()) + 1

    # 填充 country（从 states 的 owner 提取）
    # 颜色来自 colors.txt; 国名查本地化 (GER → "德意志国"/"German Reich");
    # 首都/政体来自 history/countries/ (注意原版 capital 是 State ID,
    # 我们的 CountryData.capital 是省份 ID, 这里换算)
    country_colors = result.get("country_colors", {})
    country_history = result.get("country_history", {})
    loc_map = result.get("localisation", {})
    states_by_id = {sd["id"]: sd for sd in result.get("states", [])}
    owners = set(sd.get("owner", "") for sd in result.get("states", []))
    owners.discard("")
    for tag in sorted(owners):
        # 跳过非法 TAG（中文注释、过长、特殊字符等）
        if len(tag) != 3 or not tag.isascii():
            continue
        if tag not in project.country_mgr.countries:
            color = country_colors.get(tag, None)
            if color is None:
                import hashlib
                h = int(hashlib.md5(tag.encode()).hexdigest()[:6], 16)
                color = (
                    max(60, min(220, (h >> 16) & 0xFF)),
                    max(60, min(220, (h >> 8) & 0xFF)),
                    max(60, min(220, h & 0xFF)),
                )
            try:
                # 导入的国家本来就是 vanilla/MOD 的 TAG, 必须放行
                project.country_mgr.create_country(
                    tag, name=loc_map.get(tag, tag), color=color,
                    allow_vanilla_tag=True)
            except ValueError:
                continue  # 非法 TAG 直接跳过
            ch = country_history.get(tag)
            if ch:
                if ch.get("ruling_party") in (
                        "democratic", "fascism", "communism", "neutrality"):
                    project.country_mgr.set_ruling_party(tag, ch["ruling_party"])
                # 首都: State ID → 该 State 内的省份 (优先最高分 VP, 它就是首都城市)
                cap_state = states_by_id.get(ch.get("capital_state", 0))
                if cap_state and cap_state.get("provinces"):
                    vps = cap_state.get("victory_points", {})
                    cap_pid = max(vps, key=vps.get) if vps else cap_state["provinces"][0]
                    project.country_mgr.set_capital(tag, int(cap_pid))
        # 分配 state 到国家
        for sd in result.get("states", []):
            if sd.get("owner") == tag:
                project.country_mgr.assign_state(sd["id"], tag)

    # 填充 railways
    for rd in result.get("railways", []):
        try:
            project.railway_mgr.add(rd["level"], rd["province_ids"])
        except (ValueError, KeyError):
            pass  # 跳过格式不合法的铁路

    # 填充 supply_nodes
    for sd in result.get("supply_nodes", []):
        try:
            project.supply_mgr.add(sd["province_id"], sd["level"])
        except (ValueError, KeyError):
            pass

    # 填充 adjacencies
    from domain.managers.adjacency import AdjacencyEntry
    for ad in result.get("adjacencies", []):
        entry = AdjacencyEntry(
            from_id=ad["from_id"],
            to_id=ad["to_id"],
            type=ad.get("type", "sea"),
            through_id=ad.get("through_id", -1),
            start_x=ad.get("start_x", -1),
            start_y=ad.get("start_y", -1),
            stop_x=ad.get("stop_x", -1),
            stop_y=ad.get("stop_y", -1),
            rule_name=ad.get("rule", ""),
            comment=ad.get("comment", ""),
        )
        project.adjacency_mgr.add(entry)


class MainWindowFileOpsMixin:
    """文件/导入/导出/测试导出操作，混入 MainWindow。"""

    # ═══════════════════════ 导出 ═══════════════════════════

    def _on_export_mod(self) -> None:
        from views.export_dialog import ExportDialog
        dlg = ExportDialog(self._project, self._canvas, parent=self)
        dlg.exec_()

    # ═══════════════════════ 新建/打开/保存 ═══════════════

    def _on_new_project(self) -> None:
        reply = QMessageBox.question(
            self, tr("dlg_confirm"),
            tr("file_ops_new_confirm"),
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        from data.constants import MAP_SIZE_PRESETS, set_map_size
        presets = list(MAP_SIZE_PRESETS.keys())
        default_idx = len(presets) - 1
        for i, name in enumerate(presets):
            if "原版" in name:
                default_idx = i
                break

        chosen, ok = QInputDialog.getItem(
            self, tr("file_ops_map_size_title"), tr("file_ops_map_size_prompt"),
            presets, default_idx, False,
        )
        if not ok:
            return

        new_w, new_h = MAP_SIZE_PRESETS[chosen]
        set_map_size(new_w, new_h)

        from domain.map_data import MapData
        md = MapData()
        md.tile_map = np.full((new_h, new_w), TILE_SEA, dtype=np.uint8)
        md.province_map = np.zeros((new_h, new_w), dtype=np.int32)
        md.terrain_map = np.zeros((new_h, new_w), dtype=np.uint8)
        md.height_map = np.full((new_h, new_w), 40, dtype=np.uint8)
        md.river_map = np.full((new_h, new_w), 255, dtype=np.uint8)  # 255=陆地背景，0 是源头标记不能当空白
        self._project.map_data = md
        self._canvas.set_map_data(md)
        self._canvas._scene.setSceneRect(0, 0, new_w, new_h)
        # 重置 LandController 的 mask
        land_ctrl = self._controllers.get("land")
        if land_ctrl:
            land_ctrl.reset_mask_size()
        self._project.state_mgr.clear()
        self._project.country_mgr.clear()
        self._project.strategic_region_mgr.clear()
        self._project.railway_mgr.clear()
        self._project.supply_mgr.clear()
        self._cmd_history.clear()
        self._update_province_count()
        self._canvas.refresh_display()
        self._status_info.setText(tr("file_ops_new_created", new_w, new_h))
        if hasattr(self, '_show_editor'):
            self._show_editor()

    def _on_save_project(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, tr("file_ops_save_title"), "", tr("file_ops_proj_filter")
        )
        if not path:
            return
        try:
            from services.project_service import save_project
            save_project(
                path, self._canvas, self._project.state_mgr,
                self._project.country_mgr, self._project.continent_mgr,
                adjacency_mgr=self._project.adjacency_mgr,
                railway_mgr=self._project.railway_mgr,
                supply_mgr=self._project.supply_mgr,
                adjacency_rule_mgr=self._project.adjacency_rule_mgr,
                strategic_region_mgr=self._project.strategic_region_mgr,
            )
            self._status_info.setText(tr("file_ops_saved", path))
            # 记录到最近项目
            from views.welcome_page import save_recent_project
            save_recent_project(path)
        except Exception as e:
            QMessageBox.critical(self, tr("file_ops_save_fail"), str(e))

    def _on_open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("file_ops_open_title"), "", tr("file_ops_proj_filter")
        )
        if not path:
            return
        self._load_project_file(path)

    def _load_project_file(self, path: str) -> None:
        """加载指定路径的项目文件。"""
        try:
            from services.project_service import load_project
            load_project(
                path, self._canvas, self._project.state_mgr,
                self._project.country_mgr, self._project.continent_mgr,
                adjacency_mgr=self._project.adjacency_mgr,
                railway_mgr=self._project.railway_mgr,
                supply_mgr=self._project.supply_mgr,
                adjacency_rule_mgr=self._project.adjacency_rule_mgr,
                strategic_region_mgr=self._project.strategic_region_mgr,
            )
            # 加载后检测省份 ID 空洞并提示
            import numpy as np
            pm = self._canvas.province_map
            max_id = int(pm.max())
            gap_count = 0
            if max_id > 0:
                existing = set(np.unique(pm).tolist())
                existing.discard(0)
                gap_count = max_id - len(existing)

            self._update_province_count()
            self._app._refresh_state_list()
            self._app._refresh_country_list()
            if gap_count > 0:
                self._status_info.setText(
                    tr("file_ops_loaded_gaps", path, gap_count)
                )
            else:
                self._status_info.setText(tr("file_ops_loaded", path))
            # 记录到最近项目 + 切换到编辑器
            from views.welcome_page import save_recent_project
            save_recent_project(path)
            if hasattr(self, '_show_editor'):
                self._show_editor()
        except Exception as e:
            QMessageBox.critical(self, tr("file_ops_load_fail"), str(e))

    # ═══════════════════════ 参考图/导入 ═══════════════════════

    def _on_load_vanilla_ref(self) -> None:
        from data.constants import DEFAULT_HOI4_PATH
        import os
        candidates = [
            os.path.join(DEFAULT_HOI4_PATH, "map", "provinces.bmp"),
            os.path.join(DEFAULT_HOI4_PATH, "map", "terrain",
                         "colormap_rgb_cityemissivemask_a.dds"),
        ]
        for path in candidates:
            if os.path.exists(path):
                if self._canvas.load_vanilla_reference(path):
                    self._status_info.setText(
                        tr("file_ops_vanilla_loaded", os.path.basename(path))
                    )
                    return
        QMessageBox.warning(
            self, tr("dlg_error"),
            tr("file_ops_vanilla_not_found", DEFAULT_HOI4_PATH),
        )

    def _on_import_image(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self, tr("action_import_image"), "",
            "Images (*.png *.jpg *.jpeg *.bmp *.tga);;All Files (*)",
        )
        if file_path:
            if self._canvas.load_reference_image(file_path):
                self._status_info.setText(tr("file_ops_ref_loaded", file_path))
            else:
                QMessageBox.warning(self, tr("dlg_error"), tr("file_ops_ref_fail"))

    def _on_import_landmask(self) -> None:
        """从真实地图提取陆海"""
        from PIL import Image

        file_path, _ = QFileDialog.getOpenFileName(
            self, tr("file_ops_landmask_title"), "",
            "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff);;All Files (*)",
        )
        if not file_path:
            return

        threshold, ok = QInputDialog.getInt(
            self, tr("file_ops_threshold_title"),
            tr("file_ops_threshold_prompt"),
            value=1, min=0, max=255,
        )
        if not ok:
            return

        invert_reply = QMessageBox.question(
            self, tr("file_ops_invert_title"), tr("file_ops_invert_prompt"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        invert = (invert_reply == QMessageBox.StandardButton.Yes)

        try:
            img = Image.open(file_path).convert("L")
            from data.constants import MAP_WIDTH, MAP_HEIGHT
            img = img.resize((MAP_WIDTH, MAP_HEIGHT), Image.Resampling.LANCZOS)
            arr = np.array(img, dtype=np.uint8)
            land_mask = (arr < threshold) if invert else (arr >= threshold)
        except Exception as e:
            QMessageBox.warning(self, tr("dlg_error"), tr("file_ops_img_read_fail", e))
            return

        # 通过 BrushStrokeCommand 记录快照（统一走 CommandHistory）
        from commands.land.brush_stroke import BrushStrokeCommand
        before = BrushStrokeCommand.snapshot_arrays({"tile_map": self._canvas.tile_map})

        new_tm = np.where(land_mask, TILE_LAND, TILE_SEA).astype(np.uint8)
        self._canvas.tile_map[:] = new_tm
        from domain.generators.province import auto_classify_water
        auto_classify_water(self._canvas.tile_map)

        # 提交撤销命令
        after = BrushStrokeCommand.snapshot_arrays({"tile_map": self._canvas.tile_map})
        cmd = BrushStrokeCommand("从图片提取陆海", before, after)
        cmd.set_target_arrays({"tile_map": self._canvas.tile_map})
        self._cmd_history._undo_stack.append(cmd)
        self._cmd_history._redo_stack.clear()
        self._cmd_history._notify()

        self._canvas.refresh_display()

        from data.constants import MAP_WIDTH, MAP_HEIGHT
        land_n = int(land_mask.sum())
        total = MAP_WIDTH * MAP_HEIGHT
        land_pct = f"{land_n/total*100:.1f}"
        sea_pct = f"{(1-land_n/total)*100:.1f}"
        self._status_info.setText(
            tr("file_ops_landmask_done", land_pct, sea_pct)
        )

    def _on_import_mod_map(self) -> None:
        """从 HOI4 mod/vanilla 目录导入地图图层"""
        reply = QMessageBox.question(
            self, tr("dlg_confirm"),
            tr("file_ops_import_confirm"),
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        mod_dir = QFileDialog.getExistingDirectory(
            self, tr("file_ops_select_mod_dir"),
            "", QFileDialog.Option.ShowDirsOnly,
        )
        if not mod_dir:
            return

        from services.import_service import validate_mod_directory, import_mod_map

        missing = validate_mod_directory(mod_dir)
        if missing:
            QMessageBox.warning(
                self, tr("dlg_error"),
                tr("file_ops_missing_files") + "\n".join(missing),
            )
            return

        try:
            result = import_mod_map(mod_dir)
        except Exception as e:
            QMessageBox.warning(self, tr("dlg_error"), tr("file_ops_import_fail", e))
            return

        new_w, new_h = result["width"], result["height"]

        # 更新全局地图尺寸
        from data.constants import set_map_size
        set_map_size(new_w, new_h)

        # 通过 Project 统一更新（保持 canvas 和 project 的 map_data 同步）
        from domain.map_data import MapData
        md = MapData()
        # 直接替换数组引用（尺寸可能不同，不能用 [:] 原地写入）
        md.tile_map = result["tile_map"]
        md.province_map = result["province_map"]
        md.terrain_map = result["terrain_map"]
        md.height_map = result["height_map"]
        if result["river_map"] is not None:
            md.river_map = result["river_map"]
        md.provincial_terrain = result.get("provincial_terrain", {})

        self._project.map_data = md
        self._project.state_mgr.clear()
        self._project.country_mgr.clear()
        self._project.continent_mgr.clear()
        self._project.strategic_region_mgr.clear()
        self._project.railway_mgr.clear()
        self._project.supply_mgr.clear()
        self._project.adjacency_mgr.clear()
        self._cmd_history.clear()

        # 保留导入的美术资产（colormap/world_normal 等），导出时不会覆盖
        imported_assets = result.get("assets", {})
        self._project.assets = dict(imported_assets)
        self._project.dirty_assets = set()

        # 填充 states 数据
        _populate_imported_data(self._project, result)

        # 让 canvas 使用同一个 map_data
        self._canvas.set_map_data(md)
        self._canvas._scene.setSceneRect(0, 0, new_w, new_h)
        self._canvas.refresh_display()
        self._update_province_count()
        # 刷新 State/Country 着色（导入后切模式才能看到颜色）
        self._app._refresh_state_colors()
        self._app._refresh_country_colors()
        self._app._refresh_country_list()
        self._app._refresh_state_list()
        self._project.mark_dirty()

        state_count = len(self._project.state_mgr.states)
        sr_count = self._project.strategic_region_mgr.count()
        asset_count = len(self._project.assets)
        info_text = tr("file_ops_mod_imported", new_w, new_h,
                       result['province_count'], state_count, sr_count, asset_count)
        self._status_info.setText(info_text)

        warnings_text = ""
        if result["warnings"]:
            warnings_text = "\n\n" + tr("file_ops_import_warnings") + "\n".join(f"- {w}" for w in result["warnings"])
        QMessageBox.information(
            self, tr("file_ops_import_done"), info_text + warnings_text
        )

    # ═══════════════════════ 测试导出 ═══════════════════════

    @staticmethod
    def _get_test_levels():
        return [
            (tr("file_ops_test_lv1_title"), tr("file_ops_test_lv1_desc")),
            (tr("file_ops_test_lv2_title"), tr("file_ops_test_lv2_desc")),
            (tr("file_ops_test_lv3_title"), tr("file_ops_test_lv3_desc")),
            (tr("file_ops_test_lv4_title"), tr("file_ops_test_lv4_desc")),
        ]

    def _on_test_export(self) -> None:
        from PyQt5.QtWidgets import (
            QDialog, QVBoxLayout, QRadioButton,
            QDialogButtonBox, QLabel, QGroupBox,
        )

        dlg = QDialog(self)
        dlg.setWindowTitle(tr("file_ops_test_dialog_title"))
        dlg.setMinimumWidth(500)
        layout = QVBoxLayout(dlg)

        layout.addWidget(QLabel(tr("file_ops_test_select_level")))

        test_levels = self._get_test_levels()
        group = QGroupBox()
        group_layout = QVBoxLayout(group)
        radios = []
        for i, (title, desc) in enumerate(test_levels):
            rb = QRadioButton(f"{title}\n    {desc}")
            rb.setStyleSheet("QRadioButton { padding: 6px 0; }")
            if i == 0:
                rb.setChecked(True)
            radios.append(rb)
            group_layout.addWidget(rb)
        layout.addWidget(group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        level = 1
        for i, rb in enumerate(radios):
            if rb.isChecked():
                level = i + 1
                break

        output_dir = QFileDialog.getExistingDirectory(
            self, tr("file_ops_test_output_dir"), DEFAULT_MOD_OUTPUT_PATH,
        )
        if not output_dir:
            return

        self._status_info.setText(tr("file_ops_test_generating", level))
        QApplication.processEvents()

        try:
            from export.test_exporter import export_test_mod
            export_test_mod(output_dir, level)
            QMessageBox.information(
                self, tr("file_ops_test_export_title"),
                tr("file_ops_test_export_ok", level, output_dir,
                   test_levels[level-1][0]),
            )
        except Exception as e:
            import traceback
            QMessageBox.critical(
                self, tr("file_ops_export_fail"), f"{e}\n\n{traceback.format_exc()}"
            )
        finally:
            self._status_info.setText(tr("status_ready"))
