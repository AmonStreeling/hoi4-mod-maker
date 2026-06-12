"""
预览功能集成测试 — 渲染器缓存 / 降级 / 模式接入。

游戏文件不进 CI: 合成走假资产, 真实资产相关行为由 test_game_assets 覆盖。
"""

from types import SimpleNamespace

import numpy as np
import pytest
from PyQt5.QtWidgets import QApplication

import services.game_assets as ga
from features.map.preview import renderer as preview_renderer


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def canvas(qapp):
    """对齐全局尺寸后构造画布 (与 test_render_registry 相同的防御)。"""
    import views.canvas.widget as widget_mod
    import data.constants as constants
    from data.constants import set_map_size

    old_w, old_h = constants.MAP_WIDTH, constants.MAP_HEIGHT
    set_map_size(widget_mod.MAP_WIDTH, widget_mod.MAP_HEIGHT)
    try:
        yield widget_mod.MapCanvas()
    finally:
        set_map_size(old_w, old_h)


@pytest.fixture()
def fake_assets(monkeypatch):
    """注入 16 瓦片假资产, 测试结束还原默认单例。"""
    tiles = np.zeros((16, 4, 4, 4), dtype=np.uint8)
    tiles[:, :, :, 1] = 200          # 全绿瓦片
    tiles[:, :, :, 3] = 255
    fake = SimpleNamespace(
        atlas_tiles=lambda: tiles,
        terrain_to_texture=lambda: {0: 1},
        available=lambda: True,
        install_dir="<fake>",
        last_error="",
    )
    monkeypatch.setattr(ga, "_default_assets", fake)
    yield fake


def test_preview_mode_is_valid_and_registered(canvas):
    """preview 是合法显示模式且注册了渲染器。"""
    from views.canvas.render_registry import DEFAULT_RENDERERS
    canvas.display_mode = "preview"
    assert canvas.display_mode == "preview"
    assert DEFAULT_RENDERERS["preview"] == "features.map.preview.renderer"


def test_render_composes_and_caches(canvas, fake_assets):
    """首次渲染合成并缓存; 再次渲染直接用缓存。"""
    preview_renderer.render(canvas)
    cache1 = canvas._preview_cache
    assert cache1 is not None
    assert cache1.shape == (*canvas._tile_map.shape, 3)

    preview_renderer.render(canvas)
    assert canvas._preview_cache is cache1     # 同一对象 = 没重新合成


def test_invalidate_cache_forces_recompose(canvas, fake_assets):
    """invalidate_cache 后重新合成 (刷新按钮的路径)。"""
    preview_renderer.render(canvas)
    cache1 = canvas._preview_cache
    preview_renderer.invalidate_cache(canvas)
    preview_renderer.render(canvas)
    assert canvas._preview_cache is not cache1


def test_degrades_to_land_when_assets_unavailable(canvas, monkeypatch):
    """游戏资产不可用: 不崩, 降级 land 渲染, 原因可供页面显示。"""
    broken = SimpleNamespace(
        atlas_tiles=lambda: None,
        terrain_to_texture=lambda: None,
        available=lambda: False,
        install_dir=None,
        last_error="未找到 HOI4 安装目录",
    )
    monkeypatch.setattr(ga, "_default_assets", broken)
    preview_renderer.invalidate_cache(canvas)

    preview_renderer.render(canvas)            # 不抛异常

    assert canvas._preview_cache is None
    assert canvas._preview_error != ""


def test_preview_mode_enables_smooth_scaling(canvas):
    """预览模式开平滑缩放 (纹理图), 编辑模式保持最近邻 (像素硬边)。"""
    from PyQt5.QtGui import QPainter
    canvas.display_mode = "preview"
    assert canvas.renderHints() & QPainter.RenderHint.SmoothPixmapTransform
    canvas.display_mode = "land"
    assert not (canvas.renderHints() & QPainter.RenderHint.SmoothPixmapTransform)


def test_renderer_has_no_partial_render():
    """预览渲染器刻意不提供 partial_render (画布将回退全量)。"""
    assert not hasattr(preview_renderer, "partial_render")
