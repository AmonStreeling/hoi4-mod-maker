"""
自动气候色调 — 替代 P 社美术手工绘制的区域色调图。

vanilla 地图"好看"七成来自手绘的 colormap (撒哈拉金黄/欧洲翠绿/极地冷白)。
本模块按地理规则自动生成同样的色调层:

1. 纬度气候带: 赤道湿绿 → 副热带干黄 (哈德里环流下沉带) → 温带绿
   → 寒带冷灰 → 极地雪白
2. 海拔修正: 高山逐渐染成岩灰/雪白
3. 低频噪声: 打散纬度带的"等高线感", 让色块边缘自然

输出 (H, W, 3) uint8 色调图, 128 = 原色 (配合合成器 材质×色调×2 公式)。
全 numpy 向量化, 零 Qt。
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter

from data.constants import TILE_LAND, SEA_LEVEL

# 气候带关键点: |纬度| → 色调 RGB (128 为中性)
# 数值围绕 128 设计, 避免 ×2 公式下过曝/过暗
_LAT_KEYS = np.array([0, 12, 22, 33, 45, 58, 68, 78, 90], dtype=np.float32)
_LAT_R = np.array([108, 112, 138, 150, 122, 112, 124, 150, 165], dtype=np.float32)
_LAT_G = np.array([132, 134, 132, 138, 130, 124, 126, 152, 168], dtype=np.float32)
_LAT_B = np.array([ 96, 100,  98, 100, 104, 108, 122, 155, 175], dtype=np.float32)

# 海拔修正: 高于此高度开始向岩灰过渡, 到雪线变白
# (按原版实测标定: 山地 P50=+32, 见 tools/vanilla_terrain_stats.py)
_ROCK_START = SEA_LEVEL + 26.0
_SNOW_LINE = SEA_LEVEL + 60.0
_ROCK_RGB = np.array([130, 128, 126], dtype=np.float32)
_SNOW_RGB = np.array([175, 178, 185], dtype=np.float32)

# 低频噪声: 振幅 (色调单位) 和平滑半径 (像素)
_NOISE_AMP = 9.0
_NOISE_SIGMA = 48.0


def latitude_field(
    h: int,
    w: int,
    equator_y: float | None = None,
    seed: int = 0,
    amp: float = _NOISE_AMP,
    sigma: float = _NOISE_SIGMA,
) -> np.ndarray:
    """每像素"纬度" (H, W) float32, 0~90, 带低频噪声蜿蜒。

    地形细化和气候色调共用这张场, 保证森林带和色调带对得上。
    """
    eq = h / 2.0 if equator_y is None else float(equator_y)
    ys = np.arange(h, dtype=np.float32)
    lat = np.abs(ys - eq) / max(eq, h - eq) * 90.0          # (H,)

    rng = np.random.default_rng(seed)
    wobble = gaussian_filter(
        rng.standard_normal((h, w)).astype(np.float32), sigma)
    wobble *= amp / max(float(np.abs(wobble).max()), 1e-6)
    return np.clip(lat[:, None] + wobble, 0.0, 90.0)


def generate_climate_tint(
    tile_map: np.ndarray,
    height_map: np.ndarray,
    equator_y: float | None = None,
    seed: int = 0,
) -> np.ndarray:
    """按纬度/海拔自动生成色调图, 返回 (H, W, 3) uint8。

    参数:
        tile_map: 陆/海/湖分类 (H, W); 水体像素输出中性 128 (反正会被水色覆盖)
        height_map: 高度图 (H, W)
        equator_y: 赤道所在行, None = 地图垂直居中 (H/2)
        seed: 噪声种子, 同一种子结果可复现
    """
    h, w = tile_map.shape

    # ── 1. 纬度气候带 ──
    lat2d = latitude_field(h, w, equator_y, seed)           # (H, W)

    tint = np.empty((h, w, 3), dtype=np.float32)
    tint[:, :, 0] = np.interp(lat2d, _LAT_KEYS, _LAT_R)
    tint[:, :, 1] = np.interp(lat2d, _LAT_KEYS, _LAT_G)
    tint[:, :, 2] = np.interp(lat2d, _LAT_KEYS, _LAT_B)

    # ── 2. 海拔修正: 高山 → 岩灰 → 雪白 ──
    hf = height_map.astype(np.float32)
    rock_t = np.clip((hf - _ROCK_START) / (_SNOW_LINE - _ROCK_START), 0.0, 1.0)
    if np.any(rock_t > 0):
        # 先向岩灰过渡 (前半程), 再向雪白过渡 (后半程)
        half = np.clip(rock_t * 2.0, 0.0, 1.0)[:, :, None]
        peak = np.clip(rock_t * 2.0 - 1.0, 0.0, 1.0)[:, :, None]
        tint = tint * (1.0 - half) + _ROCK_RGB * half
        tint = tint * (1.0 - peak) + _SNOW_RGB * peak

    # ── 3. 水体置中性 ──
    tint[tile_map != TILE_LAND] = 128.0

    return np.clip(tint, 0, 255).astype(np.uint8)
