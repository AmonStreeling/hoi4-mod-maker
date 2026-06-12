"""
冒烟测试 — 每次改代码后跑一遍，确保核心功能没炸。

覆盖:
- 省份生成（含密度图）
- State 管理 + VP 城市名
- 战略区管理 + compact 同步
- 河流验证
- 导出本地化（VP 城市名）
- 大洲分配（含 State 级别）
- trees_bmp 自动生成
"""

import numpy as np
import pytest


# ═══════ 省份生成 + 密度图 ═══════

def test_province_generation_basic():
    """基础省份生成不崩。"""
    from domain.generators.province import generate_provinces
    tile_map = np.zeros((64, 128), dtype=np.uint8)
    tile_map[10:54, 10:118] = 1  # 陆地
    province_map, count = generate_provinces(tile_map, target_count=20)
    assert count >= 5
    assert province_map.shape == tile_map.shape


def test_province_generation_with_density():
    """带密度图的省份生成不崩。"""
    from domain.generators.province import generate_provinces
    tile_map = np.zeros((64, 128), dtype=np.uint8)
    tile_map[10:54, 10:118] = 1
    density_map = np.full((64, 128), 0.5, dtype=np.float32)
    density_map[20:40, 40:80] = 1.0
    province_map, count = generate_provinces(tile_map, target_count=20, density_map=density_map)
    assert count >= 5


# ═══════ State 管理 ═══════

def test_state_manager_basic():
    """State 创建和省份分配。"""
    from domain.managers.state import StateManager
    mgr = StateManager()
    state = mgr.create_state()
    sid = state.id
    assert sid > 0
    mgr.assign_province(1, sid)
    mgr.assign_province(2, sid)
    s = mgr.get_state(sid)
    assert 1 in s.provinces
    assert 2 in s.provinces


def test_state_vp_names():
    """VP 城市名存取。"""
    from domain.managers.state import StateManager
    mgr = StateManager()
    state = mgr.create_state()
    sid = state.id
    mgr.assign_province(1, sid)
    mgr.set_vp(1, 10, name="Beijing")
    s = mgr.get_state(sid)
    assert s.victory_points[1] == 10
    assert s.vp_names[1] == "Beijing"


# ═══════ 战略区 + compact 同步 ═══════

def test_strategic_region_compact():
    """compact_with_references 同步战略区省份 ID。"""
    from domain.map_data import MapData
    from domain.managers.strategic_region import StrategicRegionManager
    import data.constants as constants
    from data.constants import set_map_size

    old_w, old_h = constants.MAP_WIDTH, constants.MAP_HEIGHT
    set_map_size(8, 4)
    try:
        md = MapData()
        md.province_map = np.array([
            [0, 0, 1, 1, 3, 3, 5, 5],
            [0, 0, 1, 1, 3, 3, 5, 5],
            [0, 0, 1, 1, 3, 3, 5, 5],
            [0, 0, 1, 1, 3, 3, 5, 5],
        ], dtype=np.int32)
        md.tile_map = np.ones((4, 8), dtype=np.uint8)

        sr_mgr = StrategicRegionManager()
        r = sr_mgr.create_region()
        r.province_ids = [1, 3, 5]

        mapping = md.compact_with_references(strategic_region_mgr=sr_mgr)
        new_ids = sorted(r.province_ids)
        assert new_ids == [1, 2, 3]
    finally:
        # 全局尺寸是共享状态, 必须还原, 否则污染后续测试
        set_map_size(old_w, old_h)


# ═══════ 河流验证 ═══════

def test_river_validate_multi_source_ok():
    """多源头河流网络不应报警告。"""
    from domain.managers.river import validate_rivers, RIVER_SOURCE
    width_idx = 6
    h, w = 10, 20
    river_map = np.full((h, w), 254, dtype=np.uint8)
    # 主干
    river_map[5, 3:15] = width_idx
    river_map[5, 3] = RIVER_SOURCE
    # 支流
    river_map[3, 10] = RIVER_SOURCE
    river_map[4, 10] = width_idx

    warnings = validate_rivers(river_map)
    for w_text in warnings:
        assert "sources" not in w_text.lower()
        assert "源头" not in w_text or "缺少" in w_text


