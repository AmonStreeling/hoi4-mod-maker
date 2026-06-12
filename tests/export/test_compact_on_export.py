"""
导出时省份 ID 压实测试 — 只压导出副本, 项目数据零改动。

工程故意带编号空洞 (省份 1/5/9, 空洞 2-4/6-8):
1. 导出后项目本体 (province_map / 各 manager) 与导出前逐字节一致
2. 导出的 definition.csv 编号连续 (0..N 无空洞)
3. 铁路 / 补给节点在导出文件里按新编号重映射
"""

import os
import shutil
import tempfile

import numpy as np
import pytest

from domain.managers.state import StateManager, StateData
from domain.managers.country import CountryManager
from domain.managers.continent import ContinentManager
from domain.managers.railway import RailwayManager
from domain.managers.supply_node import SupplyNodeManager
from export.mod_exporter import export_full_mod
from data.constants import MAP_WIDTH, MAP_HEIGHT, TILE_LAND, TILE_SEA


def _build_gappy_project():
    """迷你工程: 省份 ID 1/5/9 带空洞 (模拟合并掉 2-4/6-8 后的状态)."""
    tile_map = np.full((MAP_HEIGHT, MAP_WIDTH), TILE_LAND, dtype=np.uint8)
    tile_map[0, :] = TILE_SEA
    tile_map[-1, :] = TILE_SEA
    tile_map[:, 0] = TILE_SEA
    tile_map[:, -1] = TILE_SEA

    province_map = np.zeros((MAP_HEIGHT, MAP_WIDTH), dtype=np.int32)
    mid = MAP_WIDTH // 2
    province_map[1:-1, 1:mid] = 1       # 左半陆
    province_map[1:-1, mid:-1] = 5      # 右半陆 (空洞 2-4)
    province_map[tile_map == TILE_SEA] = 9  # 边框海 (空洞 6-8)

    state_mgr = StateManager()
    s1 = StateData(id=1, name="TestState", provinces=[1, 5],
                   manpower=100000, category="town", owner_tag="TST")
    state_mgr._states[1] = s1
    state_mgr._province_to_state = {1: 1, 5: 1}
    state_mgr._next_id = 2

    country_mgr = CountryManager()
    country_mgr.create_country("TST", "TestLand", (100, 100, 200))
    country_mgr.set_capital("TST", 1)
    country_mgr.assign_state(1, "TST")

    continent_mgr = ContinentManager()

    railway_mgr = RailwayManager()
    railway_mgr.add(1, [1, 5])

    supply_mgr = SupplyNodeManager()
    supply_mgr.add(5)

    return (tile_map, province_map, state_mgr, country_mgr,
            continent_mgr, railway_mgr, supply_mgr)


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


@pytest.mark.slow
def test_export_compacts_copy_without_mutating_project():
    (tile_map, province_map, state_mgr, country_mgr,
     continent_mgr, railway_mgr, supply_mgr) = _build_gappy_project()

    pm_before = province_map.copy()

    tmpdir = tempfile.mkdtemp(prefix="hoi4_compact_test_")
    try:
        export_full_mod(
            tile_map=tile_map,
            province_map=province_map,
            output_dir=tmpdir,
            mod_name="CompactTest",
            tag="TST",
            state_mgr=state_mgr,
            country_mgr=country_mgr,
            continent_mgr=continent_mgr,
            railway_mgr=railway_mgr,
            supply_mgr=supply_mgr,
        )

        # ── 1. 项目本体零改动 ──
        assert np.array_equal(province_map, pm_before), \
            "导出不应修改项目的 province_map"
        assert state_mgr._states[1].provinces == [1, 5], \
            "导出不应修改 state 的省份列表"
        assert country_mgr.get_country("TST").capital == 1
        assert railway_mgr.get_all()[0].province_ids == [1, 5], \
            "导出不应修改铁路数据"
        assert [n.province_id for n in supply_mgr.get_all()] == [5], \
            "导出不应修改补给节点数据"

        # ── 2. definition.csv 编号连续 (1→1, 5→2, 9→3) ──
        defn = _read(os.path.join(tmpdir, "map", "definition.csv"))
        ids = [int(line.split(";")[0])
               for line in defn.strip().splitlines() if line.strip()]
        assert ids == list(range(len(ids))), \
            f"definition.csv 编号必须从 0 连续: 实际 {ids[:10]}..."
        assert max(ids) == 3  # 0 + 3 个省份

        # ── 3. 导出文件按新编号重映射 ──
        # railways.txt 行格式: level 省份数 省份... → 铁路 [1,5] 压实后 = "1 2 1 2"
        railways = _read(os.path.join(tmpdir, "map", "railways.txt"))
        assert "1 2 1 2" in railways, \
            f"铁路应重映射为省份 1,2: 实际内容 {railways!r}"
        # supply_nodes.txt 行格式: level 省份 → 节点在省份 5(新编号 2) = "1 2"
        supply = _read(os.path.join(tmpdir, "map", "supply_nodes.txt"))
        assert "1 2" in supply, \
            f"补给节点应重映射为省份 2: 实际内容 {supply!r}"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
