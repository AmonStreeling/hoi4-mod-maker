"""
保形美化地形 — 保留作者画的布局, 把粗糙色块渲染出原版级细节。

与"按气候细化"(terrain_detail, 从零按纬度铺) 互补:
这里**作者画的哪里是森林哪里是沙漠一律不变**, 只做三件事:

1. 边界自然化: 域扭曲 (domain warping) — 用平滑噪声轻推每个像素的
   采样位置, 笔直的色块分界变成有机的犬牙交错; 布局宏观不变
2. 块内混变体: 单一色块按原版实测比例掺入同家族变体
   (森林 67:33, 沙漠 44:32:14:10, 山地 42:34:22, 平原 91:7, 丛林 87:13
    — tools/vanilla_terrain_stats.py 2026-07-04 实测)
3. 海拔叠加: 高处自动点缀丘陵/山地/雪线 (阈值同为原版实测)

水体(海/湖)与城市像素原样保留; 海陆边界不参与扭曲 (海岸线神圣)。
全 numpy 向量化, 零 Qt; 只读输入, 返回新数组。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import gaussian_filter

from data.constants import TILE_LAND, TILE_LAKE, SEA_LEVEL
from data.terrain_types import PALETTE_TO_TYPE
from domain.generators.base import GeneratorParams
from domain.generators.terrain_detail import (
    _quantile_thresholds,
    IDX_PLAINS, IDX_PLAINS_VAR, IDX_FOREST, IDX_FOREST_VAR,
    IDX_DESERT, IDX_DESERT_VAR, IDX_DESERT_ROCK, IDX_DESERT_HILLS,
    IDX_DESERT_MOUNTAIN, IDX_HILLS, IDX_MOUNTAIN, IDX_MOUNTAIN_VAR,
    IDX_MOUNTAIN_GRASS, IDX_SNOW_MOUNTAIN, IDX_JUNGLE, IDX_JUNGLE_VAR,
    IDX_JUNGLE_MOUNTAIN, IDX_LAKES, IDX_OCEAN, IDX_MARSH,
    HILL_START, MOUNTAIN_START, SNOW_PEAK_START,
)

IDX_URBAN = 13

# 家族 → (变体索引列表, 累计占比阈值) — 原版实测混合比例
_FAMILY_MIX: dict[str, tuple[list[int], list[float]]] = {
    "plains":   ([IDX_PLAINS, IDX_PLAINS_VAR],                        [0.91]),
    "forest":   ([IDX_FOREST, IDX_FOREST_VAR],                        [0.67]),
    "jungle":   ([IDX_JUNGLE, IDX_JUNGLE_VAR],                        [0.87]),
    "desert":   ([IDX_DESERT, IDX_DESERT_VAR, IDX_DESERT_HILLS,
                  IDX_DESERT_ROCK],                                   [0.44, 0.76, 0.90]),
    "mountain": ([IDX_MOUNTAIN, IDX_MOUNTAIN_GRASS, IDX_MOUNTAIN_VAR], [0.42, 0.76]),
}


@dataclass(frozen=True)
class TerrainBeautifyParams(GeneratorParams):
    """保形美化参数。warp_strength = 边界扭曲幅度 (像素)。"""
    warp_strength: float = 6.0


class TerrainBeautifyGenerator:
    """保形美化 — 路线 C 的第三个生成器。"""

    id = "terrain_beautify"
    target_layer = "terrain_map"

    def default_params(self) -> TerrainBeautifyParams:
        return TerrainBeautifyParams()

    def generate(self, map_data, params: TerrainBeautifyParams,
                 mask: np.ndarray | None = None) -> np.ndarray:
        out = beautify_terrain(
            map_data.terrain_map, map_data.tile_map, map_data.height_map,
            seed=params.seed, warp_strength=params.warp_strength,
        )
        if mask is not None:
            out = np.where(mask, out, map_data.terrain_map)
        return out.astype(np.uint8)


def beautify_terrain(
    terrain_map: np.ndarray,
    tile_map: np.ndarray,
    height_map: np.ndarray,
    seed: int = 0,
    warp_strength: float = 6.0,
) -> np.ndarray:
    """保形美化, 返回新的 terrain_map (H, W) uint8。"""
    h, w = terrain_map.shape
    rng = np.random.default_rng(seed)
    land = tile_map == TILE_LAND

    # ── 1. 域扭曲: 边界自然化 (只在陆地内部采样, 海岸线不动) ──
    def _smooth(sigma: float) -> np.ndarray:
        f = gaussian_filter(rng.standard_normal((h, w)).astype(np.float32), sigma)
        return f / max(float(np.abs(f).max()), 1e-6)

    dy = (_smooth(9.0) * warp_strength).round().astype(np.int32)
    dx = (_smooth(9.0) * warp_strength).round().astype(np.int32)
    yy, xx = np.mgrid[0:h, 0:w]
    sy = np.clip(yy + dy, 0, h - 1)
    sx = np.clip(xx + dx, 0, w - 1)
    warped = terrain_map[sy, sx]
    # 三类像素不参与扭曲, 原样保留:
    # 1) 自身是水 / 采样源是水 — 海岸线与湖岸神圣
    # 2) 自身或采样源是城市/沼泽 — 作者显式放置的点位, 不能被
    #    扭进(边缘被邻居啃掉)也不能被扭出(涂抹到周围)
    src_is_land = land[sy, sx]
    orig_protected = np.isin(terrain_map, [IDX_URBAN, IDX_MARSH])
    src_protected = orig_protected[sy, sx]
    warp_ok = land & src_is_land & ~orig_protected & ~src_protected
    base = np.where(warp_ok, warped, terrain_map).astype(np.uint8)

    # ── 2. 块内混变体 (按原版实测比例) ──
    variant_low = _smooth(55.0)
    variant_fine = _smooth(2.5)
    variant_noise = variant_low * 0.7 + variant_fine * 0.3   # 细粒对齐原版斑块密度

    # 当前像素属于哪个家族 (按调色板索引 → provincial type)
    fam_lut = np.full(256, "", dtype=object)
    for idx, t in PALETTE_TO_TYPE.items():
        fam_lut[idx] = t
    families = fam_lut[base]

    out = base.copy()
    for fam, (variants, fracs) in _FAMILY_MIX.items():
        fam_mask = (families == fam) & land
        if not bool(fam_mask.any()):
            continue
        thresholds = _quantile_thresholds(variant_noise, fracs)
        sel = out[fam_mask]
        noise_vals = variant_noise[fam_mask]
        sel[:] = variants[0]
        for t, var_idx in zip(thresholds, variants[1:]):
            sel[noise_vals > t] = var_idx
        out[fam_mask] = sel

    # ── 3. 海拔叠加 (城市/沼泽不动 — 那是作者的明确设计) ──
    # 保护判定用原图 (orig_protected), 与扭曲阶段同一基准
    hf = height_map.astype(np.float32) - float(SEA_LEVEL)
    overlay_ok = land & ~orig_protected

    is_desert_fam = (families == "desert")
    hills = overlay_ok & (hf >= HILL_START) & (hf < MOUNTAIN_START)
    out[hills & is_desert_fam] = IDX_DESERT_HILLS

    mountains = overlay_ok & (hf >= MOUNTAIN_START)
    q_m1, q_m2 = _quantile_thresholds(variant_noise, [0.42, 0.76])
    out[mountains] = IDX_MOUNTAIN
    out[mountains & (variant_noise > q_m1)] = IDX_MOUNTAIN_GRASS
    out[mountains & (variant_noise > q_m2)] = IDX_MOUNTAIN_VAR
    out[mountains & is_desert_fam] = IDX_DESERT_MOUNTAIN

    out[overlay_ok & (hf >= SNOW_PEAK_START)] = IDX_SNOW_MOUNTAIN

    # ── 4. 水体强制还原 ──
    out[tile_map == TILE_LAKE] = IDX_LAKES
    out[~land & (tile_map != TILE_LAKE)] = IDX_OCEAN
    return out.astype(np.uint8)
