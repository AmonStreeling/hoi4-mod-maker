"""海面着色 — 按距陆地距离做浅→深渐变, 导出与预览共用同一公式.

效果: 近岸青绿, 80 像素内渐变到深蓝远海; 陆地/湖泊像素填深海色
     (与导出的 colormap_water 完全一致, 预览所见即游戏海面色源).
适用: export/writers/map/colormap_dds (打包成 BGRA DDS),
     domain/preview/compositor (预览海面直接取 RGB).
调用: water_color_rgb(tile_map) → (H, W, 3) float32 RGB [0,255]
"""
import numpy as np

from data.constants import TILE_SEA

# 浅海(近岸)青绿 → 深海深蓝
SHALLOW_RGB = np.array([130.0, 200.0, 180.0], dtype=np.float32)
DEEP_RGB = np.array([30.0, 70.0, 110.0], dtype=np.float32)
# 距陆地这么多像素达到纯深海色
DEEP_DISTANCE = 80.0


def water_color_rgb(tile_map: np.ndarray) -> np.ndarray:
    """tile_map (H, W) uint8 → 海面颜色 (H, W, 3) float32.

    海洋像素按距陆地距离渐变; 非海像素(陆地/湖泊)填深海色 —
    引擎不用陆地处的水色, 填一致避免 mip 边缘伪影。
    需要 scipy; 不可用时由调用方自行降级。
    """
    from scipy.ndimage import distance_transform_edt

    sea = (tile_map == TILE_SEA) | (tile_map == 0)
    dist_to_land = distance_transform_edt(sea).astype(np.float32)
    norm = np.clip(dist_to_land / DEEP_DISTANCE, 0.0, 1.0)
    rgb = SHALLOW_RGB + (DEEP_RGB - SHALLOW_RGB) * norm[..., None]
    rgb[~sea] = DEEP_RGB
    return rgb
