"""
预览合成器 — 把项目数据 + 游戏原版贴图合成"游戏内观感"的画面。

分层叠加 (全部 numpy 向量化, 零 Qt):
1. 地形材质铺底: terrain_map 调色板索引 → atlas 瓦片 → 按像素坐标平铺采样
2. 高度光影: 高度图梯度算法线, 与平行光点积得到明暗 (近似游戏 shader)
3. 海洋/湖泊: 距岸渐变, 公式与导出的 colormap_water 相同 (domain/water_colormap)
4. 河流: 河流像素覆盖为河水色

材质/映射来自游戏本体 (services/game_assets), 光影公式是近似——
定位是"够判断地图长什么样", 不追求和游戏逐像素一致。
"""

from __future__ import annotations

import numpy as np

from data.constants import TILE_LAND

# 河流颜色 (略亮于浅滩, 在陆地上才看得清)
RIVER_RGB = np.array([60, 120, 190], dtype=np.float32)
# river_map 中 <= 11 的索引是河流数据 (254/255 是背景)
RIVER_MAX_INDEX = 11

# 光照: 西北上方平行光 + 环境光底色 (游戏的光也来自西北)
LIGHT_DIR = (-0.5, -0.5, 1.0)
AMBIENT = 0.55       # 环境光强度 (没有光照时的最低亮度)
DIFFUSE = 0.65       # 漫反射强度 (受坡向影响的部分)
# 高度梯度转法线的陡峭系数: 越大山体明暗对比越强
SLOPE_SCALE = 3.0


def _texture_lut(terrain_to_texture: dict[int, int], tile_count: int) -> np.ndarray:
    """调色板索引(0..255) → 瓦片号 的查找表。

    未定义的索引和越界瓦片号 (如湖泊的 texture=255) 回落到
    平原瓦片 (索引 0 的映射, 没有就用 0 号瓦片) —— 这些像素
    随后会被水体层覆盖, 铺什么底无所谓, 只要不越界。
    """
    fallback = terrain_to_texture.get(0, 0)
    if not (0 <= fallback < tile_count):
        fallback = 0
    lut = np.full(256, fallback, dtype=np.int32)
    for palette_idx, tex in terrain_to_texture.items():
        if 0 <= palette_idx < 256 and 0 <= tex < tile_count:
            lut[palette_idx] = tex
    return lut


def _hillshade(height_map: np.ndarray) -> np.ndarray:
    """高度图 → 每像素亮度系数 (H, W) float32, 约 [AMBIENT, AMBIENT+DIFFUSE]。"""
    h = height_map.astype(np.float32)
    gy, gx = np.gradient(h)
    # 法线 ∝ (-gx*k, -gy*k, 1), 归一化
    nx = -gx * SLOPE_SCALE
    ny = -gy * SLOPE_SCALE
    nz = np.ones_like(nx)
    norm = np.sqrt(nx * nx + ny * ny + nz * nz)

    lx, ly, lz = LIGHT_DIR
    lnorm = (lx * lx + ly * ly + lz * lz) ** 0.5
    dot = (nx * lx + ny * ly + nz * lz) / (norm * lnorm)
    return AMBIENT + DIFFUSE * np.clip(dot, 0.0, 1.0)


def compose_preview(
    tile_map: np.ndarray,
    terrain_map: np.ndarray,
    height_map: np.ndarray,
    river_map: np.ndarray | None,
    atlas_tiles: np.ndarray,
    terrain_to_texture: dict[int, int],
    tint: np.ndarray | None = None,
) -> np.ndarray:
    """合成预览图, 返回 (H, W, 3) uint8。

    参数:
        tile_map: 陆/海/湖分类 (H, W) uint8
        terrain_map: 图形地形调色板索引 (H, W) uint8
        height_map: 高度图 (H, W) uint8
        river_map: 河流图 (H, W) uint8, None = 不画河流
        atlas_tiles: 游戏材质瓦片 (N, th, tw, 4) uint8 (game_assets.atlas_tiles)
        terrain_to_texture: 调色板索引 → 瓦片号 (game_assets.terrain_to_texture)
        tint: 区域色调图 (H, W, 3) uint8, None = 不调色。
              P社 shader 惯例: 材质 × 色调 × 2 (色调 128 即原色)
    """
    h, w = tile_map.shape
    tile_count, th, tw = atlas_tiles.shape[0], atlas_tiles.shape[1], atlas_tiles.shape[2]

    # ── 1. 地形材质铺底 ──
    lut = _texture_lut(terrain_to_texture, tile_count)
    tex_idx = lut[terrain_map]                      # (H, W) 每像素瓦片号
    ys = np.arange(h, dtype=np.int32) % th
    xs = np.arange(w, dtype=np.int32) % tw
    ty = np.broadcast_to(ys[:, None], (h, w))       # 瓦片内坐标 (平铺采样)
    tx = np.broadcast_to(xs[None, :], (h, w))
    base = atlas_tiles[tex_idx, ty, tx, :3].astype(np.float32)

    # ── 1.5 区域色调 (北非偏黄/西欧偏绿的来源) ──
    if tint is not None:
        base = base * (tint.astype(np.float32) / 255.0) * 2.0

    # ── 2. 高度光影 ──
    shade = _hillshade(height_map)
    rgb = base * shade[:, :, None]

    # ── 3. 海洋/湖泊: 与导出的 colormap_water 同一渐变公式 ──
    # 游戏海面色源就是那张贴图, 预览直接用同款距岸渐变 → 所见即导出。
    water = tile_map != TILE_LAND
    if np.any(water):
        from domain.water_colormap import water_color_rgb
        water_rgb = water_color_rgb(tile_map)
        rgb[water] = water_rgb[water]

    # ── 4. 河流覆盖 ──
    if river_map is not None:
        rivers = river_map <= RIVER_MAX_INDEX
        rgb[rivers] = RIVER_RGB

    return np.clip(rgb, 0, 255).astype(np.uint8)
