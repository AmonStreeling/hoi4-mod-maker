"""
地形自动细化 — 按纬度/海拔/噪声给地图自动生成丰富的图形地形标注。

vanilla 地图细节丰富的根源: terrain.bmp 每隔几十像素就换地形变体
(森林斑块/丘陵过渡/沙漠岩地混排)。手画 1100 万像素不现实, 本模块
把地理规律写成规则自动生成:

1. 纬度基调: 丛林带 → 沙漠带 (副热带高压) → 温带草原/森林 → 寒带 → 雪原
2. 海拔叠加: 丘陵 → 山地 → 雪峰, 且变体跟随气候带 (沙漠里是沙漠丘陵)
3. 噪声斑块: 森林/沼泽/变体混排, 打散大色块

输出与导出共用同一套调色板索引 (data/terrain_types.GRAPHICAL_TERRAINS),
所以预览里看到什么, 导出进游戏就是什么。全 numpy 向量化, 零 Qt。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import gaussian_filter

from data.constants import TILE_LAND, TILE_LAKE, SEA_LEVEL
from domain.generators.base import GeneratorParams
from domain.preview.climate_tint import latitude_field

# ── 调色板索引 (data/terrain_types.GRAPHICAL_TERRAINS 已验证) ──
IDX_PLAINS, IDX_PLAINS_VAR = 0, 5
IDX_FOREST, IDX_FOREST_VAR = 1, 4
IDX_DESERT, IDX_DESERT_VAR, IDX_DESERT_ROCK = 3, 7, 12
IDX_DESERT_HILLS, IDX_DESERT_MOUNTAIN = 8, 11
IDX_HILLS = 17
IDX_MOUNTAIN, IDX_MOUNTAIN_VAR, IDX_MOUNTAIN_GRASS = 6, 10, 20
IDX_SNOW_MOUNTAIN, IDX_PLAINS_SNOW = 16, 19
IDX_MARSH = 9
IDX_JUNGLE, IDX_JUNGLE_VAR, IDX_JUNGLE_MOUNTAIN = 21, 22, 27
IDX_LAKES, IDX_OCEAN = 14, 15

# 海拔阈值 (高度图灰度, 相对海平面)
HILL_START = 45.0
MOUNTAIN_START = 85.0
SNOW_PEAK_START = 125.0

# 纬度带边界 (度)
JUNGLE_END = 16.0
DESERT_START, DESERT_END = 20.0, 38.0
TEMPERATE_END = 62.0
COLD_END = 74.0


def generate_detailed_terrain(
    tile_map: np.ndarray,
    height_map: np.ndarray,
    equator_y: float | None = None,
    seed: int = 0,
) -> np.ndarray:
    """生成细化的 terrain.bmp 调色板索引图 (H, W) uint8。

    只读输入, 返回新数组, 不修改任何项目数据。
    """
    h, w = tile_map.shape
    rng = np.random.default_rng(seed)

    lat = latitude_field(h, w, equator_y, seed)
    hf = height_map.astype(np.float32) - float(SEA_LEVEL)

    # 噪声场: 森林斑块 (中频) / 变体混排 (低频) / 沼泽点缀 (中频)
    forest_noise = gaussian_filter(
        rng.standard_normal((h, w)).astype(np.float32), 14.0)
    forest_noise /= max(float(np.abs(forest_noise).max()), 1e-6)
    variant_noise = gaussian_filter(
        rng.standard_normal((h, w)).astype(np.float32), 55.0)
    marsh_noise = gaussian_filter(
        rng.standard_normal((h, w)).astype(np.float32), 9.0)
    marsh_noise /= max(float(np.abs(marsh_noise).max()), 1e-6)

    out = np.full((h, w), IDX_OCEAN, dtype=np.uint8)
    land = tile_map == TILE_LAND

    # ── 1. 纬度基调 ──
    # 原则: 任何气候带都是"基调 + 斑块", 不能整带一刀切糊成色块
    base = np.full((h, w), IDX_PLAINS, dtype=np.uint8)
    base[variant_noise > 0] = IDX_PLAINS_VAR

    jungle_band = lat < JUNGLE_END
    jungle = jungle_band & (forest_noise > -0.12)        # ~6 成丛林斑块, 余下平原
    base[jungle] = IDX_JUNGLE
    base[jungle & (variant_noise > 0.2)] = IDX_JUNGLE_VAR

    desert_band = (lat >= DESERT_START) & (lat < DESERT_END)
    desert = desert_band & (variant_noise > -0.35)       # 带边缘留干草原过渡
    base[desert] = IDX_DESERT
    base[desert & (variant_noise > 0.3)] = IDX_DESERT_VAR
    base[desert & (forest_noise < -0.45)] = IDX_DESERT_ROCK

    snow = lat >= COLD_END
    base[snow] = IDX_PLAINS_SNOW

    # ── 2. 森林斑块 (密度随气候带变化, 沙漠/雪原不长树) ──
    forest_density = np.zeros((h, w), dtype=np.float32)
    forest_density[(lat >= JUNGLE_END) & (lat < DESERT_START)] = 0.15
    forest_density[(lat >= DESERT_END) & (lat < TEMPERATE_END)] = 0.30
    forest_density[(lat >= TEMPERATE_END) & (lat < COLD_END)] = 0.22
    forest = (forest_noise > (0.62 - forest_density)) & (forest_density > 0)
    base[forest] = IDX_FOREST
    base[forest & (variant_noise > 0.25)] = IDX_FOREST_VAR

    # ── 3. 沼泽点缀: 温带低洼平地 ──
    marsh = (
        (lat >= DESERT_END) & (lat < COLD_END)
        & (hf < 12.0) & (marsh_noise > 0.78) & ~forest
    )
    base[marsh] = IDX_MARSH

    # ── 4. 海拔叠加 (覆盖基调, 变体跟随气候带) ──
    hills = hf >= HILL_START
    base[hills] = IDX_HILLS
    base[hills & desert] = IDX_DESERT_HILLS

    mountains = hf >= MOUNTAIN_START
    base[mountains] = IDX_MOUNTAIN
    base[mountains & (variant_noise > 0.3)] = IDX_MOUNTAIN_VAR
    base[mountains & (variant_noise < -0.4)] = IDX_MOUNTAIN_GRASS
    base[mountains & desert] = IDX_DESERT_MOUNTAIN
    base[mountains & jungle] = IDX_JUNGLE_MOUNTAIN

    peaks = hf >= SNOW_PEAK_START
    base[peaks] = IDX_SNOW_MOUNTAIN
    # 寒带的山一律雪山
    base[mountains & snow] = IDX_SNOW_MOUNTAIN

    # ── 5. 套回水陆 ──
    out[land] = base[land]
    out[tile_map == TILE_LAKE] = IDX_LAKES
    return out


# ── 标准生成器接口 (domain/generators/base.py 协议的首个实现) ──

@dataclass(frozen=True)
class TerrainDetailParams(GeneratorParams):
    """气候细化参数。equator_y=None 表示赤道在地图垂直正中。"""
    equator_y: float | None = None


class TerrainDetailGenerator:
    """按气候细化地形 — 路线 C 的第一个生成器。"""

    id = "terrain_detail"
    target_layer = "terrain_map"

    def default_params(self) -> TerrainDetailParams:
        return TerrainDetailParams()

    def generate(self, map_data, params: TerrainDetailParams,
                 mask: np.ndarray | None = None) -> np.ndarray:
        out = generate_detailed_terrain(
            map_data.tile_map, map_data.height_map,
            equator_y=params.equator_y, seed=params.seed,
        )
        if mask is not None:
            # 掩码外保持原图层 (保护手动精修区域)
            out = np.where(mask, out, map_data.terrain_map)
        return out.astype(np.uint8)
