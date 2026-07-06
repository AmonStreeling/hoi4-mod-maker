"""ResplitStateCommand 测试 — 州内重分割/州外不动/undo/redo"""
import numpy as np
import pytest

from commands.state.resplit import ResplitStateCommand
from domain.managers.state import StateManager, StateData
from data.constants import TILE_LAND


class _FakeMapData:
    def __init__(self, h=48, w=48):
        self.tile_map = np.full((h, w), TILE_LAND, dtype=np.uint8)
        self.province_map = np.zeros((h, w), dtype=np.int32)


@pytest.fixture
def setup():
    md = _FakeMapData()
    # 左半 = 省份 1 (州外); 右半上/下 = 省份 2/3 (目标州)
    md.province_map[:, :20] = 1
    md.province_map[:24, 24:] = 2
    md.province_map[24:, 24:] = 3
    # 中间一条 pm==0 的未分配带 (x 20~23), 模拟新画陆地
    mgr = StateManager()
    mgr._states[7] = StateData(id=7, provinces=[2, 3])
    mgr._province_to_state = {2: 7, 3: 7}
    mgr._states[7].victory_points = {2: 5}
    mgr._states[7].vp_names = {2: "旧城"}
    return md, mgr


def test_resplit_only_inside_state(setup):
    md, mgr = setup
    old_pm = md.province_map.copy()
    inside = np.isin(old_pm, [2, 3])

    cmd = ResplitStateCommand(md, mgr, 7, 6)
    cmd.execute()

    # 州外像素 (省份 1 + 未分配带) 一个都没变
    assert (md.province_map[~inside] == old_pm[~inside]).all()
    # 州内全部换成新 id (> 3)
    new_ids = np.unique(md.province_map[inside])
    assert (new_ids > 3).all()
    # 新省份归回该州, 反查表同步, VP 清空
    state = mgr.get_state(7)
    assert sorted(state.provinces) == sorted(int(i) for i in new_ids)
    assert all(mgr.get_state_of_province(int(i)) == 7 for i in new_ids)
    assert state.victory_points == {} and state.vp_names == {}


def test_resplit_undo_redo(setup):
    md, mgr = setup
    old_pm = md.province_map.copy()

    cmd = ResplitStateCommand(md, mgr, 7, 6)
    cmd.execute()
    after_pm = md.province_map.copy()
    after_provinces = list(mgr.get_state(7).provinces)

    cmd.undo()
    assert (md.province_map == old_pm).all()
    state = mgr.get_state(7)
    assert sorted(state.provinces) == [2, 3]
    assert state.victory_points == {2: 5}
    assert mgr.get_state_of_province(2) == 7

    cmd.execute()  # redo 回放, 结果和第一次完全一致
    assert (md.province_map == after_pm).all()
    assert list(mgr.get_state(7).provinces) == after_provinces
