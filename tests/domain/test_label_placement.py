"""label_placement 单元测试 — 质心/主轴/连通块拆分"""
import numpy as np

from domain.label_placement import compute_region_labels


def test_empty_map():
    assert compute_region_labels(np.zeros((50, 80), dtype=np.int32)) == {}


def test_horizontal_rect_centroid_and_angle():
    m = np.zeros((100, 200), dtype=np.int32)
    m[40:60, 20:180] = 7  # 横向长条
    out = compute_region_labels(m, min_pixels=50)
    assert set(out) == {7}
    assert len(out[7]) == 1
    cx, cy, angle, length, width = out[7][0]
    assert abs(cx - 99.5) < 1.0
    assert abs(cy - 49.5) < 1.0
    assert abs(angle) < 5.0          # 主轴接近水平
    assert length > width            # 长轴 > 短轴


def test_vertical_strip_angle():
    m = np.zeros((200, 100), dtype=np.int32)
    m[20:180, 40:60] = 3  # 纵向长条
    out = compute_region_labels(m, min_pixels=50)
    _, _, angle, length, width = out[3][0]
    assert abs(abs(angle) - 90.0) < 5.0  # 主轴接近垂直
    assert length > width


def test_each_component_gets_label_largest_first():
    m = np.zeros((100, 300), dtype=np.int32)
    m[10:20, 10:20] = 5            # 小岛 100px
    m[40:90, 100:280] = 5          # 本土 9000px
    out = compute_region_labels(m, min_pixels=50)
    assert len(out[5]) == 2        # 每块各一个名字
    cx, cy, _, _, _ = out[5][0]    # 大块在前 → 本土
    assert 100 <= cx <= 280
    assert 40 <= cy <= 90
    cx2, cy2, _, _, _ = out[5][1]  # 小岛
    assert 10 <= cx2 <= 20
    assert 10 <= cy2 <= 20


def test_split_by_neighbor_land_not_merged():
    # 同一区域被另一区域的陆地切成两半(同大陆飞地):
    # 名字必须一块一个, 不能按整体质心横穿中间的邻区
    m = np.zeros((100, 300), dtype=np.int32)
    m[20:80, 10:100] = 1     # 区域1 左块
    m[20:80, 100:200] = 2    # 区域2 夹在中间
    m[20:80, 200:290] = 1    # 区域1 右块
    out = compute_region_labels(m, min_pixels=50)
    assert len(out[1]) == 2
    assert len(out[2]) == 1
    xs = sorted(p[0] for p in out[1])
    assert xs[0] < 100          # 左块质心在左块内
    assert xs[1] > 200          # 右块质心在右块内
    assert 100 < out[2][0][0] < 200


def test_min_pixels_filter():
    m = np.zeros((100, 100), dtype=np.int32)
    m[10:12, 10:12] = 9  # 4 像素
    assert compute_region_labels(m, min_pixels=50) == {}


def test_min_pixels_filters_small_component_only():
    m = np.zeros((100, 300), dtype=np.int32)
    m[10:13, 10:13] = 5            # 9px 碎块, 低于门槛
    m[40:90, 100:280] = 5          # 本土
    out = compute_region_labels(m, min_pixels=50)
    assert len(out[5]) == 1        # 碎块不出名字


def test_two_regions():
    m = np.zeros((100, 200), dtype=np.int32)
    m[10:40, 10:90] = 1
    m[60:90, 110:190] = 2
    out = compute_region_labels(m, min_pixels=50)
    assert set(out) == {1, 2}
    assert out[1][0][0] < 100 < out[2][0][0]
