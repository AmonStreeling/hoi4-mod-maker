"""
原版地形统计提取 — 把 P 社美术的手艺量化成参数。

从游戏本体的 terrain.bmp + heightmap.bmp 提取:
1. 每种图形地形的占比 (陆地内)
2. 每个地形家族内部的变体混合比例 (森林 A:B、沙漠 A:B:C...)
3. 每种地形的海拔分布 (P25/P50/P75, 相对海平面)
4. 斑块粒度 (边界密度: 边界像素占比越高 = 斑块越碎)

输出的数字直接用作"保形美化地形"生成器的目标参数 —
"生成得好不好"的判据 = 统计上是否贴近原版。

用法: py tools/vanilla_terrain_stats.py
"""

import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PIL import Image

from services.game_assets import find_hoi4_install, parse_water_palette_indices, TERRAIN_DEF_RELPATH
from data.terrain_types import GRAPHICAL_TERRAIN_BY_INDEX

SEA_LEVEL = 95  # 原版海平面灰度


def main() -> int:
    game = find_hoi4_install()
    if game is None:
        print("未找到游戏目录")
        return 1

    terrain = np.asarray(Image.open(os.path.join(game, "map/terrain.bmp")))
    height = np.asarray(Image.open(os.path.join(game, "map/heightmap.bmp")))
    with open(os.path.join(game, TERRAIN_DEF_RELPATH), encoding="utf-8-sig",
              errors="replace") as f:
        water_idx = parse_water_palette_indices(f.read())

    land = ~np.isin(terrain, list(water_idx))
    land_total = int(land.sum())
    print(f"地图 {terrain.shape[1]}x{terrain.shape[0]}, 陆地像素 {land_total:,}\n")

    # ── 1+2. 占比 & 家族内变体比例 ──
    counts = np.bincount(terrain[land].ravel(), minlength=256)
    family_members: dict[str, list[tuple[int, int]]] = defaultdict(list)
    print("── 各图形地形占比 (陆地内) ──")
    for idx in np.nonzero(counts)[0]:
        n = int(counts[idx])
        gt = GRAPHICAL_TERRAIN_BY_INDEX.get(int(idx))
        name = f"{gt.id}({gt.type})" if gt else f"未登记索引{idx}"
        fam = gt.type if gt else f"idx{idx}"
        family_members[fam].append((int(idx), n))
        print(f"  idx {idx:>3} {name:<38} {n / land_total * 100:6.2f}%")

    print("\n── 家族内变体混合比例 ──")
    for fam, members in sorted(family_members.items()):
        if len(members) < 2:
            continue
        total = sum(n for _, n in members)
        ratio = " : ".join(
            f"idx{idx}={n / total * 100:.0f}%" for idx, n in
            sorted(members, key=lambda t: -t[1]))
        print(f"  {fam:<10} {ratio}")

    # ── 3. 每种地形的海拔分布 ──
    print("\n── 海拔分布 (相对海平面, P25/P50/P75) ──")
    hf = height.astype(np.int32) - SEA_LEVEL
    for fam, members in sorted(family_members.items()):
        fam_mask = np.isin(terrain, [i for i, _ in members]) & land
        vals = hf[fam_mask]
        if vals.size < 1000:
            continue
        p25, p50, p75 = np.percentile(vals, [25, 50, 75])
        print(f"  {fam:<10} P25={p25:5.0f}  P50={p50:5.0f}  P75={p75:5.0f}")

    # ── 4. 斑块粒度 (边界密度) ──
    diff_h = (terrain[:, 1:] != terrain[:, :-1]) & land[:, 1:] & land[:, :-1]
    diff_v = (terrain[1:, :] != terrain[:-1, :]) & land[1:, :] & land[:-1, :]
    boundary_ratio = (int(diff_h.sum()) + int(diff_v.sum())) / max(land_total, 1)
    print(f"\n── 斑块粒度 ──")
    print(f"  地形边界密度 (边界像素/陆地像素): {boundary_ratio:.3f}")
    print(f"  (数值越大斑块越碎; 我们生成器输出应贴近该值)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
