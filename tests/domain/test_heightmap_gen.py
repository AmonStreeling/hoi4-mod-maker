"""
真实感高度图生成器测试 — 硬约束 / 山链与平原 / 生成器协议。
"""

from types import SimpleNamespace

import numpy as np

from domain.generators.heightmap import (
    generate_realistic_heightmap, RealisticHeightmapGenerator,
    HeightmapParams, LAND_FLOOR, SEA_CEILING,
)
from data.constants import TILE_LAND, TILE_SEA


def _world(h=256, w=512):
    """中央一块大陆, 四周海洋。"""
    tile_map = np.full((h, w), TILE_SEA, dtype=np.uint8)
    tile_map[40:-40, 60:-60] = TILE_LAND
    return tile_map


def test_hard_constraints():
    """陆地不低于安全底线, 海洋不高于海平面下限 — 防游戏崩溃的硬规矩。"""
    tile_map = _world()
    out = generate_realistic_heightmap(tile_map)
    land = tile_map == TILE_LAND
    assert out.dtype == np.uint8
    assert int(out[land].min()) >= LAND_FLOOR
    assert int(out[~land].max()) <= SEA_CEILING


def test_continental_shelf():
    """近岸海底比远海浅 (大陆架坡度)。"""
    tile_map = _world()
    out = generate_realistic_heightmap(tile_map)
    near_coast = out[128, 55]      # 离岸 5px
    deep_sea = out[128, 5]         # 远海
    assert int(near_coast) > int(deep_sea)


def test_mountains_and_plains_coexist():
    """有山 (高值) 也有大面积低平原, 不是均匀鼓包。

    海拔区间按原版实测标定 (山地 P50=+32, 峰值上限默认 165) —
    原版远比直觉"平", 游戏引擎渲染时自带垂直夸张。
    """
    tile_map = _world()
    out = generate_realistic_heightmap(
        tile_map, HeightmapParams(seed=3, mountain_coverage=0.3))
    land_vals = out[tile_map == TILE_LAND].astype(np.int32)
    assert land_vals.max() > 140                       # 存在山峰 (>海平面+45)
    plains_ratio = (land_vals < LAND_FLOOR + 10).mean()
    assert plains_ratio > 0.35                         # 大片平原


def test_deterministic_by_seed():
    tile_map = _world()
    a = generate_realistic_heightmap(tile_map, HeightmapParams(seed=9))
    b = generate_realistic_heightmap(tile_map, HeightmapParams(seed=9))
    c = generate_realistic_heightmap(tile_map, HeightmapParams(seed=10))
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)


def test_generator_protocol_with_mask():
    """生成器接口: 不改输入; mask 外保留原高度。"""
    tile_map = _world()
    original = np.full(tile_map.shape, 77, dtype=np.uint8)
    md = SimpleNamespace(tile_map=tile_map, height_map=original)
    gen = RealisticHeightmapGenerator()
    mask = np.zeros(tile_map.shape, dtype=bool)
    mask[:, :256] = True

    out = gen.generate(md, HeightmapParams(seed=1), mask=mask)

    assert np.all(md.height_map == 77)        # 输入零修改
    assert np.all(out[:, 256:] == 77)          # mask 外保留
    assert not np.all(out[:, :256] == 77)      # mask 内重生成
    assert gen.target_layer == "height_map"
