"""
compact_with_references 全量引用同步测试。

地图省份 ID 为 1/3/5（2、4 是合并留下的空洞），压实后应变为 1/2/3。
验证铁路/补给节点/邻接/邻接规则/大陆指派/省份级地形全部跟着重映射，
且指向已删省份（不在地图上的 ID）的死引用被清理。
"""

import numpy as np
import pytest

from domain.map_data import MapData
from domain.managers.railway import RailwayManager
from domain.managers.supply_node import SupplyNodeManager
from domain.managers.adjacency import AdjacencyManager, AdjacencyEntry
from domain.managers.adjacency_rule import AdjacencyRuleManager, AdjacencyRule
from domain.managers.continent import ContinentManager
from data.constants import set_map_size
import data.constants as _constants


@pytest.fixture(autouse=True)
def _restore_map_size():
    """set_map_size(8, 4) 是全局状态, 测试后必须还原, 否则污染后续测试."""
    w, h = _constants.MAP_WIDTH, _constants.MAP_HEIGHT
    yield
    set_map_size(w, h)


def _make_map_with_gaps() -> MapData:
    """省份 ID 1, 3, 5（2、4 空洞）→ 压实后 1, 2, 3。"""
    set_map_size(8, 4)
    md = MapData()
    md.province_map = np.array([
        [0, 0, 1, 1, 3, 3, 5, 5],
        [0, 0, 1, 1, 3, 3, 5, 5],
        [0, 0, 1, 1, 3, 3, 5, 5],
        [0, 0, 1, 1, 3, 3, 5, 5],
    ], dtype=np.int32)
    md.tile_map = np.ones((4, 8), dtype=np.uint8)
    return md


def test_compact_remaps_railways():
    """铁路省份重映射；引用已删省份的铁路整条丢弃。"""
    md = _make_map_with_gaps()
    rw = RailwayManager()
    rw.add(1, [1, 3, 5])
    rw.add(2, [1, 99])  # 99 不在地图上 = 死引用

    md.compact_with_references(railway_mgr=rw)

    entries = rw.get_all()
    assert len(entries) == 1
    assert entries[0].province_ids == [1, 2, 3]


def test_compact_remaps_supply_nodes():
    """补给节点重映射；死引用节点丢弃。"""
    md = _make_map_with_gaps()
    sp = SupplyNodeManager()
    sp.add(3)
    sp.add(99)

    md.compact_with_references(supply_mgr=sp)

    pids = sorted(n.province_id for n in sp.get_all())
    assert pids == [2]


def test_compact_remaps_adjacencies():
    """邻接 from/to/through 重映射；任一端是死引用则整条丢弃。"""
    md = _make_map_with_gaps()
    adj = AdjacencyManager()
    adj.add(AdjacencyEntry(from_id=1, to_id=5, type="sea", through_id=3))
    adj.add(AdjacencyEntry(from_id=1, to_id=99, type="sea"))

    md.compact_with_references(adjacency_mgr=adj)

    entries = adj.get_all()
    assert len(entries) == 1
    e = entries[0]
    assert (e.from_id, e.to_id, e.through_id) == (1, 3, 2)


def test_compact_remaps_adjacency_rules():
    """邻接规则 required_provinces / icon_province 重映射。"""
    md = _make_map_with_gaps()
    rules = AdjacencyRuleManager()
    rules.add(AdjacencyRule(
        name="CANAL", required_provinces=[1, 3, 5], icon_province=3,
    ))
    rules.add(AdjacencyRule(
        name="DEAD", required_provinces=[1, 99], icon_province=1,
    ))

    md.compact_with_references(adjacency_rule_mgr=rules)

    rule = rules.get("CANAL")
    assert rule is not None
    assert rule.required_provinces == [1, 2, 3]
    assert rule.icon_province == 2
    assert rules.get("DEAD") is None


def test_compact_remaps_continents():
    """省份→大陆指派重映射；死引用指派丢弃。"""
    md = _make_map_with_gaps()
    cont = ContinentManager()
    asia = cont.add_continent("Asia")
    cont.assign_province(3, asia)
    cont.assign_province(99, asia)

    md.compact_with_references(continent_mgr=cont)

    assert cont.get_province_continent(2) == asia
    # 99 的指派被丢弃, 3 现在是另一个省份(原 5), 应回落到默认 0
    assert cont.get_province_continent(3) == 0


def test_compact_drops_zero_pid_references():
    """引用 0 号（未分配像素）的脏数据在压实时被清掉, 不会原样穿透。"""
    md = _make_map_with_gaps()
    sp = SupplyNodeManager()
    sp.add(0)
    cont = ContinentManager()
    cont.assign_province(0, 0)

    md.compact_with_references(supply_mgr=sp, continent_mgr=cont)

    assert sp.get_all() == []
    assert 0 not in cont._province_continent


def test_compact_remaps_provincial_terrain():
    """MapData.provincial_terrain（pid→地形）重映射。"""
    md = _make_map_with_gaps()
    md.provincial_terrain = {3: "hills", 5: "mountain", 99: "plains"}

    md.compact_with_references()

    assert md.provincial_terrain == {2: "hills", 3: "mountain"}
