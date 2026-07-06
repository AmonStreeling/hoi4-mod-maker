"""River 模式渲染: 地形底图 + 河流叠加.

HOI4 规定河流必须 1 像素宽，但在画布上 1 像素的蓝/红/黄线条几乎看不见，
只有亮绿色的"源头"显眼。所以渲染时我们**在视觉上膨胀**河流显示为 3 像素，
但数据层仍保持 1 像素（导出的 rivers.bmp 不受影响）。
"""

import numpy as np

from features.map.terrain import renderer as terrain_renderer
from domain.managers.river import VALID_RIVER_VALUES


# 视觉膨胀半径（画布显示加粗）。0 = 不膨胀（1px），1 = 3×3，2 = 5×5
# 数据层永远是 1px（HOI4 规则），这只影响编辑器里的视觉粗细。
_DISPLAY_DILATE_RADIUS = 0


def _make_river_mask(river_data: np.ndarray) -> np.ndarray:
    """河流像素 mask: 所有有效河流值 (含 0=源头)."""
    mask = np.zeros(river_data.shape, dtype=bool)
    for v in VALID_RIVER_VALUES:
        mask |= (river_data == v)
    return mask


def _dilated_color_overlay(
    river_data: np.ndarray, color_lut: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """返回 (dilated_mask, dilated_colors) — 在原始 river_data 的 1px 基础上
    视觉扩展成 (2r+1) × (2r+1) 的粗线。

    颜色优先级：源头/汇入点/入海口 > 宽度索引。
    即若一个邻域内既有宽度又有 marker，marker 颜色胜出。
    """
    h, w = river_data.shape
    r = _DISPLAY_DILATE_RADIUS
    if r <= 0:
        return _make_river_mask(river_data), color_lut[river_data]

    # 源 mask（原始 1px 河流位置）
    src_mask = _make_river_mask(river_data)
    if not np.any(src_mask):
        return src_mask, color_lut[river_data]

    # 每个像素的颜色来源：优先选"源头/汇入点/入海口"（索引 0/1/2），其次宽度
    # 先算一个"优先级"场：markers = 高，widths = 低，bg = 0
    priority = np.zeros_like(river_data, dtype=np.uint8)
    priority[src_mask] = 1  # 普通河流
    priority[(river_data == 0) | (river_data == 1) | (river_data == 2)] = 2  # markers

    # 膨胀：扫描每个偏移 (dy, dx) ∈ [-r, r]，把原像素复制到邻域，保留高优先级
    out_values = np.zeros_like(river_data)
    out_priority = np.zeros_like(priority)
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            # 把 river_data 沿 (dy, dx) 位移到画布
            y_src_start = max(0, -dy)
            y_src_end = min(h, h - dy)
            x_src_start = max(0, -dx)
            x_src_end = min(w, w - dx)
            y_dst_start = max(0, dy)
            y_dst_end = min(h, h + dy)
            x_dst_start = max(0, dx)
            x_dst_end = min(w, w + dx)

            src_vals = river_data[y_src_start:y_src_end, x_src_start:x_src_end]
            src_prio = priority[y_src_start:y_src_end, x_src_start:x_src_end]
            dst_vals = out_values[y_dst_start:y_dst_end, x_dst_start:x_dst_end]
            dst_prio = out_priority[y_dst_start:y_dst_end, x_dst_start:x_dst_end]

            # 更高优先级的值覆盖
            win = src_prio > dst_prio
            dst_vals[win] = src_vals[win]
            dst_prio[win] = src_prio[win]

    dilated_mask = out_priority > 0
    dilated_colors = color_lut[out_values]
    return dilated_mask, dilated_colors


def render(canvas) -> None:
    from ui.canvas_widget import _RIVER_COLOR_LUT
    # 先渲染地形作为底图（画河要看得见山谷走向）
    terrain_renderer.render(canvas)
    mask, colors = _dilated_color_overlay(canvas._river_map, _RIVER_COLOR_LUT)
    if np.any(mask):
        canvas._display_buffer[mask] = colors[mask]


def partial_render(canvas, x0: int, y0: int, x1: int, y1: int) -> None:
    from ui.canvas_widget import _RIVER_COLOR_LUT
    # 膨胀显示会让 1px 的源像素影响 ±r 邻域 → 局部刷新范围必须也扩大
    r = _DISPLAY_DILATE_RADIUS
    h, w = canvas._river_map.shape
    ex0 = max(0, x0 - r)
    ey0 = max(0, y0 - r)
    ex1 = min(w, x1 + r)
    ey1 = min(h, y1 + r)
    # 先把扩大区域的底图（地形）重绘，免得旧的河流像素留在扩展带
    terrain_renderer.partial_render(canvas, ex0, ey0, ex1, ey1)
    region = canvas._river_map[ey0:ey1, ex0:ex1]
    mask, colors = _dilated_color_overlay(region, _RIVER_COLOR_LUT)
    if np.any(mask):
        buf = canvas._display_buffer[ey0:ey1, ex0:ex1]
        buf[mask] = colors[mask]
