"""
项目完成度检查 — 导出预检和制作进度面板共用的一套标准。

从 views/export_dialog.py 迁出 (2026-06 架构整理):
完成度是业务规则不是对话框细节, 导出预检和 M2 的常驻进度面板
必须用同一套计算, 否则"面板说完成了、导出说缺东西"两套标准打架。

map_source: 任何提供 province_map / tile_map / terrain_map / height_map
属性的对象 (MapData 或画布都满足), 不依赖 Qt。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ui.i18n import tr


@dataclass
class CheckItem:
    """单个检查项"""
    name: str           # 显示名
    status: str         # "ok" / "missing" / "warning"
    detail: str         # 详细说明
    can_auto: bool      # 是否可自动补全
    count: int = 0      # 数量（省份数/State数等）


def check_project_readiness(project, map_source) -> list[CheckItem]:
    """检查项目是否可以导出，返回检查项列表。"""
    items: list[CheckItem] = []
    pm = map_source.province_map
    tm = map_source.tile_map
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
    ter = map_source.terrain_map
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
    hm = map_source.height_map
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
