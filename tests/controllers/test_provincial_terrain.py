"""ProvincialTerrainController 单元测试 — 重点覆盖 sync_from_visual。"""
import numpy as np
import pytest

from model.project import Project
from model.events import EventBus
from commands.history import CommandHistory
from controllers.provincial_terrain import ProvincialTerrainController
from data.constants import TILE_LAND, TILE_SEA
from data.terrain_types import TERRAIN_PALETTE_INDEX


@pytest.fixture
def pterrain_setup():
    """创建 Project + CommandHistory + ProvincialTerrainController。

    地图: 8x8, 省份 1 (左半) + 省份 2 (右半), 全陆地。
    视觉地形: 省份 1 = forest, 省份 2 = mountain。
    """
    bus = EventBus()
    project = Project(event_bus=bus)
    history = CommandHistory(event_bus=bus)
    ctrl = ProvincialTerrainController(project, history)

    md = project.map_data
    md.province_map = np.ones((8, 8), dtype=np.int32)
    md.province_map[:, 4:] = 2
    md.tile_map = np.full((8, 8), TILE_LAND, dtype=np.uint8)
    md.terrain_map = np.full((8, 8), TERRAIN_PALETTE_INDEX["forest"], dtype=np.uint8)
    md.terrain_map[:, 4:] = TERRAIN_PALETTE_INDEX["mountain"]
    return ctrl, project, history


def test_sync_from_visual_overwrites_manual(pterrain_setup):
    """手动设过的属性也会被视觉多数地形覆盖。"""
    ctrl, project, _ = pterrain_setup
    md = project.map_data
    md.provincial_terrain[1] = "urban"   # 手动设置, 与视觉 (forest) 不一致
    md.provincial_terrain[2] = "mountain"  # 已与视觉一致

    ctrl.sync_from_visual()

    assert md.provincial_terrain[1] == "forest"
    assert md.provincial_terrain[2] == "mountain"


def test_sync_from_visual_undoable(pterrain_setup):
    """同步走命令历史, Ctrl+Z 能还原手动设置。"""
    ctrl, project, history = pterrain_setup
    md = project.map_data
    md.provincial_terrain[1] = "urban"

    ctrl.sync_from_visual()
    assert md.provincial_terrain[1] == "forest"

    history.undo()
    assert md.provincial_terrain[1] == "urban"


def test_sync_from_visual_nochange_no_command(pterrain_setup):
    """属性已一致时不产生命令 (撤销栈不变)。"""
    ctrl, project, history = pterrain_setup
    md = project.map_data
    md.provincial_terrain[1] = "forest"
    md.provincial_terrain[2] = "mountain"

    ctrl.sync_from_visual()

    assert history.can_undo is False


def test_sync_from_visual_skips_sea_province(pterrain_setup):
    """海洋省份不写入属性 dict。"""
    ctrl, project, _ = pterrain_setup
    md = project.map_data
    md.tile_map[:, 4:] = TILE_SEA  # 省份 2 变海洋

    ctrl.sync_from_visual()

    assert md.provincial_terrain.get(1) == "forest"
    assert 2 not in md.provincial_terrain
