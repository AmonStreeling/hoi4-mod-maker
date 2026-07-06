"""政治视图图层 — 在预览底图上叠加国家势力色 (原版政治地图模式).

效果: 有主陆地 = 底图光影 × 国家色混合, 国界压暗成深色细线,
     无主陆地/海洋保持底图原样 — 和游戏内政治模式同配方。
适用: 预览模式的"政治视图"开关。
调用: apply_political_layer(base, country_rgb, owned_mask) → RGB uint8。
配方标定: 用原版全图数据实测对照 (scratchpad political_sample), mix=0.62。
"""

from __future__ import annotations

import numpy as np

# 国家色混合权重 (0=纯底图, 1=纯色块); 0.62 实测最接近原版观感
POLITICAL_MIX = 0.62
# 国界压暗系数 (原版是深色细线)
BORDER_DIM = 0.35


def apply_political_layer(
    base: np.ndarray,
    country_rgb: np.ndarray | None,
    owned_mask: np.ndarray | None,
    mix: float = POLITICAL_MIX,
    border_dim: float = BORDER_DIM,
) -> np.ndarray:
    """底图 (H, W, 3 RGB) + 国家色图/有主掩码 → 政治视图 RGB uint8.

    country_rgb/owned_mask 为 None 时原样返回底图 (没有国家数据可叠)。
    """
    if country_rgb is None or owned_mask is None or not owned_mask.any():
        return base

    basef = base.astype(np.float32)
    out = basef.copy()
    blend = basef * (1.0 - mix) + country_rgb.astype(np.float32) * mix
    out[owned_mask] = blend[owned_mask]

    # 国界: 相邻像素国家色不同且至少一侧有主 → 压暗
    oc = np.where(owned_mask[..., None], country_rgb, 0).astype(np.int32)
    border = np.zeros(owned_mask.shape, dtype=bool)
    diff_v = (oc[:-1] != oc[1:]).any(axis=2) & (owned_mask[:-1] | owned_mask[1:])
    border[:-1][diff_v] = True
    diff_h = (oc[:, :-1] != oc[:, 1:]).any(axis=2) & (owned_mask[:, :-1] | owned_mask[:, 1:])
    border[:, :-1][diff_h] = True
    out[border] *= border_dim

    return np.clip(out, 0, 255).astype(np.uint8)
