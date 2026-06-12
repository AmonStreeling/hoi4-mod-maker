"""
预览渲染器 — 合成游戏观感画面写入画布显示缓冲。

约定 (views/canvas/render_registry.py):
- 本模块刻意**不提供 partial_render**: 预览是整图合成, 局部刷新无意义,
  画布派发会自动回退全量渲染。
- 合成结果缓存在 canvas._preview_cache (H, W, 3 RGB uint8);
  invalidate_cache() 清缓存, 下次 render 重新合成 —
  预览页的"刷新预览"按钮走这条路。

游戏资产不可用时降级为大陆视图, 原因存到 canvas._preview_error
供侧栏页面显示。
"""

from __future__ import annotations

from services.game_assets import get_default_assets


def invalidate_cache(canvas) -> None:
    """清掉合成缓存, 下次渲染重新合成。"""
    canvas._preview_cache = None


def render(canvas) -> None:
    """全量渲染: 有缓存直接贴, 无缓存先合成。"""
    cache = getattr(canvas, "_preview_cache", None)
    if cache is None or cache.shape[:2] != canvas._tile_map.shape:
        cache = _compose(canvas)
        canvas._preview_cache = cache

    if cache is None:
        # 游戏资产不可用 → 降级大陆视图 (原因已写入 canvas._preview_error)
        from features.map.land.renderer import render as land_render
        land_render(canvas)
        return

    # RGB → 显示缓冲 (BGRA)
    buf = canvas._display_buffer
    buf[:, :, 0] = cache[:, :, 2]
    buf[:, :, 1] = cache[:, :, 1]
    buf[:, :, 2] = cache[:, :, 0]
    buf[:, :, 3] = 255


def _compose(canvas):
    """用当前地图数据 + 游戏贴图合成, 失败返回 None。"""
    assets = get_default_assets()
    tiles = assets.atlas_tiles()
    mapping = assets.terrain_to_texture()
    if tiles is None or mapping is None:
        canvas._preview_error = assets.last_error or "未找到 HOI4 安装目录"
        return None
    canvas._preview_error = ""

    from domain.preview.climate_tint import generate_climate_tint
    from domain.preview.compositor import compose_preview

    tint = generate_climate_tint(canvas._tile_map, canvas._height_map)
    return compose_preview(
        canvas._tile_map,
        canvas._terrain_map,
        canvas._height_map,
        canvas._river_map,
        tiles,
        mapping,
        tint=tint,
    )
