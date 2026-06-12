"""
预览渲染 CLI — 把 .hoi4proj 项目用游戏贴图合成预览 PNG, 不开 GUI。

用法:
    py tools/render_preview.py <project.hoi4proj> [输出.png]

M1 验收工具: 直接看合成效果, 也用于日后排查预览问题。
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image

from data.constants import set_map_size
from domain.project_io import load_project
from domain.managers.state import StateManager
from domain.managers.country import CountryManager
from domain.preview.compositor import compose_preview
from services.game_assets import GameAssets


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    proj_path = sys.argv[1]
    out_path = sys.argv[2] if len(sys.argv) > 2 else "preview.png"

    assets = GameAssets()
    if not assets.available():
        print("未找到 HOI4 安装目录")
        return 1
    tiles = assets.atlas_tiles()
    mapping = assets.terrain_to_texture()
    if tiles is None or mapping is None:
        print(f"游戏资产读取失败: {assets.last_error}")
        return 1

    t0 = time.perf_counter()
    tile_map, _pm, terrain_map, height_map, river_map, _pt, _snap = load_project(
        proj_path, StateManager(), CountryManager())
    set_map_size(tile_map.shape[1], tile_map.shape[0])
    t1 = time.perf_counter()

    img = compose_preview(tile_map, terrain_map, height_map, river_map,
                          tiles, mapping)
    t2 = time.perf_counter()

    Image.fromarray(img).save(out_path)
    print(f"加载 {t1 - t0:.1f}s | 合成 {t2 - t1:.1f}s | "
          f"{img.shape[1]}x{img.shape[0]} -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
