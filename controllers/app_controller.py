"""ApplicationController — 应用级调度器。

从 MainWindow 抽出的业务逻辑：
- 模式切换副作用
- 省份信息计算
- State/Country 颜色图刷新
- VP 数据收集
- 列表刷新
- 撤销/重做管理

MainWindow 只做 UI 构建和信号路由，所有逻辑委托到这里。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from ui.i18n import tr

if TYPE_CHECKING:
    from model.project import Project
    from model.events import EventBus
    from commands.history import CommandHistory
    from views.canvas.widget import MapCanvas
    from ui.tool_panel import ToolPanel

from data.constants import TILE_LAND, TILE_SEA, TILE_LAKE
from commands.land.brush_stroke import BrushStrokeCommand


class ApplicationController:
    """应用级调度器 — 协调 controllers、canvas、tool_panel。"""

    def __init__(
        self,
        project: "Project",
        canvas: "MapCanvas",
        tool_panel: "ToolPanel",
        cmd_history: "CommandHistory",
        controllers: dict[str, Any],
        undo_mgr: Any,
    ) -> None:
        self._project = project
        self._canvas = canvas
        self._panel = tool_panel
        self._cmd_history = cmd_history
        self._controllers = controllers
        self._undo_mgr = undo_mgr
        self._event_bus: "EventBus" = project.event_bus
        self._current_controller = None
        self._province_info_cache: dict[int, dict] = {}

        # 画笔 stroke 状态（用于 BrushStrokeCommand）
        self._stroke_before: dict | None = None

        # 订阅 EventBus 事件
        self._subscribe_events()

    # ═══════════════════════ EventBus 订阅 ═══════════════════

    def _subscribe_events(self) -> None:
        bus = self._event_bus
        bus.subscribe("request_render", self._on_render)
        bus.subscribe("province_count_changed", self._on_province_count)
        bus.subscribe("state_changed", self._on_state_changed)
        bus.subscribe("country_changed", self._on_country_changed)
        bus.subscribe("continent_changed", self._on_continent_changed)
        bus.subscribe("vp_changed", self._on_vp_changed)
        bus.subscribe("province_map_regenerated", self._on_province_regen)
        bus.subscribe("clear_batch_selection", lambda e: self._canvas.set_batch_selection_pids([]))
        bus.subscribe("batch_highlight_pids", lambda e: self._canvas.set_batch_selection_pids(e.data.get("pids", [])))
        bus.subscribe("railway_changed", self._on_railway_changed)
        bus.subscribe("sr_colors_dirty", self._on_sr_colors_dirty)
        bus.subscribe("province_gaps_changed", self._on_province_gaps)

    # ═══════════════════════ 模式切换 ═══════════════════════

    # 模式名称映射
    _MODE_NAMES = {
        "land": "大陆", "province": "省份", "terrain": "地形",
        "height": "高度", "state": "State", "country": "国家",
        "river": "河流", "continent": "大洲", "logistics": "后勤",
        "strategic_region": "战略区", "colormap": "总览贴图",
        "default_map": "地图配置", "preview": "预览",
    }

    def on_mode_changed(self, mode: str) -> str:
        """模式切换：停用旧 controller、激活新 controller、刷新相关数据。
        返回模式中文名。"""
        if self._current_controller is not None:
            self._current_controller.deactivate()

        self._canvas.cleanup_mode_state()
        # density 模式底图是 land（叠密度遮罩）
        if mode == "density":
            self._canvas.display_mode = "land"
        else:
            self._canvas.display_mode = mode

        # 密度模式特殊：借用 LandController 但开启 density_mode
        # 密度图作为遮罩叠加在 land 视图上
        if mode == "density":
            md = self._project.map_data
            if md.density_map is None:
                md.density_map = np.full(
                    (md.tile_map.shape[0], md.tile_map.shape[1]),
                    0.5, dtype=np.float32,
                )
            self._canvas.set_density_overlay_visible(True)
            self._current_controller = self._controllers.get("land")
            if self._current_controller is not None:
                self._current_controller.density_mode = True
                self._current_controller.activate()
                self._current_controller._emit_status("密度画笔模式")
        else:
            # 切到其他模式时，确保 land controller 退出密度模式，隐藏密度遮罩
            self._canvas.set_density_overlay_visible(False)
            land_ctrl = self._controllers.get("land")
            if land_ctrl is not None:
                land_ctrl.density_mode = False
            self._current_controller = self._controllers.get(mode)
            if self._current_controller is not None:
                self._current_controller.activate()

        # 按模式刷新颜色图
        if mode == "state":
            self._refresh_state_colors()
            # state 模式叠加国家边界 + owner 高亮, 需要 country_rgb + assigned_mask
            self._refresh_country_colors()
            # 进 state 模式时清掉残留的国家高亮 (从 country mode 切过来时)
            self._canvas.set_highlight_country(None)
        elif mode == "country":
            self._refresh_country_colors()
        elif self._canvas._highlight_country_rgb is not None:
            # 离开 state / country 模式时清掉国家高亮
            self._canvas.set_highlight_country(None)
        elif mode == "strategic_region":
            self._refresh_sr_colors()
        elif mode == "logistics":
            self._refresh_railway_colors()
            self._canvas.refresh_logistics_overlay()
        elif mode == "province_terrain":
            self._refresh_provincial_terrain_colors()
        elif mode == "continent":
            self._refresh_continent_colors()

        # 离开战略区模式时隐藏 state 边界叠加
        if mode != "strategic_region":
            self._canvas.show_state_borders(False)

        return self._MODE_NAMES.get(mode, mode)

    @property
    def current_controller(self):
        return self._current_controller

    # ═══════════════════════ 省份信息 ═══════════════════════

    def invalidate_province_cache(self) -> None:
        """清除省份信息缓存。"""
        self._province_info_cache.clear()

    def calculate_province_info(self, pid: int) -> dict | None:
        """计算省份信息（类型/地形/像素数/沿海），带缓存。
        返回 dict 或 None。"""
        if pid in self._province_info_cache:
            return self._province_info_cache[pid]

        pm = self._canvas.province_map
        tm = self._canvas.tile_map
        mask = pm == pid
        pixels = int(np.sum(mask))

        ys, xs = np.where(mask)
        if len(ys) == 0:
            return None

        tiles = tm[mask]
        land_n = int(np.sum(tiles == TILE_LAND))
        sea_n = int(np.sum(tiles == TILE_SEA))
        lake_n = int(np.sum(tiles == TILE_LAKE))
        if sea_n >= land_n and sea_n >= lake_n:
            ptype = "海洋"
        elif lake_n >= land_n:
            ptype = "湖泊"
        else:
            ptype = "陆地"

        # 沿海检查
        _adj = False
        for dy, dx in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            ny = np.clip(ys + dy, 0, tm.shape[0] - 1)
            nx = np.clip(xs + dx, 0, tm.shape[1] - 1)
            if np.any(tm[ny, nx] == TILE_SEA):
                _adj = True
                break
        coastal = _adj and ptype == "陆地"

        # 优先读 provincial_terrain dict（属性层 = gameplay 真值）
        # 没有时才退回 terrain.bmp 多数像素（视觉层推断）
        from data.terrain_types import (
            GRAPHICAL_TERRAIN_BY_INDEX, TERRAIN_TYPES,
            terrain_display_name, graphical_terrain_display_name,
        )
        prov_terrain = self._project.map_data.provincial_terrain
        if pid in prov_terrain:
            ptype_key = prov_terrain[pid]
            terrain_obj = TERRAIN_TYPES.get(ptype_key)
            terrain_name = terrain_display_name(terrain_obj) if terrain_obj else ptype_key
        else:
            terrain_data = self._canvas.terrain_map[mask]
            if len(terrain_data) > 0:
                counts = np.bincount(terrain_data)
                # 跳过 index 0（背景/海洋），优先取非零地形
                if len(counts) > 1 and counts[1:].max() > 0:
                    terrain_idx = int(counts[1:].argmax()) + 1
                else:
                    terrain_idx = int(counts.argmax())
                gt = GRAPHICAL_TERRAIN_BY_INDEX.get(terrain_idx)
                terrain_name = graphical_terrain_display_name(gt) if gt else tr("terrain_unknown")
            else:
                terrain_name = tr("terrain_unknown")

        info = {
            "ptype": ptype, "terrain": terrain_name,
            "pixels": pixels, "coastal": coastal,
        }
        self._province_info_cache[pid] = info
        return info

    # ═══════════════════════ State/Country 刷新 ═══════════════

    def _refresh_state_list(self) -> None:
        country_mgr = self._project.country_mgr
        items = [
            (sid, s.name, len(s.provinces), country_mgr.get_owner_of_state(sid))
            for sid, s in self._project.state_mgr.states.items()
        ]
        self._panel.update_state_list(items)

    def _refresh_state_colors(self) -> None:
        if int(self._canvas.province_map.max()) == 0:
            return
        rgb = self._project.state_mgr.build_state_color_map(self._canvas.province_map)
        self._canvas.set_state_colors(rgb)
        self._refresh_vp_data()
        # 统计未分配的 land province → 状态栏提示
        self._emit_unassigned_count()

    def _emit_unassigned_count(self) -> None:
        """统计未分配到 state 的 land province 数量，发送到状态栏。"""
        from data.constants import TILE_LAND
        tm = self._project.map_data.tile_map
        pm = self._canvas.province_map
        if pm is None or pm.max() == 0:
            return
        # 所有 land province ID
        land_pids = set(np.unique(pm[tm == TILE_LAND]).tolist())
        land_pids.discard(0)
        count = self._project.state_mgr.count_unassigned_provinces(land_pids)
        if count > 0:
            self._project.event_bus.emit(
                "status_message",
                text=tr("status_unassigned_warning", count)
            )
        else:
            self._project.event_bus.emit(
                "status_message", text=tr("status_all_assigned")
            )

    def _refresh_provincial_terrain_colors(self) -> None:
        """计算每个 province 的 gameplay terrain 颜色，传给 canvas。
        像素颜色 = 该 province 的 provincial_terrain[pid] 对应的颜色。
        未指定 type 的 province 显示灰色。"""
        province_map = self._canvas.province_map
        if int(province_map.max()) == 0:
            return
        from data.terrain_types import TERRAIN_TYPES
        prov_terrain = self._project.map_data.provincial_terrain
        n = int(province_map.max()) + 1
        # pid → RGB（0=灰色 fallback）
        lookup = np.full((n, 3), 80, dtype=np.uint8)
        for pid, ptype in prov_terrain.items():
            if pid < n and ptype in TERRAIN_TYPES:
                r, g, b = TERRAIN_TYPES[ptype].color
                lookup[pid] = (r, g, b)
        # 按 province_map 索引上色
        rgb = lookup[province_map]
        self._canvas.set_provincial_terrain_colors(rgb)

    def _refresh_vp_data(self) -> None:
        vp_dict: dict[int, int] = {}
        name_dict: dict[int, str] = {}
        for state in self._project.state_mgr.states.values():
            for pid, vp_val in state.victory_points.items():
                if vp_val > 0:
                    vp_dict[pid] = vp_val
            for pid, name in state.vp_names.items():
                if name:
                    name_dict[pid] = name
        self._canvas.set_vp_data(vp_dict, name_dict)

    def _refresh_country_list(self) -> None:
        self._panel.update_country_list(self._project.country_mgr.get_country_list())

    def _refresh_country_colors(self) -> None:
        if int(self._canvas.province_map.max()) == 0:
            return
        # 传 tile_map → 让 builder 用多数决识别陆地省, 避免海洋省被涂色
        # 返回 (rgb, assigned_mask): assigned_mask 标记"已分配国家"的 land 像素
        # → 国家 renderer 据此只在已分配区域之间画白边, 跳过海洋/未分配 state
        rgb, assigned_mask = self._project.country_mgr.build_country_color_map(
            self._canvas.province_map,
            self._project.state_mgr,
            tile_map=self._canvas.tile_map,
        )
        self._canvas.set_country_colors(rgb, assigned_mask)

    def _refresh_sr_colors(self) -> None:
        if int(self._canvas.province_map.max()) == 0:
            return
        rgb = self._project.strategic_region_mgr.build_sr_color_map(
            self._canvas.province_map, self._canvas.tile_map
        )
        self._canvas.set_sr_colors(rgb)

    def _refresh_continent_colors(self) -> None:
        if int(self._canvas.province_map.max()) == 0:
            return
        rgb = self._project.continent_mgr.build_continent_color_map(
            self._canvas.province_map,
            self._canvas.tile_map,
            state_manager=self._project.state_mgr,
        )
        self._canvas.set_continent_colors(rgb)

    def _on_railway_changed(self, event=None) -> None:
        if self._canvas.display_mode == "logistics":
            self._refresh_railway_colors()
            self._canvas.refresh_logistics_overlay()

    def _on_sr_colors_dirty(self, event=None) -> None:
        if self._canvas.display_mode == "strategic_region":
            self._refresh_sr_colors()
            self._canvas.refresh_display()

    def _refresh_railway_colors(self) -> None:
        if int(self._canvas.province_map.max()) == 0:
            return
        rgb = self._project.railway_mgr.build_railway_color_map(
            self._canvas.province_map
        )
        self._canvas.set_railway_colors(rgb)

    def update_province_count(self) -> int:
        """返回当前省份数量。"""
        return int(self._canvas.province_map.max())

    # ═══════════════════════ EventBus 处理器 ═══════════════════

    def _on_render(self, event) -> None:
        full = event.data.get("full", False)
        bbox = event.data.get("bbox")
        self._canvas._rebind_aliases()
        # province_terrain 模式下，渲染前先刷新颜色（属性变化要立即反映）
        if self._canvas.display_mode == "province_terrain":
            self._refresh_provincial_terrain_colors()
        if full or bbox is None:
            # 清除省份边界缓存，确保合并/切割后边界线刷新
            self._canvas._border_cache = None
            if hasattr(self._canvas, '_border_base_pixmap'):
                self._canvas._border_base_pixmap = None
            self._canvas._full_render()
            self._canvas._render_province_overlay()
        else:
            x0, y0, x1, y1 = bbox
            self._canvas._partial_render(x0, y0, x1, y1)

    def _on_province_count(self, event) -> None:
        # 由 MainWindow 处理状态栏更新
        pass

    def _on_province_gaps(self, event) -> None:
        """省份 ID 空洞变化 → 更新工具面板 + 状态栏提示。"""
        gap_ids = event.data.get("gap_ids", [])
        self._panel.update_province_gaps(gap_ids)
        # 状态栏也提示（不管当前在哪个页面都能看到）
        if gap_ids:
            self._event_bus.emit(
                "status_message",
                text=f"缺失省份 ID: {len(gap_ids)} 个（切割可自动补回）",
            )

    def _on_state_changed(self, event) -> None:
        """State 数据变化 → 刷新 UI。"""
        action = event.data.get("action", "")
        if action == "refresh":
            self.invalidate_province_cache()
            self._refresh_state_list()
            self._refresh_state_colors()
        elif action == "modified":
            sid = event.data.get("state_id", 0)
            state = self._project.state_mgr.get_state(sid)
            if state:
                self._panel.update_state_info(
                    state.name, state.manpower, state.category
                )
            prop = event.data.get("property", "")
            if prop in ("", "provinces", "assign"):
                self._refresh_state_colors()
                # 列表项里的省份计数 [id] name (N) 也要跟着刷，否则点了分配不更新
                self._refresh_state_list()
        elif action == "selected":
            sid = event.data.get("state_id", 0)
            state = self._project.state_mgr.get_state(sid)
            if state:
                self._panel.update_state_info(
                    state.name, state.manpower, state.category
                )
                # 高亮选中州的所有省份
                self._canvas.set_batch_selection_pids(list(state.provinces))
                # 在列表中选中对应行 + 更新 page 的 _current_state_id
                self._panel.select_state_in_list(sid)
                # 在画布上高亮该 state 的 owner 那一国 (state 模式渲染会叠暖黄)
                owner = self._project.country_mgr.get_owner_of_state(sid)
                country = self._project.country_mgr.get_country(owner) if owner else None
                if country is not None:
                    self._canvas.set_highlight_country(tuple(country.color))
                else:
                    self._canvas.set_highlight_country(None)
            else:
                self._canvas.set_batch_selection_pids([])
                self._canvas.set_highlight_country(None)

    def _on_country_changed(self, event) -> None:
        """Country 数据变化 → 刷新 UI。"""
        action = event.data.get("action", "")
        tag = event.data.get("tag", "")
        if action in ("refresh", "created", "modified"):
            self._refresh_country_list()
            self._refresh_country_colors()
            if tag:
                self._update_country_info_panel(tag)
        elif action == "selected" and tag:
            self._update_country_info_panel(tag)

    def _update_country_info_panel(self, tag: str) -> None:
        country = self._project.country_mgr.get_country(tag)
        if country:
            capital_name = f"省份 {country.capital}" if country.capital > 0 else ""
            self._panel.update_country_info(
                country.tag, country.name, country.ruling_party,
                country.color, capital_name,
            )

    def _on_vp_changed(self, event) -> None:
        self._refresh_vp_data()

    def _on_continent_changed(self, event) -> None:
        """大陆列表/指派变化 → 如果在大陆模式下，立即刷新颜色图。"""
        if self._canvas.display_mode == "continent":
            self._refresh_continent_colors()
            self._canvas.refresh_display()

    def _on_province_regen(self, event) -> None:
        """省份重新生成 → 清除所有颜色缓存，强制下次切模式时重建。"""
        self.invalidate_province_cache()
        self._canvas._state_color_rgb = None
        self._canvas._country_color_rgb = None
        self._canvas._sr_color_rgb = None
        self._canvas._railway_color_rgb = None
        self._canvas._provincial_terrain_color_rgb = None
        self._canvas._continent_color_rgb = None
        # 立即刷新当前模式的颜色（不然切模式前看到的是旧的）
        mode = self._canvas.display_mode
        if mode == "state":
            self._refresh_state_colors()
        elif mode == "country":
            self._refresh_country_colors()
        elif mode == "strategic_region":
            self._refresh_sr_colors()
        elif mode == "logistics":
            self._refresh_railway_colors()
            self._canvas.refresh_logistics_overlay()

    # ═══════════════════════ 撤销/重做 ═══════════════════════

    def _get_stroke_arrays(self) -> dict[str, np.ndarray]:
        """获取当前模式对应的数组，用于画笔快照。"""
        mode = self._canvas.display_mode
        if mode == "land":
            # 密度遮罩开启时画笔改的是 density_map（在 land mode 底图上叠加涂抹）
            md = self._project.map_data
            if (getattr(self._canvas, '_density_overlay_visible', False)
                    and md.density_map is not None):
                return {"density_map": md.density_map}
            return {"tile_map": self._canvas.tile_map}
        elif mode == "terrain":
            return {"terrain_map": self._canvas.terrain_map}
        elif mode == "height":
            return {"height_map": self._canvas.height_map}
        elif mode == "province":
            return {"province_map": self._canvas.province_map}
        elif mode == "river":
            return {"river_map": self._canvas.river_map}
        return {}

    def _get_all_arrays(self) -> dict[str, np.ndarray]:
        """获取所有数组引用（撤销/重做时需要）。"""
        arrays = {
            "tile_map": self._canvas.tile_map,
            "province_map": self._canvas.province_map,
            "terrain_map": self._canvas.terrain_map,
            "height_map": self._canvas.height_map,
            "river_map": self._canvas.river_map,
        }
        md = self._project.map_data
        if md.density_map is not None:
            arrays["density_map"] = md.density_map
        return arrays

    def on_stroke_started(self) -> None:
        """画笔开始 — 记录操作前快照。"""
        arrays = self._get_stroke_arrays()
        self._stroke_before = BrushStrokeCommand.snapshot_arrays(arrays)

    def on_stroke_ended(self) -> None:
        """画笔结束 — 比较变化，创建 Command 并推入 CommandHistory。"""
        if self._stroke_before is None:
            return
        arrays = self._get_stroke_arrays()
        if BrushStrokeCommand.has_changes(self._stroke_before, arrays):
            after = BrushStrokeCommand.snapshot_arrays(arrays)
            mode = self._canvas.display_mode
            cmd = BrushStrokeCommand(f"{mode} 绘制", self._stroke_before, after)
            cmd.set_target_arrays(self._get_all_arrays())
            # 直接推入栈，不调 execute（因为画笔已经绘制完了）
            self._cmd_history._undo_stack.append(cmd)
            self._cmd_history._redo_stack.clear()
            if len(self._cmd_history._undo_stack) > self._cmd_history._max_size:
                self._cmd_history._undo_stack.pop(0)
            self._cmd_history._notify()
        self._stroke_before = None

    def _refresh_brush_targets(self, cmd) -> None:
        """递归把 BrushStrokeCommand（包括嵌套在 CompositeCommand 内的）刷成最新数组引用。"""
        from commands.composite import CompositeCommand
        if isinstance(cmd, BrushStrokeCommand):
            cmd.set_target_arrays(self._get_all_arrays())
        elif isinstance(cmd, CompositeCommand):
            for child in cmd.children:
                self._refresh_brush_targets(child)

    def undo(self) -> str:
        """执行撤销。返回状态消息。"""
        # 如果有未完成的 stroke，先提交
        if self._stroke_before is not None:
            self.on_stroke_ended()

        if not self._cmd_history.can_undo:
            return "没有可撤销的操作"

        # 确保 BrushStrokeCommand（含 composite 内的）有最新数组引用
        self._refresh_brush_targets(self._cmd_history._undo_stack[-1])

        self._cmd_history.undo()
        self._post_undo_redo_refresh()
        return "已撤销"

    def redo(self) -> str:
        """执行重做。返回状态消息。"""
        if self._stroke_before is not None:
            self.on_stroke_ended()

        if not self._cmd_history.can_redo:
            return "没有可重做的操作"

        self._refresh_brush_targets(self._cmd_history._redo_stack[-1])

        self._cmd_history.redo()
        self._post_undo_redo_refresh()
        return "已重做"

    def _post_undo_redo_refresh(self) -> None:
        """撤销/重做后刷新画布 + 按模式重建颜色图 + 通知所有 list 刷新。"""
        mode = self._canvas.display_mode
        if mode == "logistics":
            self._refresh_railway_colors()
            self._canvas.refresh_logistics_overlay()
        elif mode == "state":
            self._refresh_state_colors()
        elif mode == "country":
            self._refresh_country_colors()
        elif mode == "strategic_region":
            self._refresh_sr_colors()
        elif mode == "continent":
            self._refresh_continent_colors()
        self._canvas.refresh_display()

        # 撤销/重做可能改了 manager 数据 — 全面 emit 让所有 list 刷新（低频操作，可接受）
        bus = self._event_bus
        bus.emit("state_changed", state_id=0, action="refresh")
        bus.emit("country_changed", tag="", action="refresh")
        bus.emit("continent_changed", action="refresh")
        bus.emit("sr_colors_dirty")
        bus.emit("railway_changed")
        # 省份数和缺失 ID 也可能变（如局部重生）
        pm_max = int(self._canvas.province_map.max())
        bus.emit("province_count_changed", count=pm_max)
        import numpy as np
        if pm_max > 0:
            existing = set(np.unique(self._canvas.province_map).tolist()) - {0}
            gap_ids = sorted(set(range(1, pm_max + 1)) - existing)
            bus.emit("province_gaps_changed", gap_ids=gap_ids)

    # ═══════════════════════ 省份点击路由 ═══════════════════

    def on_province_clicked(self, pid: int) -> dict | None:
        """省份被点击：计算信息 + 转发给当前 controller。返回省份信息 dict。"""
        if pid <= 0:
            return None
        info = self.calculate_province_info(pid)
        if self._current_controller is not None:
            self._current_controller.on_province_clicked(pid)
        return info

    def on_province_double_clicked(self, pid: int) -> None:
        if pid <= 0:
            return
        if self._current_controller is not None:
            self._current_controller.on_province_double_clicked(pid)
