"""
河流管理器 — 河流数据存储与渲染
严格按原版 HOI4 rivers.bmp 格式：
  - 0:  源头（绿色）
  - 1:  红色标记
  - 2:  入海口（黄色）
  - 3:  河流宽度 1（最窄，浅蓝）
  - 4:  河流宽度 2
  - 5:  河流宽度 3
  - 6:  河流宽度 4（深蓝）
  - 7:  河流宽度 5
  - 8:  河流宽度 6
  - 9:  河流宽度 7
  - 10: 河流宽度 8
  - 11: 河流宽度 9（最宽）
  - 254: 海洋无河流（灰色背景）
  - 255: 陆地无河流（白色背景）
"""
import numpy as np

# 河流调色板索引（与原版一致）
RIVER_SOURCE = 0       # 源头
RIVER_MARKER = 1       # 红色标记
RIVER_MOUTH = 2        # 入海口
RIVER_WIDTH_1 = 3      # 最窄
RIVER_WIDTH_2 = 4
RIVER_WIDTH_3 = 5
RIVER_WIDTH_4 = 6
RIVER_WIDTH_5 = 7
RIVER_WIDTH_6 = 8
RIVER_WIDTH_7 = 9
RIVER_WIDTH_8 = 10
RIVER_WIDTH_9 = 11     # 最宽

# 背景值
RIVER_BG_SEA = 254     # 海洋区域背景
RIVER_BG_LAND = 255    # 陆地区域背景

# 擦除时使用的值（不是0，0是源头！用255=陆地背景）
RIVER_ERASE = RIVER_BG_LAND

# HOI4 rivers.bmp 调色板颜色（严格按原版）
# 格式: index → (R, G, B)
RIVER_PALETTE = {
    0: (0, 255, 0),         # 源头 — 绿色
    1: (255, 0, 0),         # 标记 — 红色
    2: (255, 252, 0),       # 入海口 — 黄色
    3: (0, 225, 255),       # 宽度1 — 浅蓝
    4: (0, 200, 255),       # 宽度2
    5: (0, 150, 255),       # 宽度3
    6: (0, 100, 255),       # 宽度4
    7: (0, 0, 255),         # 宽度5 — 纯蓝
    8: (0, 0, 225),         # 宽度6
    9: (0, 0, 200),         # 宽度7
    10: (0, 0, 150),        # 宽度8
    11: (0, 0, 100),        # 宽度9 — 深蓝
    12: (0, 85, 0),         # 保留
    13: (0, 125, 0),        # 保留
    14: (0, 158, 0),        # 保留
    15: (24, 206, 0),       # 保留
    254: (122, 122, 122),   # 海洋背景 — 灰色
    255: (255, 255, 255),   # 陆地背景 — 白色
}

# 画布显示用 BGRA 颜色
RIVER_DISPLAY_COLORS = {}
for _idx, (_r, _g, _b) in RIVER_PALETTE.items():
    RIVER_DISPLAY_COLORS[_idx] = (_b, _g, _r, 255)

# 可绘制的河流类型（工具面板中显示）
# 第 2 项是 i18n key，UI 调 tr() 获取中/英文名
# 标记类型 (单像素放置)
RIVER_MARKER_TYPES = [
    (RIVER_SOURCE, "river_marker_source"),     # 绿色, 每条河流一个
    (RIVER_MARKER, "river_marker_confluence"), # 红色, 支流汇入
    (RIVER_MOUTH,  "river_marker_mouth"),      # 黄色, 河流分支/出海口
]

# 宽度画笔 (拖拽绘制)
# 注意：跳过 index 5 和 8！vanilla rivers.bmp 从不用这两个索引，
# 手动画时选 5/8 会导致 HOI4 加载崩溃（EXCEPTION_INT_DIVIDE_BY_ZERO）
RIVER_WIDTH_TYPES = [
    (RIVER_WIDTH_1, "river_width_1"),  # index 3 — 细流
    (RIVER_WIDTH_2, "river_width_2"),  # index 4 — 小河
    (RIVER_WIDTH_4, "river_width_4"),  # index 6（跳过 5）— 中河
    (RIVER_WIDTH_5, "river_width_5"),  # index 7 — 大河
    (RIVER_WIDTH_7, "river_width_7"),  # index 9（跳过 8）— 宽河
    (RIVER_WIDTH_8, "river_width_8"),  # index 10 — 巨河
    (RIVER_WIDTH_9, "river_width_9"),  # index 11 — 最宽
]

