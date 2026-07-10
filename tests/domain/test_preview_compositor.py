"""
预览合成器测试 — 用假贴图验证分层叠加逻辑, 不依赖游戏文件。
"""

import numpy as np

from domain.preview.compositor import compose_preview, _texture_lut, _hillshade
from data.constants import TILE_LAND, TILE_SEA, SEA_LEVEL


def _fake_atlas(tile_count: int = 16, size: int = 4) -> np.ndarray:
    """每个瓦片纯色: R 通道 = 瓦片号×10, 便于断言来源。"""
    tiles = np.zeros((tile_count, size, size, 4), dtype=np.uint8)
    for i in range(tile_count):
        tiles[i, :, :, 0] = i * 10
        tiles[i, :, :, 3] = 255
    return tiles


def _flat_world(h: int = 8, w: int = 8):
    """全陆地、平坦高度的基础世界。"""
    tile_map = np.full((h, w), TILE_LAND, dtype=np.uint8)
    terrain_map = np.zeros((h, w), dtype=np.uint8)
    height_map = np.full((h, w), SEA_LEVEL + 20, dtype=np.uint8)
    return tile_map, terrain_map, height_map


def test_texture_lut_fallback():
    """未定义索引回落到平原瓦片; 越界瓦片号 (湖泊 255) 同样回落。"""
    lut = _texture_lut({0: 1, 6: 11, 14: 255}, tile_count=16)
    assert lut[0] == 1
    assert lut[6] == 11
    assert lut[14] == 1   # 255 越界 → 回落到索引 0 的映射 (瓦片 1)
    assert lut[99] == 1   # 未定义 → 同上


def test_land_uses_mapped_tile():
    """陆地像素的颜色来自映射的瓦片 (R = 瓦片号×10 × 光照系数)。"""
    tile_map, terrain_map, height_map = _flat_world()
    terrain_map[:] = 3                       # 调色板索引 3
    out = compose_preview(tile_map, terrain_map, height_map, None,
                          _fake_atlas(), {0: 1, 3: 9})

    assert out.shape == (8, 8, 3)
    # 平坦地形 → 全图同一亮度; 瓦片 9 → R 基色 90, 乘光照后仍应远大于瓦片 1 的 10
    assert out[:, :, 0].min() == out[:, :, 0].max()
    assert out[4, 4, 0] > 40


def test_water_overrides_texture():
    """海洋像素不显示地形材质, 而是按深度的蓝色。"""
    tile_map, terrain_map, height_map = _flat_world()
    tile_map[:, :4] = TILE_SEA
    height_map[:, :4] = 0                    # 深海

    out = compose_preview(tile_map, terrain_map, height_map, None,
                          _fake_atlas(), {0: 1})

    sea = out[0, 0]
    land = out[0, 7]
    assert sea[2] > sea[0]                   # 海是蓝色主导
    assert not np.array_equal(sea, land)


def test_near_coast_lighter_than_open_sea():
    """近岸比远海亮 (与导出的 colormap_water 同一距岸渐变)。"""
    tile_map, terrain_map, height_map = _flat_world(h=8, w=256)
    tile_map[:, 8:] = TILE_SEA               # 左边一条陆地, 往右全是海

    out = compose_preview(tile_map, terrain_map, height_map, None,
                          _fake_atlas(), {0: 1})

    near = out[4, 10]                        # 离岸 2px
    far = out[4, 250]                        # 离岸 240px (> 80px 已到纯深海)
    assert int(near.sum()) > int(far.sum())


def test_rivers_drawn_on_top():
    """河流像素 (索引<=11) 覆盖陆地; 背景 (254/255) 不覆盖。"""
    tile_map, terrain_map, height_map = _flat_world()
    river_map = np.full((8, 8), 255, dtype=np.uint8)
    river_map[2, :] = 3                      # 一条河
    river_map[5, :] = 254                    # 陆地背景, 不是河

    out = compose_preview(tile_map, terrain_map, height_map, river_map,
                          _fake_atlas(), {0: 1})

    assert out[2, 3, 2] > out[2, 3, 0]       # 河是蓝色主导
    assert np.array_equal(out[5, 3], out[6, 3])  # 254 行与普通陆地一致


def test_hillshade_slope_darker_than_flat():
    """背光坡 (东南向) 比平地暗, 向光坡比平地亮。"""
    height = np.zeros((8, 8), dtype=np.uint8)
    height[:, :] = 100
    for x in range(8):
        height[4, x] = 100 + x * 5           # 向东升高 → 西坡向光
    shade = _hillshade(height)

    flat = shade[0, 4]
    assert shade[4, 4] != flat               # 坡面亮度偏离平地
