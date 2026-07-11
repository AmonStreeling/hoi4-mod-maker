"""命令行导出: python cli_export.py <project.hoi4proj> [output_dir] [--mod-name NAME]

从 .hoi4proj 项目文件加载数据, 自动补全缺失内容, 导出可玩 MOD.
"""
import os
import sys
import shutil
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from data.constants import TILE_LAND, TILE_SEA, TILE_LAKE
from data.terrain_types import TERRAIN_PALETTE_INDEX
from domain.managers.state import StateManager
from domain.managers.country import CountryManager
from domain.managers.continent import ContinentManager
from domain.managers.adjacency import AdjacencyManager
from domain.managers.railway import RailwayManager
from domain.managers.supply_node import SupplyNodeManager
from domain.managers.adjacency_rule import AdjacencyRuleManager
from domain.managers.strategic_region import StrategicRegionManager
from domain.project_io import load_project
from export.mod_exporter import export_full_mod


DEFAULT_OUTPUT = "D:/Documents/Paradox Interactive/Hearts of Iron IV/mod/WorldTest"
DEFAULT_MOD_NAME = "WorldTest"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="从 .hoi4proj 项目文件导出 HOI4 MOD"
    )
    parser.add_argument("project", help=".hoi4proj 项目文件路径")
    parser.add_argument(
        "output_dir", nargs="?", default=DEFAULT_OUTPUT,
        help=f"导出目录 (默认: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--mod-name", default=DEFAULT_MOD_NAME,
        help=f"MOD 名称 (默认: {DEFAULT_MOD_NAME})",
    )
    parser.add_argument(
        "--clean", action="store_true",
        help="导出前清空输出目录",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.project):
        print(f"错误: 找不到项目文件 {args.project}")
        sys.exit(1)

    # ── 1. 加载项目 ──
    print(f"加载项目: {args.project}")
    state_mgr = StateManager()
    country_mgr = CountryManager()
    continent_mgr = ContinentManager()
    adjacency_mgr = AdjacencyManager()
    railway_mgr = RailwayManager()
    supply_mgr = SupplyNodeManager()
    adjacency_rule_mgr = AdjacencyRuleManager()
    strategic_region_mgr = StrategicRegionManager()

    tile_map, province_map, terrain_map, height_map, river_map, provincial_terrain, _tile_snapshot = \
        load_project(
            args.project,
            state_mgr, country_mgr,
            continent_mgr=continent_mgr,
            adjacency_mgr=adjacency_mgr,
            railway_mgr=railway_mgr,
            supply_mgr=supply_mgr,
            adjacency_rule_mgr=adjacency_rule_mgr,
            strategic_region_mgr=strategic_region_mgr,
        )

    H, W = tile_map.shape
    pcount = int(province_map.max())
    land_pixels = int(np.sum(tile_map == TILE_LAND))
    sea_pixels = int(np.sum(tile_map == TILE_SEA))
    print(f"地图: {W}x{H}, 省份: {pcount}, 陆地: {land_pixels:,}, 海洋: {sea_pixels:,}")

    # ── 2. 同步地形 ──
    ocean_idx = TERRAIN_PALETTE_INDEX["ocean"]
    plains_idx = TERRAIN_PALETTE_INDEX["plains"]
    land_mask = tile_map == TILE_LAND
    bad_land = land_mask & (terrain_map == ocean_idx)
    bad_count = int(np.sum(bad_land))
    if bad_count > 0:
        terrain_map[bad_land] = plains_idx
        print(f"修正: {bad_count:,} 个陆地像素的地形 ocean→plains")

    sea_mask = tile_map == TILE_SEA
    sea_bad = sea_mask & (terrain_map != ocean_idx)
    sea_bad_count = int(np.sum(sea_bad))
    if sea_bad_count > 0:
        terrain_map[sea_bad] = ocean_idx
        print(f"修正: {sea_bad_count:,} 个海洋像素的地形→ocean")

    # ── 3. 自动生成高度图 ──
    if height_map is not None and land_mask.any():
        land_heights = height_map[land_mask]
        if np.all(land_heights == land_heights[0]):
            print("高度未调整，自动生成...")
            from services.terrain_service import auto_height
            height_map = auto_height(tile_map)

    # ── 4. 自动生成 State ──
    if not state_mgr.states:
        print("没有 State，自动生成...")
        state_mgr.auto_split(province_map, tile_map, per_state=20)
        print(f"自动生成 State: {len(state_mgr.states)}")
    else:
        print(f"已有 State: {len(state_mgr.states)}")

    # ── 5. 自动创建国家 ──
    if not country_mgr.countries:
        print("没有国家，自动创建测试国家...")
        c = country_mgr.create_country("AAA", "Aurora", (60, 130, 220))
        c.ruling_party = "democratic"
        c.popularities = {
            "democratic": 60, "fascism": 10,
            "communism": 10, "neutrality": 20,
        }
        for sid in state_mgr.states:
            country_mgr.assign_state(sid, "AAA")
            state = state_mgr.get_state(sid)
            if state:
                state.owner_tag = "AAA"
        first_state = state_mgr.get_state(1)
        if first_state and first_state.provinces:
            c.capital = first_state.provinces[0]
        print(f"创建国家 AAA, {len(state_mgr.states)} states")
    else:
        print(f"已有国家: {list(country_mgr.countries.keys())}")

    # ── 6. 导出前检查 & 填充默认数据 ──
    from services.export_service import pre_export_check_and_fix, fill_default_state_data
    report = pre_export_check_and_fix(
        tile_map, province_map, terrain_map,
        state_mgr, country_mgr, continent_mgr,
        strategic_region_mgr=strategic_region_mgr,
    )
    if report.fixed:
        print("\n── 自动修复 ──")
        for f in report.fixed:
            print(f"  [已修复] {f}")
    if report.warnings:
        print("\n── 警告 ──")
        for w in report.warnings:
            print(f"  [警告] {w}")

    filled = fill_default_state_data(state_mgr, terrain_map, province_map, tile_map)
    if filled > 0:
        print(f"为 {filled} 个 State 填充了默认资源/建筑")

    # ── 7. 清理旧 MOD ──
    if args.clean and os.path.exists(args.output_dir):
        shutil.rmtree(args.output_dir, ignore_errors=True)
        # Windows 上 rmtree 有延迟，等目录确实消失
        import time
        for _ in range(50):
            if not os.path.exists(args.output_dir):
                break
            time.sleep(0.1)
        print(f"已清空: {args.output_dir}")
    os.makedirs(args.output_dir, exist_ok=True)

    # ── 8. 导出 ──
    print(f"\n导出到: {args.output_dir}")
    export_full_mod(
        tile_map=tile_map,
        province_map=province_map,
        output_dir=args.output_dir,
        mod_name=args.mod_name,
        tag="AAA",
        state_mgr=state_mgr,
        country_mgr=country_mgr,
        terrain_map=terrain_map,
        height_map=height_map,
        river_map=river_map,
        continent_mgr=continent_mgr,
        adjacency_mgr=adjacency_mgr,
        railway_mgr=railway_mgr,
        supply_mgr=supply_mgr,
        adjacency_rule_mgr=adjacency_rule_mgr,
        strategic_region_mgr=strategic_region_mgr,
        provincial_terrain=provincial_terrain,
    )

    file_count = sum(len(files) for _, _, files in os.walk(args.output_dir))
    print(f"\n[OK] {args.mod_name} 导出完成: {file_count} 个文件")
    print(f"省份: {pcount}, State: {len(state_mgr.states)}, "
          f"国家: {len(country_mgr.countries)}")

    # ── 9. 导出验证 ──
    print("\n── 导出验证 ──")
    critical_files = [
        "map/default.map", "map/provinces.bmp", "map/definition.csv",
        "map/terrain.bmp", "map/heightmap.bmp", "map/rivers.bmp",
        "map/buildings.txt", "map/positions.txt", "map/adjacencies.csv",
        "map/supply_nodes.txt", "map/railways.txt", "map/continent.txt",
        "descriptor.mod",
    ]
    missing = []
    for f in critical_files:
        path = os.path.join(args.output_dir, f)
        if os.path.exists(path):
            size = os.path.getsize(path)
            if size == 0:
                print(f"  [空文件!] {f}")
                missing.append(f)
            else:
                print(f"  [OK] {f} ({size:,} bytes)")
        else:
            print(f"  [缺失!] {f}")
            missing.append(f)

    # 检查目录
    for d in ["history/states", "history/countries", "common/country_tags"]:
        dp = os.path.join(args.output_dir, d)
        if os.path.isdir(dp):
            count = len(os.listdir(dp))
            print(f"  [OK] {d}/ ({count} 个文件)")
        else:
            print(f"  [缺失!] {d}/")
            missing.append(d)

    # .mod 启动器文件
    mod_file = args.output_dir + ".mod"
    if os.path.exists(mod_file):
        print(f"  [OK] {os.path.basename(mod_file)}")
    else:
        print(f"  [缺失!] {os.path.basename(mod_file)}")
        missing.append(mod_file)

    if missing:
        print(f"\n[警告] {len(missing)} 个关键文件缺失或为空!")
    else:
        print("\n[验证通过] 所有关键文件完整，可以进游戏测试。")


if __name__ == "__main__":
    main()
