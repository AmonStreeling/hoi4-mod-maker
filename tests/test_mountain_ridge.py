"""
画山脉线测试 — 升级后的真实山链行为（此前无测试覆盖）。
"""

import numpy as np

from services.terrain_service import apply_mountain_ridge
from data.constants import TILE_LAND, TILE_SEA, SEA_LEVEL


def _world(h=200, w=400):
    tile_map = np.full((h, w), TILE_LAND, dtype=np.uint8)
    tile_map[:, :40] = TILE_SEA
    height_map = np.full((h, w), SEA_LEVEL + 20, dtype=np.uint8)
    return tile_map, height_map


def test_ridge_raises_heights_near_line_only():
    """山脊线附近升高, 远处和海洋不动。"""
    tile_map, height_map = _world()
    points = [(100, 80), (100, 350)]
    out = apply_mountain_ridge(height_map, tile_map, points, peak_height=220)

    assert int(out[100, 200]) > 150            # 脊上
    assert int(out[10, 200]) == SEA_LEVEL + 20  # 远处平原不动
    assert np.array_equal(out[:, :40], height_map[:, :40])  # 海洋不动


def test_crest_has_peaks_and_passes():
    """沿脊高度有起伏 (主峰与垭口), 不再是均匀土堆。"""
    tile_map, height_map = _world()
    points = [(100, 80), (100, 350)]
    out = apply_mountain_ridge(height_map, tile_map, points, peak_height=220)

    crest = out[100, 90:340].astype(np.int32)   # 沿脊取样
    assert crest.max() - crest.min() > 25       # 有显著峰谷起伏
    assert crest.min() > 100                    # 但垭口仍是山, 不断链


def test_same_line_is_deterministic():
    """同一条线两次调用结果一致 (调滑条预览时山形不跳变)。"""
    tile_map, height_map = _world()
    points = [(60, 100), (140, 300)]
    a = apply_mountain_ridge(height_map, tile_map, points, peak_height=200)
    b = apply_mountain_ridge(height_map, tile_map, points, peak_height=200)
    assert np.array_equal(a, b)
