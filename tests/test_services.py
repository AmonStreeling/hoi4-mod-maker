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
