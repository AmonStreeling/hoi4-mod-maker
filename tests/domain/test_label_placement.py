"""label_placement 单元测试 — 质心/主轴/最大连通块选择"""
import numpy as np

from domain.label_placement import compute_region_labels


def test_empty_map():
    assert compute_region_labels(np.zeros((50, 80), dtype=np.int32)) == {}


def test_horizontal_rect_centroid_and_angle():
    m = np.zeros((100, 200), dtype=np.int32)
    m[40:60, 20:180] = 7  # 横向长条
    out = compute_region_labels(m, min_pixels=50)
    assert set(out) == {7}
    cx, cy, angle, length, width = out[7]
    assert abs(cx - 99.5) < 1.0
    assert abs(cy - 49.5) < 1.0
    assert abs(angle) < 5.0          # 主轴接近水平
    assert length > width            # 长轴 > 短轴


def test_vertical_strip_angle():
    m = np.zeros((200, 100), dtype=np.int32)
    m[20:180, 40:60] = 3  # 纵向长条
    out = compute_region_labels(m, min_pixels=50)
    _, _, angle, length, width = out[3]
    assert abs(abs(angle) - 90.0) < 5.0  # 主轴接近垂直
    assert length > width


def test_label_on_largest_component():
    m = np.zeros((100, 300), dtype=np.int32)
    m[10:20, 10:20] = 5            # 小岛 100px
    m[40:90, 100:280] = 5          # 本土 9000px
    out = compute_region_labels(m, min_pixels=50)
    cx, cy, _, _, _ = out[5]
    # 标签应落在本土, 不受小岛拉偏
    assert 100 <= cx <= 280
    assert 40 <= cy <= 90


def test_min_pixels_filter():
    m = np.zeros((100, 100), dtype=np.int32)
    m[10:12, 10:12] = 9  # 4 像素
    assert compute_region_labels(m, min_pixels=50) == {}


def test_two_regions():
    m = np.zeros((100, 200), dtype=np.int32)
    m[10:40, 10:90] = 1
    m[60:90, 110:190] = 2
    out = compute_region_labels(m, min_pixels=50)
    assert set(out) == {1, 2}
    assert out[1][0] < 100 < out[2][0]
