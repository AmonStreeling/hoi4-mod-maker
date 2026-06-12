"""
显示模式 → renderer 模块路径 注册表。

加新显示模式 = 在 DEFAULT_RENDERERS 加一行, 不再需要改 canvas/widget.py
(旧做法是在 widget.py 手写 _render_X_mode / _partial_render_X 薄壳对,
 已在 2026-06 架构整理中废除)。

renderer 模块的约定:
- 必须提供 render(canvas) — 全量渲染
- 可选提供 partial_render(canvas, x0, y0, x1, y1) — 局部渲染;
  没有该函数的模式 (如预览这种整图合成) 自动回退全量渲染

模块按需延迟加载并缓存, 与旧薄壳的延迟 import 行为一致。
运行时扩展走 MapCanvas.register_renderer(mode, module_path)。
"""

DEFAULT_RENDERERS: dict[str, str] = {
    "land": "features.map.land.renderer",
    "terrain": "features.map.terrain.renderer",
    "height": "features.map.height.renderer",
    "province": "features.map.province.renderer",
    "state": "features.map.state.renderer",
    "country": "features.map.country.renderer",
    "river": "features.map.river.renderer",
    "logistics": "features.map.logistics.renderer",
    "continent": "features.map.continent.renderer",
    "strategic_region": "features.map.strategic_region.renderer",
    "province_terrain": "features.map.province_terrain.renderer",
    # 预览: 整图合成, 无 partial_render (自动回退全量)
    "preview": "features.map.preview.renderer",
    # 暂无专用渲染的模式复用 land
    "colormap": "features.map.land.renderer",
    "default_map": "features.map.land.renderer",
}
