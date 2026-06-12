"""
地形自动细化测试 — 气候带分布 / 海拔叠加 / 生成器协议。
"""

from types import SimpleNamespace

import numpy as np

from domain.generators.terrain_detail import (
    generate_detailed_terrain, TerrainDetailGenerator, TerrainDetailParams,
    IDX_OCEAN, IDX_LAKES, IDX_DESERT, IDX_DESERT_VAR, IDX_DESERT_ROCK,
    IDX_JUNGLE, IDX_JUNGLE_VAR, IDX_SNOW_MOUNTAIN, IDX_PLAINS_SNOW,
)
from data.constants import TILE_LAND, TILE_SEA, TILE_LAKE, SEA_LEVEL


def _world(h=180, w=512):
    """全陆地平坦世界 (纬度跨满 0~90)。

    宽度要足够大: 噪声斑块半径 ~14px, 窄世界里单条纬度带可能
    恰好整条落进一个斑块, 比例断言会抖。
    """
    tile_map = np.full((h, w), TILE_LAND, dtype=np.uint8)
    height_map = np.full((h, w), SEA_LEVEL + 10, dtype=np.uint8)
    return tile_map, height_map


def test_water_tiles_untouched():
    """海洋/湖泊像素固定为对应索引, 不参与气候细化。"""
    tile_map, height_map = _world()
    tile_map[:, :8] = TILE_SEA
    tile_map[:, 8:12] = TILE_LAKE
    out = generate_detailed_terrain(tile_map, height_map)
    assert np.all(out[:, :8] == IDX_OCEAN)
    assert np.all(out[:, 8:12] == IDX_LAKES)


def test_climate_bands_present():
    """赤道带有丛林、副热带有沙漠、极地有雪原 — 但都不是一刀切色块。"""
    tile_map, height_map = _world()
    out = generate_detailed_terrain(tile_map, height_map)

    eq_band = out[76:105]                      # 整条丛林带 (|纬度| < 14°)
    jungle_ratio = np.isin(eq_band, [IDX_JUNGLE, IDX_JUNGLE_VAR]).mean()
    assert 0.3 < jungle_ratio < 0.95           # 有丛林斑块, 但不是糊满

    sub_band = out[114:126]                    # |纬度| ≈ 24°~36° (h=180, 赤道在 90)
    desert_ratio = np.isin(
        sub_band, [IDX_DESERT, IDX_DESERT_VAR, IDX_DESERT_ROCK]).mean()
    assert desert_ratio > 0.3

    polar = out[:8]                            # 北极
    assert (polar == IDX_PLAINS_SNOW).mean() > 0.8


def test_high_peaks_become_snow_mountains():
    """超过雪线的高地变成雪山。"""
    tile_map, height_map = _world()
    height_map[100:104, 10:14] = SEA_LEVEL + 130
    out = generate_detailed_terrain(tile_map, height_map)
    assert np.all(out[100:104, 10:14] == IDX_SNOW_MOUNTAIN)


def test_deterministic_by_seed():
    """同种子可复现, 换种子结果不同。"""
    tile_map, height_map = _world()
    a = generate_detailed_terrain(tile_map, height_map, seed=1)
    b = generate_detailed_terrain(tile_map, height_map, seed=1)
    c = generate_detailed_terrain(tile_map, height_map, seed=2)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)


def test_generator_protocol_with_mask():
    """生成器接口: 不改 map_data; mask 外保持原图层。"""
    tile_map, height_map = _world()
    original_terrain = np.full(tile_map.shape, 99, dtype=np.uint8)
    md = SimpleNamespace(
        tile_map=tile_map, height_map=height_map,
        terrain_map=original_terrain,
    )
    gen = TerrainDetailGenerator()
    mask = np.zeros(tile_map.shape, dtype=bool)
    mask[:, :32] = True

    out = gen.generate(md, TerrainDetailParams(seed=5), mask=mask)

    assert out.dtype == np.uint8
    assert np.all(md.terrain_map == 99)        # 输入零修改
    assert np.all(out[:, 32:] == 99)           # mask 外保留原值
    assert not np.all(out[:, :32] == 99)       # mask 内被细化
    assert gen.target_layer == "terrain_map"
