"""
画布渲染派发注册化测试。

验证 2026-06 架构整理: 显示模式 → renderer 模块由注册表驱动,
新模式 (如预览) 通过 register_renderer 接入, 不再改 widget.py。
"""

from types import SimpleNamespace

import pytest
from PyQt5.QtWidgets import QApplication

from views.canvas.render_registry import DEFAULT_RENDERERS


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def canvas(qapp):
    """构造画布前把全局尺寸对齐到 widget 模块绑定的常量。

    MapCanvas 的缓冲区用 import 时绑定的 MAP_WIDTH/MAP_HEIGHT,
    而 MapData 读运行时全局尺寸 — 若前面有测试改过尺寸会错位。
    """
    import views.canvas.widget as widget_mod
    import data.constants as constants
    from data.constants import set_map_size

    old_w, old_h = constants.MAP_WIDTH, constants.MAP_HEIGHT
    set_map_size(widget_mod.MAP_WIDTH, widget_mod.MAP_HEIGHT)
    try:
        yield widget_mod.MapCanvas()
    finally:
        set_map_size(old_w, old_h)


def test_default_registry_covers_all_valid_modes():
    """所有合法显示模式都有注册的渲染器。"""
    for mode in ("land", "terrain", "height", "province", "state", "country",
                 "river", "logistics", "continent", "strategic_region",
                 "colormap", "default_map", "province_terrain"):
        assert mode in DEFAULT_RENDERERS


# partial_render 是可选约定 — 整图合成类渲染器明确豁免 (画布回退全量)
_NO_PARTIAL_MODES = {"preview"}


def test_all_registered_renderer_modules_import():
    """注册表里每个模块路径都能真实 import 且符合渲染器约定。"""
    import importlib
    for mode, path in DEFAULT_RENDERERS.items():
        mod = importlib.import_module(path)
        assert callable(mod.render), f"{mode}: {path} 缺 render()"
        if mode in _NO_PARTIAL_MODES:
            assert not hasattr(mod, "partial_render"), \
                f"{mode} 声明为整图合成, 不应提供 partial_render"
        else:
            assert callable(mod.partial_render), f"{mode}: {path} 缺 partial_render()"


def test_resolve_renderer_imports_and_caches(canvas):
    """land 渲染器可解析为真实模块, 且二次解析走缓存。"""
    r1 = canvas._resolve_renderer("land")
    assert callable(r1.render)
    assert canvas._resolve_renderer("land") is r1


def test_registered_mode_dispatches_full_render(canvas):
    """注册的新模式被 _full_render 派发到 (预览模式的接入路径)。"""
    calls = []
    fake = SimpleNamespace(render=lambda c: calls.append("full"))
    canvas._renderer_paths["fake_mode"] = "<test>"
    canvas._renderer_cache["fake_mode"] = fake
    canvas._display_mode = "fake_mode"

    canvas._full_render()

    assert calls == ["full"]


def test_partial_render_falls_back_to_full_when_unsupported(canvas):
    """渲染器没有 partial_render → 局部渲染回退全量 (整图合成类模式)。"""
    calls = []
    fake = SimpleNamespace(render=lambda c: calls.append("full"))  # 无 partial_render
    canvas._renderer_paths["fake_mode"] = "<test>"
    canvas._renderer_cache["fake_mode"] = fake
    canvas._display_mode = "fake_mode"

    canvas._partial_render(0, 0, 4, 4)

    assert calls == ["full"]


def test_unknown_mode_falls_back_to_land(canvas):
    """未注册的模式回退 land 渲染器, 不崩溃。"""
    canvas._display_mode = "no_such_mode"
    canvas._full_render()  # 不抛异常即通过


def test_register_renderer_overrides_and_invalidates_cache(canvas):
    """register_renderer 覆盖旧注册并清缓存。"""
    canvas._renderer_cache["land"] = SimpleNamespace(render=lambda c: None)
    canvas.register_renderer("land", "features.map.land.renderer")
    assert "land" not in canvas._renderer_cache
    assert canvas._renderer_paths["land"] == "features.map.land.renderer"


def test_dead_merge_provinces_removed(canvas):
    """死代码 merge_provinces 已删除 (现行合并走 MergeProvincesCommand)。"""
    assert not hasattr(canvas, "merge_provinces")