# 保持向后兼容
PAINTABLE_RIVER_TYPES = RIVER_MARKER_TYPES + RIVER_WIDTH_TYPES

# 有效的河流值（可以画的，不含背景）
VALID_RIVER_VALUES = set(range(0, 12))


def validate_rivers(river_map: np.ndarray, lang: str = "zh") -> list[str]:
    """验证河流数据，返回问题列表（双语）。
    检查：
    1. 每条连通河流有且仅有一个绿色源头 (index 0)
    2. 河流是否为 1 像素宽
    3. 是否有对角线连接
    """
    from scipy.ndimage import label

    en = lang == "en"
    warnings: list[str] = []

    # 河流像素 mask (非背景的所有像素)
    river_mask = np.zeros_like(river_map, dtype=bool)
    for v in VALID_RIVER_VALUES:
        river_mask |= (river_map == v)

    if not np.any(river_mask):
        return ["No river data" if en else "没有河流数据"]

    # 用 8 连通标记找出每条河流
    struct_8conn = np.ones((3, 3), dtype=int)
    labeled, num_rivers = label(river_mask, structure=struct_8conn)

    # 每条河的像素数/源头数一次 bincount 算完 (不逐河全图扫描)
    pixel_counts = np.bincount(labeled.ravel(), minlength=num_rivers + 1)
    source_counts = np.bincount(
        labeled[river_map == RIVER_SOURCE].ravel(), minlength=num_rivers + 1
    )
    for river_id in range(1, num_rivers + 1):
        if source_counts[river_id] == 0:
            pixel_count = int(pixel_counts[river_id])
            if en:
                warnings.append(f"River #{river_id} ({pixel_count}px): missing source marker (green)")
            else:
                warnings.append(f"河流 #{river_id} ({pixel_count}px): 缺少源头标记(绿色)")

    # 检查宽度：河流像素中不应有 2x2 的实心块
    rm = river_mask.astype(np.uint8)
    block_sum = (rm[:-1, :-1] + rm[:-1, 1:] + rm[1:, :-1] + rm[1:, 1:])
    wide_pixels = int((block_sum >= 4).sum())
    if wide_pixels > 0:
        if en:
            warnings.append(f"{wide_pixels} places where river is wider than 1 pixel (2x2 solid block)")
        else:
            warnings.append(f"河流中有 {wide_pixels} 处宽度超过 1 像素 (2x2 实心块)")

    # 检查对角线连接
    diag_count = 0
    ys, xs = np.where(river_mask)
    h, w = river_map.shape
    for dy, dx in [(-1, -1), (-1, 1), (1, -1), (1, 1)]:
        ny, nx = ys + dy, xs + dx
        valid = (ny >= 0) & (ny < h) & (nx >= 0) & (nx < w)
        has_diag = valid & river_mask[np.clip(ny, 0, h-1), np.clip(nx, 0, w-1)]
        n1y, n1x = ys + dy, xs
        n2y, n2x = ys, xs + dx
        v1 = (n1y >= 0) & (n1y < h) & (n1x >= 0) & (n1x < w)
        v2 = (n2y >= 0) & (n2y < h) & (n2x >= 0) & (n2x < w)
        has_n1 = v1 & river_mask[np.clip(n1y, 0, h-1), np.clip(n1x, 0, w-1)]
        has_n2 = v2 & river_mask[np.clip(n2y, 0, h-1), np.clip(n2x, 0, w-1)]
        pure_diag = has_diag & ~has_n1 & ~has_n2
        diag_count += int(pure_diag.sum())
    if diag_count > 0:
        if en:
            warnings.append(f"{diag_count // 2} diagonal connections found (should be orthogonal)")
        else:
            warnings.append(f"河流中有 {diag_count // 2} 处对角线连接 (应为正交)")

    if not warnings:
        warnings.append("River validation passed ✓" if en else "河流验证通过 ✓")

    return warnings
