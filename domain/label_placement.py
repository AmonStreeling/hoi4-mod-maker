"""名字标签排版 — 计算每个区域(州/国家)的文字位置/角度/大小.

效果: 模仿 HOI4 地图名字 — 区域每个连通块各放一个名字,
     文字沿块内像素分布的主轴倾斜, 块越大可用的文字长度越大.
适用: state/country 模式的名字叠加层. 纯 numpy+scipy, 零 Qt.
调用: compute_region_labels(id_map) → {id: [(cx, cy, angle°, 长轴, 短轴), ...]}
"""
import numpy as np
from scipy.ndimage import label as _cc_label


def compute_region_labels(
    id_map: np.ndarray,
    min_pixels: int = 300,
) -> dict[int, list[tuple[float, float, float, float, float]]]:
    """区域 id 图 → 每个 id 的标签排版参数(每个连通块一条).

    id_map: (H, W) 整数图, 0 = 无归属(海洋/未分配), >0 = 区域 id.
    min_pixels: 小于该像素数的连通块不出标签(太小放不下字).

    返回 {id: [(cx, cy, angle_deg, length, width), ...]}, 大块在前:
      cx/cy      — 连通块的质心(全图坐标)
      angle_deg  — 主轴倾角, [-90, 90), 顺时针为正(Qt 场景坐标系)
      length     — 沿主轴的可用长度(像素)
      width      — 垂直主轴的可用宽度(像素)

    实现: 连通性按 id 判定 — 被别国陆地隔开的飞地是独立块,
    各得一个名字(直接对 >0 做二值标记会把同大陆的飞地粘成
    一块, 名字会横穿邻国). 做法是把降采样图 3× 放大, 只在同
    id 相邻像素间铺连接条, 一次 CC 就按 id 边界断开; 一二阶矩
    全部连通块一次 bincount 算完 → 质心 + PCA 主轴. 全程无
    逐区域扫图, 耗时与区域数/碎片数无关.
    """
    h, w = id_map.shape
    max_id = int(id_map.max())
    if max_id <= 0:
        return {}

    # 降采样: 标签排版不需要逐像素精度, 大图取样到 ~512 高
    step = max(1, min(h, w) // 512)
    sub = id_map[::step, ::step]
    sub_min = max(1, min_pixels // (step * step))
    sh, sw = sub.shape
    fg = sub > 0

    # 3× 放大: 中心点放在 (3i+1, 3j+1), 同 id 的相邻中心之间
    # 铺 2 个连接像素 → 4 连通 CC 自动在 id 边界断开
    big = np.zeros((sh * 3, sw * 3), dtype=bool)
    big[1::3, 1::3] = fg
    same_r = fg[:, :-1] & (sub[:, :-1] == sub[:, 1:])   # 右邻同 id
    big[1::3, 2::3][:, :-1] = same_r
    big[1::3, 3::3] = same_r
    same_d = fg[:-1, :] & (sub[:-1, :] == sub[1:, :])   # 下邻同 id
    big[2::3, 1::3][:-1, :] = same_d
    big[3::3, 1::3] = same_d

    comp3, ncomp = _cc_label(big)
    if ncomp == 0:
        return {}
    comp = comp3[1::3, 1::3]            # 回到 sub 尺寸, 0 = 背景
    flat = comp.ravel().astype(np.int64)
    counts = np.bincount(flat, minlength=ncomp + 1)
    # 每个连通块属于哪个 id (块内 id 相同, 任取一个像素即可)
    comp_id = np.zeros(ncomp + 1, dtype=np.int64)
    comp_id[flat] = sub.ravel()

    keep = np.nonzero((counts >= sub_min) & (comp_id > 0))[0]
    if keep.size == 0:
        return {}
    keep = keep[np.argsort(-counts[keep], kind="stable")]  # 大块在前

    # 一二阶矩: 全部连通块一次 bincount 算完, 不逐块扫图
    yy, xx = np.mgrid[0:sh, 0:sw]
    fx = xx.ravel().astype(np.float64)
    fy = yy.ravel().astype(np.float64)
    n_bins = ncomp + 1
    sx = np.bincount(flat, weights=fx, minlength=n_bins)
    sy = np.bincount(flat, weights=fy, minlength=n_bins)
    sxx = np.bincount(flat, weights=fx * fx, minlength=n_bins)
    syy = np.bincount(flat, weights=fy * fy, minlength=n_bins)
    sxy = np.bincount(flat, weights=fx * fy, minlength=n_bins)

    out: dict[int, list[tuple[float, float, float, float, float]]] = {}
    for c in keep:
        n = counts[c]
        mx = sx[c] / n
        my = sy[c] / n
        cxx = sxx[c] / n - mx * mx
        cyy = syy[c] / n - my * my
        cxy = sxy[c] / n - mx * my
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
        out.setdefault(int(comp_id[c]), []).append(
            (mx * step, my * step, angle, length, width)
        )
    return out
