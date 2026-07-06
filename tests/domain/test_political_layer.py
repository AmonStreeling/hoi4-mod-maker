"""political 图层单元测试 — 混合/国界/无数据降级"""
import numpy as np

from domain.preview.political import apply_political_layer


def _base(h=10, w=10, v=100):
    return np.full((h, w, 3), v, dtype=np.uint8)


def test_no_country_data_returns_base():
    base = _base()
    out = apply_political_layer(base, None, None)
    assert out is base


def test_owned_area_blended():
    base = _base(v=100)
    rgb = np.zeros((10, 10, 3), dtype=np.uint8)
    rgb[:, :5] = (200, 0, 0)
    mask = np.zeros((10, 10), dtype=bool)
    mask[:, :5] = True
    out = apply_political_layer(base, rgb, mask, mix=0.5, border_dim=1.0)
    # 有主区域: 100*0.5 + 200*0.5 = 150 (R 通道)
    assert out[0, 0, 0] == 150
    # 无主区域保持底图
    assert (out[0, 7] == 100).all()


def test_border_darkened():
    base = _base(v=100)
    rgb = np.zeros((10, 10, 3), dtype=np.uint8)
    rgb[:, :5] = (200, 0, 0)
    rgb[:, 5:] = (0, 0, 200)
    mask = np.ones((10, 10), dtype=bool)
    out = apply_political_layer(base, rgb, mask, mix=0.5, border_dim=0.5)
    # 两国交界列 (x=4) 被压暗: 亮度低于同国内部像素
    assert out[5, 4].sum() < out[5, 2].sum()
