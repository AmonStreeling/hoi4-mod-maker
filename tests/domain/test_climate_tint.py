"""
自动气候色调测试 — 纬度气候带 / 海拔修正 / 水体中性。
"""

import numpy as np

from domain.preview.climate_tint import generate_climate_tint
from data.constants import TILE_LAND, TILE_SEA, SEA_LEVEL


def _world(h=180, w=64):
    tile_map = np.full((h, w), TILE_LAND, dtype=np.uint8)
    height_map = np.full((h, w), SEA_LEVEL + 10, dtype=np.uint8)
    return tile_map, height_map


def test_output_shape_and_determinism():
    tile_map, height_map = _world()
    a = generate_climate_tint(tile_map, height_map, seed=7)
    b = generate_climate_tint(tile_map, height_map, seed=7)
    assert a.shape == (180, 64, 3)
    assert a.dtype == np.uint8
    assert np.array_equal(a, b)          # 同种子可复现


def test_equator_green_subtropics_yellow():
    """赤道带偏绿, 副热带干燥带相对更黄 (R-G 差值更大)。

    气候带边界有噪声蜿蜒, 所以比较带状区域的均值而不是单行。
    """
    tile_map, height_map = _world()
    tint = generate_climate_tint(tile_map, height_map).astype(np.int32)
    eq_band = tint[85:96]                 # 赤道附近
    sub_band = tint[148:166]              # |纬度| ≈ 29°~38°
    eq_yellowness = float((eq_band[:, :, 0] - eq_band[:, :, 1]).mean())
    sub_yellowness = float((sub_band[:, :, 0] - sub_band[:, :, 1]).mean())
    assert eq_yellowness < 0              # 赤道绿 (G>R)
    assert sub_yellowness > eq_yellowness + 10


def test_poles_brighter_than_tropics():
    """极地雪白比赤道亮。"""
    tile_map, height_map = _world()
    tint = generate_climate_tint(tile_map, height_map)
    assert int(tint[0].mean()) > int(tint[90].mean())


def test_high_mountains_turn_snowy():
    """超过雪线的高山接近雪白, 明显亮于同纬度平地。"""
    tile_map, height_map = _world()
    height_map[100, 10] = SEA_LEVEL + 130
    tint = generate_climate_tint(tile_map, height_map)
    assert int(tint[100, 10].sum()) > int(tint[100, 40].sum()) + 60


def test_water_is_neutral():
    """水体像素输出中性 128 (会被水色覆盖, 但不能乱)。"""
    tile_map, height_map = _world()
    tile_map[:, :8] = TILE_SEA
    tint = generate_climate_tint(tile_map, height_map)
    assert np.all(tint[:, :8] == 128)
