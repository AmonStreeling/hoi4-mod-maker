"""
services/* 测试.
"""

import numpy as np
import pytest


def test_terrain_service_auto_terrain():
    from services.terrain_service import auto_terrain
    from data.constants import TILE_LAND, TILE_SEA, TILE_LAKE
    from data.terrain_types import DEFAULT_TERRAIN_FOR_TILE, TERRAIN_PALETTE_INDEX

    tm = np.array([
        [TILE_LAND, TILE_SEA, TILE_LAKE],
        [TILE_LAND, TILE_SEA, TILE_LAND],
    ], dtype=np.uint8)
    terrain = auto_terrain(tm)
    assert terrain.shape == tm.shape
    # 陆地像素的 terrain 值必须是 DEFAULT_TERRAIN_FOR_TILE[LAND] 对应的调色板索引
    expected_land = TERRAIN_PALETTE_INDEX[DEFAULT_TERRAIN_FOR_TILE[TILE_LAND]]
    assert terrain[0, 0] == expected_land


def test_terrain_service_auto_height_range():
    from services.terrain_service import auto_height
    from data.constants import (
        MAP_WIDTH, MAP_HEIGHT, TILE_LAND, TILE_SEA, SEA_LEVEL,
    )
    tm = np.full((MAP_HEIGHT, MAP_WIDTH), TILE_LAND, dtype=np.uint8)
    tm[0, :] = TILE_SEA
    tm[-1, :] = TILE_SEA
    hm = auto_height(tm)
    assert hm.dtype == np.uint8
    assert hm.min() >= 0
    assert hm.max() <= 255
    # 陆地中心高度应该 > sea level
    mid_y, mid_x = MAP_HEIGHT // 2, MAP_WIDTH // 2
    assert hm[mid_y, mid_x] > SEA_LEVEL


def test_export_service_validate_empty_map():
    from services.export_service import validate_before_export
    from domain.managers.state import StateManager
    from domain.managers.country import CountryManager

    class _FakeCanvas:
        province_map = np.zeros((10, 10), dtype=np.int32)

    warnings = validate_before_export(_FakeCanvas(), StateManager(), CountryManager())
    assert any("省份" in w for w in warnings)


def test_export_service_validate_missing_owner():
    from services.export_service import validate_before_export
    from domain.managers.state import StateManager, StateData
    from domain.managers.country import CountryManager

    class _FakeCanvas:
        province_map = np.ones((10, 10), dtype=np.int32)

    state_mgr = StateManager()
    state_mgr._states[1] = StateData(id=1, provinces=[1])
    country_mgr = CountryManager()
    country_mgr.create_country("TST", "Test", (100, 100, 100))
    country_mgr.set_capital("TST", 1)

    warnings = validate_before_export(_FakeCanvas(), state_mgr, country_mgr)
    # 应该警告 State 1 未分配 owner
    assert any("未分配" in w for w in warnings)


def test_export_service_validate_river_issues():
    """河流缺源头 → 预检警告; 河流合法 → 无河流警告。"""
    from services.export_service import validate_before_export
    from domain.managers.state import StateManager
    from domain.managers.country import CountryManager

    class _FakeCanvas:
        province_map = np.ones((10, 10), dtype=np.int32)
        river_map = np.full((10, 10), 255, dtype=np.uint8)

    canvas = _FakeCanvas()
    canvas.river_map[5, 2:8] = 3  # 一段河, 没放源头标记

    warnings = validate_before_export(canvas, StateManager(), CountryManager())
    assert any("河流" in w and "源头" in w for w in warnings)

    canvas.river_map[5, 2] = 0  # 补上源头
    warnings = validate_before_export(canvas, StateManager(), CountryManager())
    assert not any(w.startswith("河流") for w in warnings)


# ────────── state ↔ 战略区对齐 (pre_export_check_and_fix 5.4/5.6) ──────────