def test_river_validate_no_source_warns():
    """无源头的河流应报警告。"""
    from domain.managers.river import validate_rivers
    h, w = 10, 20
    river_map = np.full((h, w), 254, dtype=np.uint8)
    river_map[5, 3:15] = 6
    warnings = validate_rivers(river_map)
    assert any("source" in w.lower() or "源头" in w for w in warnings)


# ═══════ 本地化导出 ═══════

def test_localisation_vp_names(tmp_path):
    """导出本地化时 VP 用自定义城市名。"""
    from domain.managers.state import StateManager
    from export.writers.localisation.yml import write_localisation_full

    mgr = StateManager()
    state = mgr.create_state()
    sid = state.id
    state.name = "TestState"
    mgr.assign_province(100, sid)
    mgr.set_vp(100, 10, name="MyCity")

    write_localisation_full("TestMod", mgr, None, [sid], str(tmp_path))

    # localisation 拆分后 VP 写在 states 文件
    yml_path = tmp_path / "localisation" / "zz_TestMod_states_l_english.yml"
    content = yml_path.read_text(encoding="utf-8-sig")
    assert 'VICTORY_POINTS_100:0 "MyCity"' in content


def test_localisation_vp_fallback(tmp_path):
    """VP 没自定义名时用 State 名。"""
    from domain.managers.state import StateManager
    from export.writers.localisation.yml import write_localisation_full

    mgr = StateManager()
    state = mgr.create_state()
    sid = state.id
    state.name = "Berlin Region"
    mgr.assign_province(200, sid)
    mgr.set_vp(200, 5)

    write_localisation_full("TestMod", mgr, None, [sid], str(tmp_path))

    yml_path = tmp_path / "localisation" / "zz_TestMod_states_l_english.yml"
    content = yml_path.read_text(encoding="utf-8-sig")
    assert 'VICTORY_POINTS_200:0 "Berlin Region"' in content


# ═══════ trees_bmp ═══════

def test_trees_bmp_dynamic_size():
    """trees_bmp 处理非标准地图尺寸不崩。"""
    from export.writers.map.trees_bmp import auto_generate_tree_map
    terrain = np.zeros((1024, 2048), dtype=np.uint8)
    tree_map = auto_generate_tree_map(terrain)
    assert tree_map.shape == (256, 512)


# ═══════ 大洲分配 ═══════

def test_continent_assign_by_state():
    """大洲按 State 批量分配。"""
    from domain.managers.continent import ContinentManager
    from domain.managers.state import StateManager

    cm = ContinentManager()
    cm.add_continent("europe")
    sm = StateManager()
    state = sm.create_state()
    sid = state.id
    sm.assign_province(1, sid)
    sm.assign_province(2, sid)
    sm.assign_province(3, sid)

    s = sm.get_state(sid)
    for p in s.provinces:
        cm.assign_province(p, 0)

    assert cm.get_province_continent(1) == 0
    assert cm.get_province_continent(2) == 0
    assert cm.get_province_continent(3) == 0


# ═══════ MOD 空目录 ═══════

def test_create_mod_skeleton(tmp_path):
    """新项目创建空目录结构。"""
    from services.project_service import create_mod_skeleton
    out = str(tmp_path / "test_mod")
    create_mod_skeleton(out)
    import os
    assert os.path.isdir(os.path.join(out, "common", "countries"))
    assert os.path.isdir(os.path.join(out, "history", "states"))
    assert os.path.isdir(os.path.join(out, "map", "strategicregions"))
    assert os.path.isdir(os.path.join(out, "gfx", "flags"))
    assert os.path.isdir(os.path.join(out, "localisation"))
    assert os.path.isdir(os.path.join(out, "events"))
