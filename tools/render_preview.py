"""
预览渲染 CLI — 用游戏贴图合成预览 PNG, 不开 GUI。

用法:
    py tools/render_preview.py <project.hoi4proj> [输出.png]            # 渲染项目
    py tools/render_preview.py <project.hoi4proj> [输出.png] --enrich   # 演示: 地形自动细化
    py tools/render_preview.py vanilla [输出.png]                       # 渲染游戏原版地图

--enrich 只在内存里细化地形, 项目文件零改动 — 用于演示效果。

M1 验收工具: 直接看合成效果, 也用于日后排查预览问题。
vanilla 模式是对照实验: 同样的数据游戏怎么画 vs 我们怎么画,
差距即合成公式的差距, 与项目数据质量无关。
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PIL import Image

from data.constants import set_map_size, TILE_LAND, TILE_SEA
from domain.project_io import load_project
from domain.managers.state import StateManager
from domain.managers.country import CountryManager
from domain.preview.compositor import compose_preview
from services.game_assets import GameAssets


def _load_project_layers(proj_path: str, enrich: bool = False,
                         realheight: bool = False):
    tile_map, _pm, terrain_map, height_map, river_map, _pt, _snap = load_project(
        proj_path, StateManager(), CountryManager())
    if realheight:
        # 演示模式: 内存里重新生成真实感高度图, 不写回项目
        from domain.generators.heightmap import generate_realistic_heightmap
        height_map = generate_realistic_heightmap(tile_map)
    if enrich:
        # 演示模式: 内存里自动细化地形, 不写回项目
        from domain.generators.terrain_detail import generate_detailed_terrain
        terrain_map = generate_detailed_terrain(tile_map, height_map)
    # 自制地图没有手绘色调图 → 按纬度/海拔自动生成气候色调
    from domain.preview.climate_tint import generate_climate_tint
    tint = generate_climate_tint(tile_map, height_map)
    return tile_map, terrain_map, height_map, river_map, tint


def _load_vanilla_layers(assets: GameAssets):
    """读游戏原版 map/ 下的三张 BMP + 配套色调图。"""
    g = assets.install_dir
    terrain_map = np.asarray(Image.open(os.path.join(g, "map/terrain.bmp")))
    height_map = np.asarray(Image.open(os.path.join(g, "map/heightmap.bmp")))
    river_map = np.asarray(Image.open(os.path.join(g, "map/rivers.bmp")))

    water_idx = assets.water_palette_indices() or set()
    is_water = np.isin(terrain_map, list(water_idx))
    tile_map = np.where(is_water, TILE_SEA, TILE_LAND).astype(np.uint8)

    # 色调图是地图一半分辨率, 放大 2 倍对齐
    tint = assets.colormap_rgb()
    if tint is not None:
        fy = terrain_map.shape[0] // tint.shape[0]
        fx = terrain_map.shape[1] // tint.shape[1]
        if fy >= 1 and fx >= 1:
            tint = np.repeat(np.repeat(tint, fy, axis=0), fx, axis=1)
            tint = tint[:terrain_map.shape[0], :terrain_map.shape[1]]
        else:
            tint = None
    return tile_map, terrain_map, height_map, river_map, tint


def main() -> int:
    args = [a for a in sys.argv[1:] if a not in ("--enrich", "--realheight")]
    enrich = "--enrich" in sys.argv
    realheight = "--realheight" in sys.argv
    if not args:
        print(__doc__)
        return 2
    source = args[0]
    default_out = "preview_vanilla.png" if source == "vanilla" else "preview.png"
    out_path = args[1] if len(args) > 1 else default_out

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
    if source == "vanilla":
        tile_map, terrain_map, height_map, river_map, tint = \
            _load_vanilla_layers(assets)
    else:
        tile_map, terrain_map, height_map, river_map, tint = \
            _load_project_layers(source, enrich=enrich, realheight=realheight)
    set_map_size(tile_map.shape[1], tile_map.shape[0])
    t1 = time.perf_counter()

    img = compose_preview(tile_map, terrain_map, height_map, river_map,
                          tiles, mapping, tint=tint)
    t2 = time.perf_counter()

    Image.fromarray(img).save(out_path)
    print(f"加载 {t1 - t0:.1f}s | 合成 {t2 - t1:.1f}s | "
          f"{img.shape[1]}x{img.shape[0]} -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
