"""
真实感高度图生成 — 生成器协议的第 2 号成员。

解决"软乎乎圆包世界"的三个病根:
1. 山脉不成链 → 用脊状分形噪声 (ridged FBM, 1-|噪声| 天然形成
   连绵锋利的山脊线), 再用低频"山带场"把山限制在成片的山区里
2. 平原不平 → 低地振幅压到 ±2, 大片纯平光影才干净
3. 没有质感 → 多八度噪声叠加, 振幅随海拔放大 (山区粗糙平原细腻),
   坡面叠高频"侵蚀纹"

硬约束 (防游戏崩溃, 见 CLAUDE.md):
- 陆地像素 ≥ SEA_LEVEL + 15 (海岸凹陷会让游戏判定异常)
- 海洋像素 ≤ SEA_LEVEL - 2, 近海有大陆架坡度 (顺带让预览的
  海岸浅滩有真实的深度渐变)

全 numpy/scipy 向量化, 零 Qt; 只读输入, 返回新数组。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import distance_transform_edt, gaussian_filter

from data.constants import TILE_LAND, SEA_LEVEL, OCEAN_HEIGHT
from domain.generators.base import GeneratorParams

# 陆地的安全底线 (海岸凹陷防线) 和最高峰
LAND_FLOOR = SEA_LEVEL + 15
SEA_CEILING = SEA_LEVEL - 2


@dataclass(frozen=True)
class HeightmapParams(GeneratorParams):
    """真实感高度图参数。"""
    mountain_coverage: float = 0.28   # 陆地中山区占比 (0~1)
    peak_height: int = 235            # 最高峰灰度 (上限 255)
    shelf_width: float = 60.0         # 大陆架宽度 (像素)


def _fbm(rng: np.random.Generator, shape: tuple[int, int],
         octaves: tuple[tuple[float, float], ...]) -> np.ndarray:
    """分形噪声: (sigma, 振幅) 八度叠加, 输出粗略 [-1, 1]。"""
    out = np.zeros(shape, dtype=np.float32)
    for sigma, amp in octaves:
        layer = gaussian_filter(
            rng.standard_normal(shape).astype(np.float32), sigma)
        layer /= max(float(np.abs(layer).max()), 1e-6)
        out += layer * amp
    return out / max(float(np.abs(out).max()), 1e-6)


def generate_realistic_heightmap(
    tile_map: np.ndarray,
    params: HeightmapParams | None = None,
) -> np.ndarray:
    """生成真实感高度图 (H, W) uint8。海陆轮廓完全遵从 tile_map。"""
    if params is None:
        params = HeightmapParams()
    h, w = tile_map.shape
    rng = np.random.default_rng(params.seed)
    land = tile_map == TILE_LAND

    # ── 1. 海岸距离场: 陆地向内升, 海底向外降 (大陆架) ──
    d_land = distance_transform_edt(land).astype(np.float32)
    d_sea = distance_transform_edt(~land).astype(np.float32)

    elev = np.empty((h, w), dtype=np.float32)
    # 陆地基面: 海岸处 LAND_FLOOR, 向内陆极缓爬升 (封顶 +8 —
    # 坡度太陡会在 uint8 量化后变成肉眼可见的"梯田"等高线)
    elev[:] = LAND_FLOOR + np.minimum(np.sqrt(d_land) * 0.45, 8.0)
    # 海底: 大陆架内缓坡, 之外落到深海
    shelf_t = np.clip(d_sea / max(params.shelf_width, 1.0), 0.0, 1.0)
    sea_depth = SEA_CEILING - 4.0 - shelf_t * (SEA_CEILING - 4.0 - OCEAN_HEIGHT)
    elev[~land] = sea_depth[~land]

    # ── 2. 山带场: 低频噪声挑出"成片山区" ──
    belt = _fbm(rng, (h, w), ((110.0, 1.0), (55.0, 0.5)))
    # 海岸附近不放山带 (山脉一般不贴着海岸线起步)
    coast_falloff = np.clip(d_land / 25.0, 0.0, 1.0)
    belt_land = belt[land] * coast_falloff[land]
    if belt_land.size:
        # 按目标占比取阈值, 平滑过渡进山区
        thresh = float(np.quantile(
            belt_land, 1.0 - np.clip(params.mountain_coverage, 0.02, 0.9)))
        belt_w = np.clip((belt * coast_falloff - thresh) / 0.18, 0.0, 1.0)
    else:
        belt_w = np.zeros((h, w), dtype=np.float32)

    # ── 3. 脊状分形: 1-|FBM| 天然形成连绵山脊链 ──
    ridge_base = _fbm(rng, (h, w),
                      ((48.0, 1.0), (24.0, 0.5), (12.0, 0.25)))
    ridged = 1.0 - np.abs(ridge_base)            # 山脊线 = 噪声零交叉处
    # 强锐化: 只有贴近脊线的像素才到山地高度, 山带内其余是山麓 →
    # 地形细化按海拔分类时, 岩石只描在脊上, 山链形状才出得来
    ridged = np.clip(ridged, 0.0, 1.0) ** 3.5

    peak_range = float(params.peak_height) - (LAND_FLOOR + 18.0)
    mountains = ridged * belt_w * max(peak_range, 0.0)

    # ── 4. 丘陵带: 山区边缘的中频过渡 ──
    hill_w = np.clip(belt_w * 2.0, 0.0, 1.0) - belt_w   # 山带边缘权重
    hills = (_fbm(rng, (h, w), ((20.0, 1.0), (10.0, 0.5))) * 0.5 + 0.5) \
        * hill_w * 28.0

    # ── 5. 平原微起伏 + 坡面侵蚀纹 ──
    plains = _fbm(rng, (h, w), ((30.0, 1.0), (9.0, 0.4))) * 2.0
    elev_land = elev + mountains + hills + plains

    gy, gx = np.gradient(elev_land)
    slope = np.sqrt(gx * gx + gy * gy)
    erosion = _fbm(rng, (h, w), ((4.0, 1.0),)) * np.clip(slope * 1.5, 0.0, 6.0)
    elev_land += erosion

    elev[land] = elev_land[land]

    # ── 6. 整体轻平滑后把约束拉回 (平滑会蚀掉海岸, 必须二次钳制) ──
    elev = gaussian_filter(elev, 1.2)
    # 抖动: ±0.6 白噪声打散 uint8 量化的整数阶梯, 否则缓坡上会出现
    # 肉眼可见的"梯田"等高线 (被光影放大)
    elev += rng.uniform(-0.6, 0.6, elev.shape).astype(np.float32)
    elev[land] = np.clip(elev[land], LAND_FLOOR, 255.0)
    elev[~land] = np.clip(elev[~land], 0.0, SEA_CEILING)

    return elev.astype(np.uint8)


# ── 标准生成器接口 ──

class RealisticHeightmapGenerator:
    """真实感高度图 — 路线 C 的第二个生成器。"""

    id = "realistic_heightmap"
    target_layer = "height_map"

    def default_params(self) -> HeightmapParams:
        return HeightmapParams()

    def generate(self, map_data, params: HeightmapParams,
                 mask: np.ndarray | None = None) -> np.ndarray:
        out = generate_realistic_heightmap(map_data.tile_map, params)
        if mask is not None:
            # 掩码外保持原高度 (保护导入/手工精修的区域)
            out = np.where(mask, out, map_data.height_map).astype(np.uint8)
        return out
