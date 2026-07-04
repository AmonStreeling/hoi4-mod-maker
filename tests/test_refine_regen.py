"""
选区从零重新生成地势测试 — refine_heightmap_region 的 regenerate 分支。
"""

import numpy as np

from services.terrain_service import refine_heightmap_region
from commands.map.refine_height_region import (
    RefineHeightRegionCommand, RefineParams)
from data.constants import TILE_LAND, TILE_SEA, SEA_LEVEL


def _world(h=200, w=300):
    tile_map = np.full((h, w), TILE_LAND, dtype=np.uint8)
    tile_map[:, :30] = TILE_SEA
    height_map = np.full((h, w), SEA_LEVEL + 40, dtype=np.uint8)
    return tile_map, height_map


def _lasso_mask(h=200, w=300):
    mask = np.zeros((h, w), dtype=bool)
    mask[50:150, 80:220] = True
    return mask


def test_regenerate_only_touches_mask():
    """选区外一个像素都不动; 选区内被重做。"""
    tile_map, height_map = _world()
    mask = _lasso_mask()
    out = refine_heightmap_region(
        height_map, mask, tile_map, seed=3, regenerate=True)

    assert np.array_equal(out[~mask], height_map[~mask])
    assert not np.array_equal(out[mask], height_map[mask])


def test_regenerate_edges_blend_smoothly():
    """选区边界无悬崖: 边界内侧一圈与原图差值很小 (羽化衔接)。"""
    tile_map, height_map = _world()
    mask = _lasso_mask()
    out = refine_heightmap_region(
        height_map, mask, tile_map, seed=3, regenerate=True)

    # 选区上边界内侧第 1 行: 混合权重接近 0 → 应与原图几乎一致
    border_row = out[50, 80:220].astype(np.int32)
    original_row = height_map[50, 80:220].astype(np.int32)
    assert int(np.abs(border_row - original_row).max()) <= 3


def test_regenerate_deterministic_and_seed_varies():
    tile_map, height_map = _world()
    mask = _lasso_mask()
    a = refine_heightmap_region(height_map, mask, tile_map, seed=7, regenerate=True)
    b = refine_heightmap_region(height_map, mask, tile_map, seed=7, regenerate=True)
    c = refine_heightmap_region(height_map, mask, tile_map, seed=8, regenerate=True)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)


def test_command_undo_restores_exactly():
    """走命令路径: 执行改变选区, 撤销逐像素还原。"""
    from types import SimpleNamespace
    tile_map, height_map = _world()
    mask = _lasso_mask()
    md = SimpleNamespace(height_map=height_map.copy(), tile_map=tile_map)
    before = md.height_map.copy()

    cmd = RefineHeightRegionCommand(
        md, mask, RefineParams(seed=5, regenerate=True))
    cmd.execute()
    assert not np.array_equal(md.height_map, before)

    cmd.undo()
    assert np.array_equal(md.height_map, before)