def _make_align_fixture(province_map, tile_map, state_provs, region_provs):
    """构造 state/country/strategic_region 三个 manager."""
    from domain.managers.state import StateManager
    from domain.managers.country import CountryManager
    from domain.managers.strategic_region import StrategicRegionManager

    state_mgr = StateManager()
    for provs in state_provs:
        state_mgr.create_state(list(provs))
    country_mgr = CountryManager()
    country_mgr.create_country("AAA", "Test", (100, 100, 100))
    sr_mgr = StrategicRegionManager()
    for provs in region_provs:
        r = sr_mgr.create_region()
        r.province_ids = list(provs)
    return state_mgr, country_mgr, sr_mgr


def test_pre_export_aligns_split_state_to_one_region():
    """连通的 state 被两个战略区切开 → 自动归并到同一个战略区."""
    from services.export_service import pre_export_check_and_fix
    from data.constants import TILE_LAND

    # 省份 1 (左半) + 省份 2 (右半), 全陆地, 同属 state 1
    pm = np.ones((6, 6), dtype=np.int32)
    pm[:, 3:] = 2
    tm = np.full((6, 6), TILE_LAND, dtype=np.uint8)
    state_mgr, country_mgr, sr_mgr = _make_align_fixture(
        pm, tm, state_provs=[[1, 2]], region_provs=[[1], [2]])

    report = pre_export_check_and_fix(tm, pm, None, state_mgr, country_mgr,
                                      strategic_region_mgr=sr_mgr)

    r1 = sr_mgr.get_region_of_province(1)
    r2 = sr_mgr.get_region_of_province(2)
    assert r1 == r2 and r1 != 0
    assert sr_mgr.count() == 1  # 被挪空的战略区已删除
    assert any("战略区" in f for f in report.fixed)
    assert not any("飞地" in w for w in report.warnings)


def test_pre_export_enclave_state_warns():
    """state 本身不连通(隔海两块) → 无法归并, 只发警告不动数据."""
    from services.export_service import pre_export_check_and_fix
    from data.constants import TILE_LAND, TILE_SEA

    # 省份 1 (左岛) | 省份 3 (海) | 省份 2 (右岛), state 1 = [1, 2]
    pm = np.ones((5, 7), dtype=np.int32)
    pm[:, 2:5] = 3
    pm[:, 5:] = 2
    tm = np.full((5, 7), TILE_LAND, dtype=np.uint8)
    tm[:, 2:5] = TILE_SEA
    state_mgr, country_mgr, sr_mgr = _make_align_fixture(
        pm, tm, state_provs=[[1, 2]], region_provs=[[1], [2], [3]])

    report = pre_export_check_and_fix(tm, pm, None, state_mgr, country_mgr,
                                      strategic_region_mgr=sr_mgr)

    # 两块地各留原区, 不许被硬拉到一起 (会造出不连通的战略区)
    assert sr_mgr.get_region_of_province(1) != sr_mgr.get_region_of_province(2)
    assert any("飞地" in w for w in report.warnings)


def test_pre_export_pulls_unassigned_province_into_state_region():
    """state 里有省份没分配战略区 → 跟随本州其他省份进同一战略区."""
    from services.export_service import pre_export_check_and_fix
    from data.constants import TILE_LAND

    pm = np.ones((6, 6), dtype=np.int32)
    pm[:, 3:] = 2
    tm = np.full((6, 6), TILE_LAND, dtype=np.uint8)
    # 省份 2 未分配任何战略区
    state_mgr, country_mgr, sr_mgr = _make_align_fixture(
        pm, tm, state_provs=[[1, 2]], region_provs=[[1]])

    report = pre_export_check_and_fix(tm, pm, None, state_mgr, country_mgr,
                                      strategic_region_mgr=sr_mgr)

    rid = sr_mgr.get_region_of_province(1)
    assert sr_mgr.get_region_of_province(2) == rid and rid != 0
    assert not any("飞地" in w for w in report.warnings)
