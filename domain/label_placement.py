"""名字标签排版 — 计算每个区域(州/国家)的文字位置/角度/大小.

效果: 模仿 HOI4 地图名字 — 文字放在区域最大连通块的质心,
     沿像素分布的主轴倾斜, 区域越大可用的文字长度越大.
适用: state/country 模式的名字叠加层. 纯 numpy+scipy, 零 Qt.
调用: compute_region_labels(id_map) → {id: (cx, cy, angle°, 长轴, 短轴)}
"""
import numpy as np
from scipy.ndimage import label as _cc_label


def compute_region_labels(
    id_map: np.ndarray,
    min_pixels: int = 300,
) -> dict[int, tuple[float, float, float, float, float]]:
    """区域 id 图 → 每个 id 的标签排版参数.

    id_map: (H, W) 整数图, 0 = 无归属(海洋/未分配), >0 = 区域 id.
    min_pixels: 小于该像素数的区域不出标签(太小放不下字).

    返回 {id: (cx, cy, angle_deg, length, width)}:
      cx/cy      — 最大连通块的质心(全图坐标)
      angle_deg  — 主轴倾角, [-90, 90), 顺时针为正(Qt 场景坐标系)
      length     — 沿主轴的可用长度(像素)
      width      — 垂直主轴的可用宽度(像素)

    实现: 先对全图做 4 连通标记, 每个 id 取像素最多的连通块
    (国家有飞地/殖民地时名字只放本土), 再用 bincount 一次算完
    所有区域的一二阶矩 → 质心 + PCA 主轴. 大图按步长降采样,
    避免 5632×2048 全量坐标数组吃内存.
    """
    h, w = id_map.shape
    max_id = int(id_map.max())
    if max_id <= 0:
        return {}

    # 降采样: 标签排版不需要逐像素精度, 大图取样到 ~512 高
    step = max(1, min(h, w) // 512)
    sub = id_map[::step, ::step]
    sub_min = max(1, min_pixels // (step * step))

    comp, _ = _cc_label(sub > 0)
    K = max_id + 1
    key = comp.ravel().astype(np.int64) * K + sub.ravel()
    counts = np.bincount(key)

    # 每个 id 挑像素最多的连通块 (key % K = id, key=0 是背景)
    nz = np.nonzero(counts)[0]
    nz = nz[nz % K != 0]
    best_key: dict[int, int] = {}
    for k in nz:
        rid = int(k % K)
        if counts[k] >= sub_min and (
            rid not in best_key or counts[k] > counts[best_key[rid]]
        ):
            best_key[rid] = int(k)
    if not best_key:
        return {}

    # 一二阶矩: 全部区域一次 bincount 算完, 不逐区域扫图
    sh, sw = sub.shape
    yy, xx = np.mgrid[0:sh, 0:sw]
    fx = xx.ravel().astype(np.float64)
    fy = yy.ravel().astype(np.float64)
    n_bins = len(counts)
    sx = np.bincount(key, weights=fx, minlength=n_bins)
    sy = np.bincount(key, weights=fy, minlength=n_bins)
    sxx = np.bincount(key, weights=fx * fx, minlength=n_bins)
    syy = np.bincount(key, weights=fy * fy, minlength=n_bins)
    sxy = np.bincount(key, weights=fx * fy, minlength=n_bins)

    out: dict[int, tuple[float, float, float, float, float]] = {}
    for rid, k in best_key.items():
        n = counts[k]
        mx = sx[k] / n
        my = sy[k] / n
        cxx = sxx[k] / n - mx * mx
        cyy = syy[k] / n - my * my
        cxy = sxy[k] / n - mx * my
        # 2×2 协方差特征值 → 主/次轴方差
        tr_half = (cxx + cyy) / 2.0
        det_root = np.sqrt(max(((cxx - cyy) / 2.0) ** 2 + cxy * cxy, 0.0))
        lam1 = max(tr_half + det_root, 1e-6)
        lam2 = max(tr_half - det_root, 1e-6)
        angle = float(np.degrees(0.5 * np.arctan2(2.0 * cxy, cxx - cyy)))
        if angle >= 90.0:
            angle -= 180.0
        elif angle < -90.0:
            angle += 180.0
        # 均匀分布近似: 全长 ≈ 3.46σ, 留些边距取 3.4
        length = 3.4 * float(np.sqrt(lam1)) * step
        width = 3.4 * float(np.sqrt(lam2)) * step
        out[rid] = (mx * step, my * step, angle, length, width)
    return out
