"""
保形美化地形测试 — 布局保留 / 实测比例混变体 / 保护像素。
"""

from types import SimpleNamespace

import numpy as np

from domain.generators.terrain_beautify import (
    beautify_terrain, TerrainBeautifyGenerator, TerrainBeautifyParams,
    IDX_URBAN,
)
from domain.generators.terrain_detail import (
    IDX_PLAINS, IDX_PLAINS_VAR, IDX_FOREST, IDX_FOREST_VAR,
    IDX_OCEAN, IDX_LAKES, IDX_MARSH, IDX_SNOW_MOUNTAIN,
)
from data.constants import TILE_LAND, TILE_SEA, TILE_LAKE, SEA_LEVEL
from data.terrain_types import PALETTE_TO_TYPE


def _world(h=256, w=512):
    """左半森林右半平原的手画世界, 顶部一条海。"""
    tile_map = np.full((h, w), TILE_LAND, dtype=np.uint8)
    tile_map[:20, :] = TILE_SEA
    terrain = np.full((h, w), IDX_PLAINS, dtype=np.uint8)
    terrain[:, :w // 2] = IDX_FOREST
    terrain[:20, :] = IDX_OCEAN
    height = np.full((h, w), SEA_LEVEL + 5, dtype=np.uint8)
    return tile_map, terrain, height


def test_layout_families_preserved():
    """作者画的家族布局基本不变 (扭曲只动边界, 不搬家)。"""
    tile_map, terrain, height = _world()
    out = beautify_terrain(terrain, tile_map, height, seed=1)

    fam = np.vectorize(lambda i: PALETTE_TO_TYPE.get(int(i), ""))
    # 远离边界的采样区: 左侧深处应仍是森林家族, 右侧深处仍是平原家族
    left = fam(out[100:200, 50:200])
    right = fam(out[100:200, 300:460])
    assert (left == "forest").mean() > 0.95
    assert (right == "plains").mean() > 0.95


def test_variant_mix_matches_vanilla_ratio():
    """森林块内变体比例贴近原版实测 67:33 (±8%)。"""
    tile_map, terrain, height = _world()
    out = beautify_terrain(terrain, tile_map, height, seed=2)

    forest_zone = out[30:, :256]
    total = np.isin(forest_zone, [IDX_FOREST, IDX_FOREST_VAR]).sum()
    var_ratio = (forest_zone == IDX_FOREST_VAR).sum() / max(int(total), 1)
    assert 0.25 < var_ratio < 0.41


def test_water_urban_marsh_protected():
    """海/湖强制还原; 城市与沼泽 (作者的明确设计) 原样保留。"""
    tile_map, terrain, height = _world()
    tile_map[100:110, 100:110] = TILE_LAKE
    terrain[150:160, 150:160] = IDX_URBAN
    terrain[200:210, 300:310] = IDX_MARSH
    height[150:170, 140:320] = SEA_LEVEL + 70          # 高海拔也不能覆盖保护区

    out = beautify_terrain(terrain, tile_map, height, seed=3)

    assert np.all(out[:20, :] == IDX_OCEAN)
    assert np.all(out[100:110, 100:110] == IDX_LAKES)
    assert np.all(out[150:160, 150:160] == IDX_URBAN)
    assert np.all(out[200:210, 300:310] == IDX_MARSH)


def test_elevation_overlay_snow_peaks():
    """超过雪线的高地点缀雪山 (阈值为原版实测 +60)。"""
    tile_map, terrain, height = _world()
    height[120:130, 400:420] = SEA_LEVEL + 70
    out = beautify_terrain(terrain, tile_map, height, seed=4)
    assert np.all(out[122:128, 402:418] == IDX_SNOW_MOUNTAIN)


def test_generator_protocol():
    """协议: 不改输入; 同种子可复现。"""
    tile_map, terrain, height = _world()
    md = SimpleNamespace(terrain_map=terrain, tile_map=tile_map,
                         height_map=height)
    before = terrain.copy()
    gen = TerrainBeautifyGenerator()

    a = gen.generate(md, TerrainBeautifyParams(seed=7))
    b = gen.generate(md, TerrainBeautifyParams(seed=7))

    assert np.array_equal(md.terrain_map, before)      # 输入零修改
    assert np.array_equal(a, b)
    assert gen.target_layer == "terrain_map"
