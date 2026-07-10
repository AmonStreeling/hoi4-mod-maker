"""夜景层 — 模拟游戏夜晚: 整图压暗 + urban 地形处城市灯光.

效果: 底图乘冷色系数变成夜色, 画了 urban(城市)地形的像素点亮
     暖黄灯 + 高斯光晕 — 灯光位置与导出的 colormap alpha 城市
     灯光 mask 同源 (都来自 urban 地形), 预览所见即游戏夜面.
适用: 预览模式"夜景"开关. 纯 numpy+scipy, 零 Qt.
调用: apply_night_layer(rgb, terrain_map) → 新 (H, W, 3) uint8
"""
import numpy as np

# 夜色: 每通道乘法系数 (偏蓝的月光)
NIGHT_FACTOR = np.array([0.22, 0.26, 0.42], dtype=np.float32)
# 城市灯光: 暖黄
LIGHT_RGB = np.array([255.0, 214.0, 130.0], dtype=np.float32)
LIGHT_HALO_SIGMA = 3.0
LIGHT_STRENGTH = 0.9


def apply_night_layer(rgb: np.ndarray, terrain_map: np.ndarray | None) -> np.ndarray:
    """底图 (H, W, 3) uint8 + 地形图 → 夜景 (H, W, 3) uint8.

    terrain_map 为 None 或没有 urban 像素时只压暗, 不点灯。
    """
    night = rgb.astype(np.float32) * NIGHT_FACTOR

    if terrain_map is not None and terrain_map.shape == rgb.shape[:2]:
        from data.terrain_types import PALETTE_TO_TYPE
        urban_indices = [i for i, t in PALETTE_TO_TYPE.items() if t == "urban"]
        if urban_indices:
            mask = np.isin(terrain_map, urban_indices).astype(np.float32)
            if mask.any():
                try:
                    from scipy.ndimage import gaussian_filter
                    # 城市本体全亮, 光晕取模糊结果 (×2 补模糊损失), 不超过 1
                    glow = np.clip(
                        np.maximum(mask, gaussian_filter(mask, LIGHT_HALO_SIGMA) * 2.0),
                        0.0, 1.0,
                    )
                except ImportError:
                    glow = mask
                night = night + glow[..., None] * LIGHT_RGB * LIGHT_STRENGTH

    return np.clip(night, 0, 255).astype(np.uint8)
