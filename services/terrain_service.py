"""
地形 / 高度自动生成服务.

从 tile_map (陆/海/湖) 自动生成 terrain_map 和 height_map.
smart_auto_terrain: 基于高度图 + Perlin 噪声的智能地形生成.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from data.constants import (
    MAP_WIDTH, MAP_HEIGHT,
    TILE_LAND, TILE_LAKE, TILE_SEA,
    OCEAN_HEIGHT, LAND_BASE_HEIGHT, SEA_LEVEL,
)
from data.terrain_types import (
    DEFAULT_TERRAIN_FOR_TILE, TERRAIN_PALETTE_INDEX,
    PAINTABLE_GROUPS,
)


def auto_terrain(tile_map: np.ndarray) -> np.ndarray:
    """按 tile_map 默认规则生成 terrain_map (旧版简单映射)."""
    terrain = np.zeros_like(tile_map, dtype=np.uint8)
    for tile_type, terrain_name in DEFAULT_TERRAIN_FOR_TILE.items():
        mask = tile_map == tile_type
        terrain[mask] = TERRAIN_PALETTE_INDEX[terrain_name]
    return terrain


# ── 智能地形生成 ─────────────────────────────────────────

@dataclass(frozen=True)
class TerrainGenConfig:
    """智能地形生成参数 — UI 暴露给用户调节。"""
    # 高度阈值 (对应 heightmap 0-255)
    plains_max: int = 115       # 低于此 → 平原/森林
    hills_min: int = 130        # 高于此 → 丘陵
    mountain_min: int = 165     # 高于此 → 山地
    snow_min: int = 210         # 高于此 → 雪山

    # 森林: 平原区域中一部分变森林
    forest_noise_threshold: float = 0.1   # 噪声 > 此值 → 森林 (越低森林越多)

    # 沙漠: 纬度带 + 低海拔
    desert_band_y_min: float = 0.20   # 纬度上界 (地图 y 比例)
    desert_band_y_max: float = 0.80   # 纬度下界
    desert_noise_threshold: float = 0.15  # 噪声 > 此值 → 沙漠

    # 丛林: 赤道附近的森林区
    jungle_band_y_min: float = 0.35
    jungle_band_y_max: float = 0.65
    jungle_probability: float = 0.5   # 赤道森林变丛林的概率

    # 噪声参数
    noise_scale: float = 80.0        # 边界扰动尺度
    noise_amplitude: float = 20.0    # 高度偏移量 (像素)
    scatter_scale: float = 12.0      # 散点尺度 (越小越碎)
    scatter_strength: float = 0.65   # 散点阈值 (越低越多斑点)

    # 阈值整体偏移 (用户控制"山脉多少")
    # -50 = 所有阈值抬高 50 → 更多平原/丘陵, 更少山地/雪山
    # 0 = 默认
    # +50 = 阈值降低 50 → 多山地雪山
    threshold_offset: int = 0

    # 种子
    seed: int = 42


def smart_auto_terrain(
    height_map: np.ndarray,
    tile_map: np.ndarray,
    config: TerrainGenConfig | None = None,
    mask: np.ndarray | None = None,
) -> np.ndarray:
    """基于高度图 + Perlin 噪声的智能地形生成。

    Parameters
    ----------
    height_map : uint8 高度图
    tile_map : uint8 地块类型图 (TILE_LAND/SEA/LAKE)
    config : 生成参数，None 时用默认值
    mask : bool 数组，只生成 mask==True 的区域 (局部重塑用)

    Returns
    -------
    terrain_map : uint8 地形索引图
    """
    from domain.noise import perlin_2d

    if config is None:
        config = TerrainGenConfig()

    h, w = height_map.shape
    terrain = np.full((h, w), 15, dtype=np.uint8)  # 默认海洋

    # 1. 生成噪声层 (降采样加速)
    ds = 4 if h > 1024 else 1
    boundary_noise = perlin_2d((h, w), scale=config.noise_scale,
                               octaves=4, seed=config.seed, downsample=ds)
    forest_noise = perlin_2d((h, w), scale=config.noise_scale * 0.7,
                             octaves=3, seed=config.seed + 100, downsample=ds)
    desert_noise = perlin_2d((h, w), scale=config.noise_scale * 0.6,
                             octaves=3, seed=config.seed + 200, downsample=ds)
    scatter_noise = perlin_2d((h, w), scale=config.scatter_scale,
                              octaves=2, seed=config.seed + 300, downsample=ds)
    variant_noise = perlin_2d((h, w), scale=config.scatter_scale * 2,
                              octaves=2, seed=config.seed + 400, downsample=ds)

    # 2. 扰动高度 (Perlin 偏移让边界有机化)
    perturbed = height_map.astype(np.float32) + boundary_noise * config.noise_amplitude

    # 3. 基础分层
    # 关键：land = tile_map==LAND 且 heightmap≥SEA_LEVEL（双重判定，避免延伸到海）
    # HOI4 游戏内看 heightmap 判海陆，如果 tile_map 和 heightmap 不一致
    # （例如 tile_map=LAND 但 heightmap<95），会导致地形渲染跑到海里
    land = (tile_map == TILE_LAND) & (height_map >= SEA_LEVEL)
    lake = tile_map == TILE_LAKE
    # sea = 显式海洋 或 "陆地但高度<海平面"的不一致像素
    sea = (tile_map == TILE_SEA) | ((tile_map == TILE_LAND) & (height_map < SEA_LEVEL))

    # 阈值整体偏移 (用户"山脉多少"滑块)
    # offset > 0 → 阈值下调 → 更多山; offset < 0 → 阈值上调 → 更少山
    off = int(config.threshold_offset)
    plains_max_eff = config.plains_max - off
    mountain_min_eff = config.mountain_min - off
    snow_min_eff = config.snow_min - off

    # 纬度参数
    y_ratio = np.linspace(0, 1, h, dtype=np.float32)[:, None]  # (h, 1)

    # 平原层
    is_low = perturbed < plains_max_eff
    plains_mask = land & is_low

    # 森林: 平原中噪声较高的区域
    is_forest = plains_mask & (forest_noise > config.forest_noise_threshold)
    is_plains = plains_mask & ~is_forest

    # 丛林: 赤道附近的森林
    in_jungle_band = (y_ratio >= config.jungle_band_y_min) & (y_ratio <= config.jungle_band_y_max)
    jungle_prob_mask = (variant_noise + 1) / 2 < config.jungle_probability  # 归一化到[0,1]
    is_jungle = is_forest & in_jungle_band & jungle_prob_mask
    is_forest = is_forest & ~is_jungle

    # 沙漠: 非赤道、低海拔、噪声匹配
    in_desert_band = (y_ratio < config.desert_band_y_min) | (y_ratio > config.desert_band_y_max)
    is_desert = is_plains & in_desert_band & (desert_noise > config.desert_noise_threshold)
    is_plains = is_plains & ~is_desert

    # 丘陵层
    is_mid = (perturbed >= plains_max_eff) & (perturbed < mountain_min_eff)
    is_hills = land & is_mid

    # 山地层
    is_high = (perturbed >= mountain_min_eff) & (perturbed < snow_min_eff)
    is_mountain = land & is_high

    # 雪山层
    is_snow = land & (perturbed >= snow_min_eff)

    # 沼泽: 低海拔 + 特定噪声区域 (少量点缀)
    is_marsh = is_plains & (scatter_noise > 0.7) & (perturbed < plains_max_eff - 10)
    is_plains = is_plains & ~is_marsh

    # 4. 分配基础 palette index
    terrain[is_plains] = 0     # plains terrain_0
    terrain[is_forest] = 1     # forest terrain_1
    terrain[is_jungle] = 21    # jungle_18
    terrain[is_desert] = 3     # desert
    terrain[is_hills] = 17     # hills_blend
    terrain[is_mountain] = 6   # mountain terrain_6
    terrain[is_snow] = 16      # snow_16
    terrain[is_marsh] = 9      # marsh terrain_9
    terrain[lake] = 14         # lakes
    terrain[sea] = 15          # ocean

    # 5. 图形变体散布 (制造斑点效果)
    _apply_variants(terrain, scatter_noise, variant_noise, config, land)

    # 6. 海/湖保护 (最后一步，确保绝对不被覆盖)
    terrain[sea] = 15
    terrain[lake] = 14

    # 7. 如果有 mask，只返回 mask 区域
    if mask is not None:
        return terrain, mask

    return terrain


def _apply_variants(
    terrain: np.ndarray,
    scatter: np.ndarray,
    variant: np.ndarray,
    config: TerrainGenConfig,
    land: np.ndarray,
) -> None:
    """在大区域内撒不同图形变体的散点，制造自然斑点效果。"""
    threshold = config.scatter_strength

    # 森林区域撒森林变体 (index 4)
    forest_mask = (terrain == 1) & (scatter > threshold)
    terrain[forest_mask] = 4  # terrain_4 (森林变体)

    # 平原区域撒平原变体 (index 5)
    plains_mask = (terrain == 0) & (scatter < -threshold)
    terrain[plains_mask] = 5  # terrain_5 (平原变体)

    # 山地区域撒变体
    mt_mask = terrain == 6
    # 用 variant_noise 分配不同山地变体
    terrain[mt_mask & (variant > 0.3)] = 10   # terrain_10
    terrain[mt_mask & (variant > 0.5)] = 20   # mountain_variation_grass
    terrain[mt_mask & (variant < -0.3)] = 11  # desert_mountain_11

    # 沙漠区域撒变体
    desert_mask = terrain == 3
    terrain[desert_mask & (scatter > threshold)] = 7    # terrain_7
    terrain[desert_mask & (scatter < -threshold)] = 12  # desert_12
    terrain[desert_mask & (variant > 0.4)] = 8          # desert_hills

    # 丘陵区域部分变沙漠丘陵
    hills_mask = terrain == 17
    terrain[hills_mask & (variant < -0.5)] = 2   # desert_mountain (hills variant)

    # 丛林区域撒变体
    jungle_mask = terrain == 21
    terrain[jungle_mask & (scatter > threshold)] = 22  # jungle_blend

    # 雪山区域部分变草地山
    snow_edge = (terrain == 16) & (variant > 0.3) & (scatter < 0)
    terrain[snow_edge] = 19  # plains_snow


@dataclass(frozen=True)
class HeightGenConfig:
    """高度图生成参数。"""
    # 基础高度（参考原版: 海岸~97, 内陆平原~120, 山脉200+）
    coast_height: int = 97      # 海岸线基础高度 (刚过海平面95)
    inland_max: int = 220       # 内陆最高基础值（加上噪声 ±40 可达 260，让高山区能到 snow_min=210 成雪山）
    # 距离场
    distance_power: float = 0.35 # 距海岸距离的幂次
    distance_scale: float = 250.0 # 距离归一化尺度 (像素)
    # 噪声 — 制造山脉和谷地
    noise_scale: float = 200.0   # 大尺度噪声 (山脉走向)
    noise_amplitude: float = 200.0 # 噪声最大高度偏移 (实际约±100)
    detail_scale: float = 50.0   # 小尺度噪声 (地形细节)
    detail_amplitude: float = 35.0
    # 平滑
    smooth_sigma: float = 3.0    # 最终高斯平滑 (小值保留山峰)
    # 种子
    seed: int = 42


def smart_auto_height(
    tile_map: np.ndarray,
    config: HeightGenConfig | None = None,
) -> np.ndarray:
    """智能高度图生成: 双向距离场（海陆都渐变）+ Perlin 噪声山脉 + 平滑。

    旧版本 bug：
        1. 海洋统一设成 OCEAN_HEIGHT=40 → 海岸像悬崖
        2. 陆地用 power(dist, 0.35) 海岸瞬间升高 → 陆地侧也是悬崖
    新版本：
        - 海洋也用距离场：浅海 94 → 深海 70（渐深）
        - 陆地用线性距离：海岸 97 → 内陆 180（缓升）
        - 噪声只加在远离海岸的内陆，不破坏沙滩区
    """
    from scipy.ndimage import gaussian_filter, distance_transform_edt
    from domain.noise import perlin_2d

    if config is None:
        config = HeightGenConfig()

    h, w = tile_map.shape
    land = tile_map == TILE_LAND
    lake = tile_map == TILE_LAKE
    sea = (tile_map == TILE_SEA) | (tile_map == 0)

    # 1. 双向距离场
    dist_to_sea = distance_transform_edt(~sea).astype(np.float32)   # 陆地像素到海的距离
    dist_to_land = distance_transform_edt(~land).astype(np.float32)  # 海洋像素到陆的距离

    hm = np.full((h, w), float(SEA_LEVEL), dtype=np.float32)

    # 2. 陆地基础高度：线性（不用幂次，避免海岸悬崖）
    #    海岸 97 → 内陆 180（约 250 像素深处达到峰值）
    max_dist = max(config.distance_scale, 1.0)
    land_height_factor = np.clip(dist_to_sea / max_dist, 0, 1)
    hm[land] = config.coast_height + land_height_factor[land] * (config.inland_max - config.coast_height)

    # 3. 海洋基础高度：浅海 94 → 深海 70（系数 0.8/像素，封顶 -25）
    hm[sea] = SEA_LEVEL - np.clip(dist_to_land[sea] * 0.8, 1, 25)

    # 4. Perlin 噪声叠加 — 只加在远离海岸的内陆（保护沙滩区）
    ds = 4 if h > 1024 else 1
    mountain_noise = perlin_2d((h, w), scale=config.noise_scale,
                               octaves=4, seed=config.seed, downsample=ds)
    detail_noise = perlin_2d((h, w), scale=config.detail_scale,
                             octaves=3, seed=config.seed + 500, downsample=ds)
    # 第三层：高山集群（密集尖锐，只有阈值以上部分起作用，模拟真实山脉链）
    peaks_noise = perlin_2d((h, w), scale=80.0,
                            octaves=5, seed=config.seed + 777, downsample=ds)

    # 噪声权重：海岸 0% → 内陆 5 像素后 100%（保护海岸渐变）
    noise_weight = np.clip((dist_to_sea - 5) / 10.0, 0, 1).astype(np.float32)
    hm[land] += (mountain_noise[land] * config.noise_amplitude
                 + detail_noise[land] * config.detail_amplitude) * noise_weight[land]

    # 山峰集群：只有 peaks_noise > 0.3 的地方才加高山（大概 30% 的内陆区域形成山脉链）
    peak_threshold = 0.3
    peak_strength = 120.0  # 阈值以上每 +0.1 → +12 高度，最多加 84（0.7→84）
    peak_bonus = np.maximum(peaks_noise - peak_threshold, 0) * peak_strength
    # 只在远离海岸（≥20像素）的地方生效，让山脉远离海
    peak_mask = land & (dist_to_sea >= 20)
    hm[peak_mask] += peak_bonus[peak_mask]

    # 5. 轻微平滑（不削山峰）
    hm = gaussian_filter(hm, sigma=2.0)

    # 6. 强制约束（守底线，保证 HOI4 海陆判定正确）
    hm[lake] = SEA_LEVEL - 5
    hm[land] = np.maximum(hm[land], SEA_LEVEL + 1)  # 陆地至少 96
    hm[sea] = np.minimum(hm[sea], SEA_LEVEL - 1)    # 海至少 94

    # HOI4 要求顶底行高度接近海平面
    hm[0, :] = np.minimum(hm[0, :], SEA_LEVEL)
    hm[-1, :] = np.minimum(hm[-1, :], SEA_LEVEL)

    return np.clip(hm, 30, 255).astype(np.uint8)


def apply_mountain_ridge(
    height_map: np.ndarray,
    tile_map: np.ndarray,
    points: list[tuple[int, int]],
    peak_height: int = 220,
    falloff_distance: float = 80.0,
    ridge_width: float = 5.0,
) -> np.ndarray:
    """在高度图上沿给定点序列画山脉。

    算法（2026-06 升级为真实山链, 不再是均匀"土堆"）：
    1. 沿 points 连线生成山脊线像素 → 距离场
    2. 山脊剖面: 距离衰减 (指数略锐化, 山脊有棱)
    3. 沿脊起伏: 脊状分形噪声让一条线上长出主峰与垭口
    4. 山麓质感: 分形细节随山体权重衰减, 平地不受污染
    5. 与原高度取 max（叠加而非覆盖）+ 量化抖动防梯田纹

    种子由画线坐标决定: 同一条线反复调滑条, 山形保持稳定。

    参数:
        height_map: (H, W) uint8, 现有高度图
        tile_map: (H, W) uint8, 地块类型
        points: [(y, x), ...] 山脊线经过的点序列
        peak_height: 山峰高度 (0-255)
        falloff_distance: 衰减距离（像素）
        ridge_width: 山脊宽度（像素）
    """
    from scipy.ndimage import distance_transform_edt
    from domain.generators.heightmap import _fbm

    if len(points) < 2:
        return height_map

    h, w = height_map.shape
    result = height_map.copy().astype(np.float32)
    land = tile_map == TILE_LAND

    # 1. 在二值图上画山脊线（沿 points 连线）
    ridge_mask = np.zeros((h, w), dtype=bool)
    for i in range(len(points) - 1):
        y0, x0 = points[i]
        y1, x1 = points[i + 1]
        _draw_line(ridge_mask, y0, x0, y1, x1, int(ridge_width))

    # 2. 到山脊线的距离 → 山体权重 (0~1, 略锐化让脊有棱)
    dist = distance_transform_edt(~ridge_mask).astype(np.float32)
    body = np.exp(-(dist / max(falloff_distance, 1.0)) ** 1.25)

    # 3. 沿脊起伏: 同一条线种子固定, 调滑条时山形不跳变
    seed = hash(tuple(map(tuple, points))) & 0xFFFF
    rng = np.random.default_rng(seed)
    ridged = 1.0 - np.abs(_fbm(rng, (h, w), ((36.0, 1.0), (18.0, 0.5))))
    profile = 0.55 + 0.45 * np.clip(ridged, 0.0, 1.0) ** 2  # 垭口0.55~主峰1.0

    # 4. 山麓分形质感 (随山体权重衰减)
    detail = _fbm(rng, (h, w), ((9.0, 1.0), (4.0, 0.5))) * 10.0 * body

    ridge_height = peak_height * body * profile + detail
    # 量化抖动: 防止缓坡出现整数阶梯"梯田纹"
    ridge_height += rng.uniform(-0.6, 0.6, ridge_height.shape).astype(np.float32)

    # 5. 只叠加到陆地，取 max
    result[land] = np.maximum(result[land], ridge_height[land])

    # 强制约束
    result[~land] = height_map[~land]  # 非陆地不变
    result[land] = np.maximum(result[land], SEA_LEVEL + 1)

    return np.clip(result, 0, 255).astype(np.uint8)


def _draw_line(mask: np.ndarray, y0: int, x0: int, y1: int, x1: int, width: int) -> None:
    """Bresenham 直线 + 宽度扩展。"""
    h, w = mask.shape
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    r = width // 2

    while True:
        # 画圆形笔触
        for dy2 in range(-r, r + 1):
            for dx2 in range(-r, r + 1):
                if dy2 * dy2 + dx2 * dx2 <= r * r:
                    ny, nx = y0 + dy2, x0 + dx2
                    if 0 <= ny < h and 0 <= nx < w:
                        mask[ny, nx] = True

        if y0 == y1 and x0 == x1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x0 += sx
        if e2 < dx:
            err += dx
            y0 += sy


def auto_height(tile_map: np.ndarray) -> np.ndarray:
    """从 tile_map 自动生成高度图 (调用智能版本)."""
    return smart_auto_height(tile_map)


# 每种 terrain 的高度参数:
#   base = 该地形的最低高度 (区域边缘)
#   peak = 该地形的最高高度 (区域中心, 距边界 spread 像素时达到)
#   spread = 从 base 到 peak 需要的距离 (像素), 决定"区域多大才能形成峰"
# 设计:
#   - mountain peak=240 接近 255 上限, 大山块中心达山尖, 小块只到中段
#   - hills 起伏 120-170
#   - plains/forest 基本平地, peak 略高
_HEIGHT_BY_TERRAIN: dict[str, dict[str, int]] = {
    # ocean: base 是"海岸浅海" (高), peak 是"远海深渊" (低) — 距陆距离决定深度
    # spread 100px → 距陆 100px 后达到最深, 大洋中央会非常深, 海岸附近浅一些有过渡
    "ocean":    {"base": 92,  "peak": 35,  "spread": 100},
    "lakes":    {"base": 92,  "peak": 87,  "spread": 5},
    "plains":   {"base": 96,  "peak": 120, "spread": 30},
    "desert":   {"base": 100, "peak": 125, "spread": 25},
    "forest":   {"base": 105, "peak": 140, "spread": 20},
    "jungle":   {"base": 105, "peak": 140, "spread": 20},
    "marsh":    {"base": 95,  "peak": 105, "spread": 10},
    "urban":    {"base": 100, "peak": 115, "spread": 10},
    "hills":    {"base": 135, "peak": 185, "spread": 18},  # 提高 + 缩短 spread, 小山丘也明显
    "mountain": {"base": 155, "peak": 245, "spread": 30},  # base 155 (单像素也是真山地), peak 245 接近极限
}


def _terrain_array_from_provincial(
    provincial_terrain: dict[int, str],
    province_map: np.ndarray,
    tile_map: np.ndarray | None = None,
) -> np.ndarray:
    """把省份级属性 (provincial_terrain dict) 合成为像素级 terrain 数组.

    没设 provincial_terrain 的省份按 tile_map 默认: sea→ocean, lake→lakes, land→plains.
    """
    max_pid = int(province_map.max())
    plains_idx = TERRAIN_PALETTE_INDEX.get("plains", 0)
    ocean_idx = TERRAIN_PALETTE_INDEX.get("ocean", 15)
    lakes_idx = TERRAIN_PALETTE_INDEX.get("lakes", 14)

    # 按 tile_map 算每个 pid 的默认 terrain (多数决: 该 pid 大部分像素是 sea? land? lake?)
    lut = np.full(max_pid + 1, plains_idx, dtype=np.uint8)
    if tile_map is not None:
        flat_pm = province_map.ravel()
        flat_tm = tile_map.ravel()
        n = max_pid + 1
        sea_count = np.bincount(flat_pm, weights=(flat_tm == TILE_SEA), minlength=n)
        lake_count = np.bincount(flat_pm, weights=(flat_tm == TILE_LAKE), minlength=n)
        total_count = np.bincount(flat_pm, minlength=n)
        # 多数 sea → ocean; 多数 lake → lakes; 否则 plains
        is_sea = sea_count * 2 > total_count
        is_lake = lake_count * 2 > total_count
        lut[is_sea] = ocean_idx
        lut[is_lake] = lakes_idx

    # 用户的 provincial_terrain 优先级最高, 覆盖默认
    for pid, name in provincial_terrain.items():
        try:
            pid_int = int(pid)
        except (TypeError, ValueError):
            continue
        if 0 < pid_int <= max_pid and name in TERRAIN_PALETTE_INDEX:
            lut[pid_int] = TERRAIN_PALETTE_INDEX[name]
    return lut[province_map]


def auto_height_from_terrain(
    terrain_map: np.ndarray,
    tile_map: np.ndarray,
    provincial_terrain: dict[int, str] | None = None,
    province_map: np.ndarray | None = None,
    smooth_sigma: float = 4.0,
) -> np.ndarray:
    """从 terrain 反推 height_map (用距离场把每种地形撑满高度区间).

    数据源优先级:
      1. provincial_terrain (省份级属性, 用户真正的意图) — 优先, HOI4 实际用这个判定
      2. terrain_map (像素级装饰) — 回退, 仅当未提供 provincial_terrain 时

    算法: 对每种 terrain 算"距离该地形区域**边界**的距离" (distance_transform_edt).
        距离 = 0 (区域边缘) → base 高度
        距离 ≥ spread (区域内深处) → peak 高度
    → 大山块中心 240 (山尖), 小山丘只到中段, plains 基本平 + 微起伏.

    高度范围用足 60-240, smooth_sigma 控制平滑度.
    """
    from scipy.ndimage import gaussian_filter, distance_transform_edt

    # 选数据源
    if provincial_terrain and province_map is not None and provincial_terrain:
        terrain_arr = _terrain_array_from_provincial(
            provincial_terrain, province_map, tile_map=tile_map
        )
    else:
        terrain_arr = terrain_map

    h, w = terrain_arr.shape
    hm = np.full((h, w), float(SEA_LEVEL), dtype=np.float32)

    # 1. 每种 terrain: distance field → 高度
    for name, params in _HEIGHT_BY_TERRAIN.items():
        if name not in TERRAIN_PALETTE_INDEX:
            continue
        idx = TERRAIN_PALETTE_INDEX[name]
        mask = terrain_arr == idx
        if not mask.any():
            continue
        # 该地形像素到该地形区域边界的距离 (距离非该地形像素的最近距离)
        dist = distance_transform_edt(mask).astype(np.float32)
        spread = max(params["spread"], 1)
        # norm: 0 (边缘) → 1 (深处, 距离 ≥ spread)
        norm = np.minimum(dist / spread, 1.0)
        base = float(params["base"])
        peak = float(params["peak"])
        hm[mask] = base + norm[mask] * (peak - base)

    # 2. 高斯平滑 (消除地形边界陡变, sigma 小一点保留山尖)
    hm = gaussian_filter(hm, sigma=smooth_sigma)

    # 3. 强制 land/sea/lake 约束
    land = tile_map == TILE_LAND
    sea = (tile_map == TILE_SEA) | (tile_map == 0)
    lake = tile_map == TILE_LAKE
    hm[land] = np.maximum(hm[land], SEA_LEVEL + 1)
    hm[sea] = np.minimum(hm[sea], SEA_LEVEL - 1)
    hm[lake] = SEA_LEVEL - 5

    # HOI4 顶底行边界
    hm[0, :] = np.minimum(hm[0, :], SEA_LEVEL)
    hm[-1, :] = np.minimum(hm[-1, :], SEA_LEVEL)

    return np.clip(hm, 30, 255).astype(np.uint8)


def smooth_height(
    height_map: np.ndarray,
    tile_map: np.ndarray | None = None,
    sigma: float = 4.0,
) -> np.ndarray:
    """高斯平滑 heightmap — 只处理陆地像素，海/湖保持原值。

    实现方式：对 land_mask*height 做高斯模糊，再除以 land_mask 的高斯模糊，
    得到仅用陆地像素计算出的加权平均（避免海面 0 值拖低海岸高度）。
    """
    from scipy.ndimage import gaussian_filter
    from data.constants import TILE_LAND

    if tile_map is None:
        hm = height_map.astype(np.float32)
        return np.clip(gaussian_filter(hm, sigma=sigma), 0, 255).astype(np.uint8)

    land_mask = (tile_map == TILE_LAND).astype(np.float32)
    hm_land = height_map.astype(np.float32) * land_mask
    blurred = gaussian_filter(hm_land, sigma=sigma)
    weight = gaussian_filter(land_mask, sigma=sigma)
    out = height_map.astype(np.float32).copy()
    valid = (tile_map == TILE_LAND) & (weight > 1e-6)
    out[valid] = blurred[valid] / weight[valid]
    return np.clip(out, 0, 255).astype(np.uint8)


def compute_provincial_terrain_from_bmp(
    terrain_map: np.ndarray,
    province_map: np.ndarray,
    tile_map: np.ndarray,
) -> dict[int, str]:
    """从 terrain.bmp 按 per-province 多数地形推断 provincial_terrain dict。

    用于：自动生成地形后，让 dict 属性层跟着更新（单向同步：视觉 → 属性）。

    算法：
    1. 找出"真正的陆地 province"：该 province 的 LAND 像素数 > SEA+LAKE 像素数
    2. 对这些陆地 province，统计 terrain_map 多数地形 → 写入 dict
    3. 海洋/湖泊 province 绝对不写入 dict（避免误把海洋改成陆地属性）
    """
    from data.terrain_types import PALETTE_TO_TYPE

    flat_pid = province_map.ravel()
    flat_tile = tile_map.ravel()
    flat_ter = terrain_map.ravel()

    max_pid = int(province_map.max())
    if max_pid <= 0:
        return {}

    # Step 1: 统计每个 province 的 LAND / SEA+LAKE 像素数
    land_pixel_mask = flat_tile == TILE_LAND
    non_land_pixel_mask = (flat_tile == TILE_SEA) | (flat_tile == TILE_LAKE)

    land_counts = np.bincount(
        flat_pid[land_pixel_mask], minlength=max_pid + 1
    )
    non_land_counts = np.bincount(
        flat_pid[non_land_pixel_mask], minlength=max_pid + 1
    )

    # 真正的陆地 province：LAND 像素严格多于海/湖像素
    is_land_province = land_counts > non_land_counts
    is_land_province[0] = False  # province 0 永远不算
    land_pids = set(np.where(is_land_province)[0].tolist())

    if not land_pids:
        return {}

    # Step 2: 只对 land province 统计 terrain_map 多数地形
    # 过滤：只看 land province 的 LAND 像素（不看边界上的 SEA 像素）
    valid_mask = land_pixel_mask & np.isin(flat_pid, list(land_pids))
    valid_pid = flat_pid[valid_mask].astype(np.int64)
    valid_ter = flat_ter[valid_mask].astype(np.int64)

    if len(valid_pid) == 0:
        return {}

    keys = valid_pid * 256 + valid_ter
    unique, counts = np.unique(keys, return_counts=True)

    best: dict[int, tuple[int, int]] = {}
    for k, c in zip(unique, counts):
        pid = int(k // 256)
        terr = int(k % 256)
        cnt = int(c)
        if pid not in best or cnt > best[pid][0]:
            best[pid] = (cnt, terr)

    # Step 3: 转换成 provincial type name
    result: dict[int, str] = {}
    for pid, (_, terr_idx) in best.items():
        ptype = PALETTE_TO_TYPE.get(terr_idx)
        # 海洋/湖泊地形不记入（双重保护，即使像素里混了 ocean 索引也跳过）
        if ptype and ptype not in ("ocean", "lakes"):
            result[pid] = ptype

    return result


# ── 局部精修高度图 ──────────────────────────────────────────

FEATHER_RADIUS = 20  # 边界羽化像素宽度


def refine_heightmap_region(
    height_map: np.ndarray,
    mask: np.ndarray,
    tile_map: np.ndarray,
    strength: float = 0.5,
    enable_ridge: bool = True,
    enable_erosion: bool = True,
    enable_noise: bool = False,
    enable_shrink: bool = False,
    shrink_distance: float = 25.0,
    seed: int = 42,
) -> np.ndarray:
    """局部精修高度图。

    以用户画的 height_map 为基础，在 mask 选区内叠加山脊/侵蚀/噪声/收缩。
    保留用户意图（哪高哪低不变），只在其上加装饰；或把画大了的山脉收紧。
    边界 FEATHER_RADIUS 像素羽化，避免硬边。

    所有计算仅在 mask bbox 内进行（+padding），支持 5632×2048 大图小选区不卡。

    参数:
        height_map: (H, W) uint8, 原高度图
        mask: (H, W) bool, 选区
        tile_map: (H, W) uint8, 陆/海/湖判定（只处理陆地）
        strength: 0..1, 精修强度
        enable_ridge: 山脊尖锐化
        enable_erosion: 侵蚀沟壑
        enable_noise: 高度相关噪声
        enable_shrink: 收缩山脉形状（把画大了的山脉边缘拉低）
        shrink_distance: 收缩影响距离（像素），越大收缩越狠
        seed: 随机种子

    返回:
        (H, W) uint8 新高度图。非 mask 区域 === 输入原图。
    """
    from scipy.ndimage import distance_transform_edt, gaussian_filter, maximum_filter

    result = height_map.copy()
    if strength <= 0 or not (
        enable_ridge or enable_erosion or enable_noise or enable_shrink
    ):
        return result

    strength = float(np.clip(strength, 0.0, 1.0))
    land_mask = tile_map == TILE_LAND
    work_mask_full = mask & land_mask
    if not np.any(work_mask_full):
        return result

    # —— 只在 mask 的 bbox 内计算（带 padding 给羽化+邻域算子）——
    ys, xs = np.where(mask)
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    H, W = height_map.shape
    pad = FEATHER_RADIUS + 6  # 留羽化距离 + 邻域算子 footprint
    y0 = max(0, y0 - pad); y1 = min(H, y1 + pad)
    x0 = max(0, x0 - pad); x1 = min(W, x1 + pad)

    mask_sub = mask[y0:y1, x0:x1]
    land_sub = land_mask[y0:y1, x0:x1]
    work_sub = work_mask_full[y0:y1, x0:x1]
    hm_sub = result[y0:y1, x0:x1].astype(np.float32)

    # 1) 羽化权重
    dist_in = distance_transform_edt(mask_sub).astype(np.float32)
    feather = np.minimum(dist_in / FEATHER_RADIUS, 1.0)
    w = feather * strength

    # 2) 山脊尖锐化
    if enable_ridge:
        local_max = maximum_filter(hm_sub, size=5)
        ridge_pix = (hm_sub == local_max) & (hm_sub > SEA_LEVEL + 20) & land_sub
        ridge_boost = gaussian_filter(
            ridge_pix.astype(np.float32) * 15.0, sigma=2.0
        )
        hm_sub = hm_sub + ridge_boost * w

    # 3) 侵蚀沟壑
    if enable_erosion:
        erosion = _simulate_erosion(hm_sub, work_sub, seed=seed, iterations=30)
        hm_sub = hm_sub - erosion * w * 10.0

    # 4) 高度相关噪声
    if enable_noise:
        rng = np.random.default_rng(seed)
        noise = rng.standard_normal(hm_sub.shape).astype(np.float32) * 4.0
        noise = gaussian_filter(noise, sigma=1.5)
        height_factor = np.clip((hm_sub - SEA_LEVEL) / 100.0, 0.0, 1.0)
        hm_sub = hm_sub + noise * height_factor * w

    # 5) 收缩山脉形状（把画大了的山脉边缘拉向海平面）
    if enable_shrink:
        # 找"高地"：> SEA_LEVEL+30 且 land
        high_mask = (hm_sub > SEA_LEVEL + 30) & land_sub
        # 对"非高地"做 distance transform → 每个高地像素到最近低地的距离
        # 距离近的被拉低（边缘），距离远的（深山中心）不动
        if np.any(high_mask) and np.any(~high_mask):
            dist_from_low = distance_transform_edt(high_mask).astype(np.float32)
            pull = np.clip(1.0 - dist_from_low / max(shrink_distance, 1.0), 0.0, 1.0)
            # 仅作用在高地像素
            pull_effective = pull * high_mask.astype(np.float32) * w
            # 把高度拉向 SEA_LEVEL + 1
            hm_sub = hm_sub - (hm_sub - (SEA_LEVEL + 1)) * pull_effective

    # 6) 守底线（陆地不能 < SEA_LEVEL+1，避免陆变海）
    clipped = np.clip(hm_sub, SEA_LEVEL + 1, 255)
    sub_result = result[y0:y1, x0:x1]
    sub_result[work_sub] = clipped[work_sub].astype(np.uint8)
    result[y0:y1, x0:x1] = sub_result
    return result


def _simulate_erosion(
    hm: np.ndarray,
    work_mask: np.ndarray,
    seed: int,
    iterations: int = 30,
) -> np.ndarray:
    """极简水力侵蚀：从随机起点沿最陡下坡走 N 步，沿路累积侵蚀量。

    返回 (H, W) float32 侵蚀图，调用方乘以权重后从 hm 减去。
    只在 work_mask 内产生侵蚀。
    """
    h, w = hm.shape
    erosion = np.zeros_like(hm, dtype=np.float32)

    # 起点数量：选区面积 × 0.005（经验值，够出效果又不爆炸）
    area = int(work_mask.sum())
    n_starts = max(20, min(area // 200, 5000))

    rng = np.random.default_rng(seed)
    ys_all, xs_all = np.where(work_mask)
    if len(ys_all) == 0:
        return erosion
    idx = rng.integers(0, len(ys_all), size=n_starts)
    start_ys = ys_all[idx]
    start_xs = xs_all[idx]

    # 3x3 邻居偏移
    neighbors = [
        (-1, -1), (-1, 0), (-1, 1),
        (0, -1),           (0, 1),
        (1, -1),  (1, 0),  (1, 1),
    ]

    for sy, sx in zip(start_ys, start_xs):
        y, x = int(sy), int(sx)
        for _ in range(iterations):
            if not (0 <= y < h and 0 <= x < w):
                break
            if not work_mask[y, x]:
                break
            # 找最低邻居
            cur = hm[y, x]
            best_dy, best_dx = 0, 0
            best_h = cur
            for dy, dx in neighbors:
                ny, nx = y + dy, x + dx
                if not (0 <= ny < h and 0 <= nx < w):
                    continue
                if hm[ny, nx] < best_h:
                    best_h = hm[ny, nx]
                    best_dy, best_dx = dy, dx
            if best_dy == 0 and best_dx == 0:
                break  # 局部最低，停
            erosion[y, x] += 0.1
            y += best_dy
            x += best_dx
            erosion[y, x] += 0.3

    # 稍微平滑，避免单像素沟壑
    from scipy.ndimage import gaussian_filter
    erosion = gaussian_filter(erosion, sigma=0.8)
    return erosion
