"""
渐进式测试导出器 — 从最小地图到完整MOD，逐级排查崩溃原因

策略：能从原版复制的文件就复制，只生成必须自定义的文件。
这样最大程度减少格式错误的可能性。

Lv1: 纯地图文件（BMP + definition.csv + 配置文件）
Lv2: +State +1个国家 +补给 +战略区域
Lv3: +2个国家 +bookmark
Lv4: +意识形态 +state_category +replace_path
"""
import os
import shutil
import struct
import numpy as np
from scipy.ndimage import gaussian_filter

from data.constants import (
    MAP_WIDTH, MAP_HEIGHT,
    TILE_LAND, TILE_SEA, TILE_LAKE,
    OCEAN_HEIGHT, LAND_BASE_HEIGHT, SEA_LEVEL,
    DEFAULT_HOI4_PATH, REPLACE_PATHS,
)
from data.terrain_types import TERRAIN_PALETTE_INDEX, DEFAULT_TERRAIN_FOR_TILE
from domain.generators.province import generate_provinces, generate_province_colors
from domain.validators.province import get_coastal_provinces
from export.bmp_writer import (
    write_provinces_bmp, write_heightmap_bmp,
    write_terrain_bmp, write_rivers_bmp, write_trees_bmp,
)

# 原版地图目录
VANILLA_MAP = os.path.join(DEFAULT_HOI4_PATH, "map")


def export_test_mod(output_dir: str, level: int = 1) -> None:
    """渐进式导出测试MOD。"""
    # ── 生成测试地图数据 ──
    tile_map = np.full((MAP_HEIGHT, MAP_WIDTH), TILE_SEA, dtype=np.uint8)
    tile_map[400:1600, 500:4500] = TILE_LAND
    tile_map[800:900, 2000:2300] = TILE_LAKE

    province_map, province_count = generate_provinces(tile_map, 100)
    colors = generate_province_colors(province_count)

    # 高度图
    hm = np.full((MAP_HEIGHT, MAP_WIDTH), OCEAN_HEIGHT, dtype=np.float32)
    hm[tile_map == TILE_LAND] = LAND_BASE_HEIGHT
    hm[tile_map == TILE_LAKE] = SEA_LEVEL - 5
    hm = gaussian_filter(hm, sigma=6)
    hm[tile_map == TILE_SEA] = np.minimum(hm[tile_map == TILE_SEA], SEA_LEVEL - 1)
    hm[tile_map == TILE_LAND] = np.maximum(hm[tile_map == TILE_LAND], SEA_LEVEL + 1)
    heightmap = np.clip(hm, 0, 255).astype(np.uint8)

    # 地形图
    terrain_map = np.zeros((MAP_HEIGHT, MAP_WIDTH), dtype=np.uint8)
    for tile_type, terrain_name in DEFAULT_TERRAIN_FOR_TILE.items():
        terrain_map[tile_map == tile_type] = TERRAIN_PALETTE_INDEX[terrain_name]

    # 分类省份
    land_ids, sea_ids, lake_ids = _classify_provinces(province_count, province_map, tile_map)

    # ── Lv1: 最小完整MOD（地图+State+1国家+补给+战略区域+基本replace_path）──
    _write_map_files(
        output_dir, province_map, colors, province_count,
        heightmap, terrain_map, tile_map,
        land_ids, sea_ids, lake_ids,
    )

    states = _auto_split_states(sorted(land_ids), province_map)
    _write_states(states, "AAA", output_dir)
    _write_country("AAA", "TestNation", (200, 80, 80),
                    min(land_ids) if land_ids else 1, output_dir)
    _write_supply(states, province_map, output_dir)
    _write_strategic_regions(province_count, output_dir)
    _write_localisation_lv1(states, output_dir)

    if level >= 2:
        _write_country("BBB", "TestRepublic", (80, 80, 200),
                        max(land_ids) if land_ids else 1, output_dir, append_tag=True)
        _write_bookmark(["AAA", "BBB"], output_dir)
        _write_localisation_lv2(output_dir)

    if level >= 3:
        _write_ideologies(output_dir)
        _write_state_categories(output_dir)

    if level >= 4:
        for p in REPLACE_PATHS:
            os.makedirs(os.path.join(output_dir, p), exist_ok=True)

    # 确保所有 replace_path 指向的目录都存在（即使为空）
    _write_descriptor(output_dir, level)
    _create_replace_dirs(output_dir, level)


# ════════════════════════════════════════════════════════════
#  Lv1: 地图文件
# ════════════════════════════════════════════════════════════

def _write_map_files(output_dir, province_map, colors, province_count,
                     heightmap, terrain_map, tile_map,
                     land_ids, sea_ids, lake_ids):
    """写入 map/ 下所有基础文件 — 能复制原版的就复制"""
    map_dir = os.path.join(output_dir, "map")
    os.makedirs(map_dir, exist_ok=True)

    # === 必须自己生成的 BMP ===
    write_provinces_bmp(province_map, output_dir, colors)
    write_heightmap_bmp(heightmap, output_dir)
    write_terrain_bmp(terrain_map, output_dir)  # 会优先复制原版头+调色板
    write_rivers_bmp(output_dir, river_map=None)  # 空河流
    write_trees_bmp(output_dir)

    # world_normal.bmp — 自己生成
    _write_normal_map(heightmap, output_dir)

    # === definition.csv — 必须自己生成 ===
    coastal = get_coastal_provinces(tile_map, province_map)
    with open(os.path.join(map_dir, "definition.csv"), "w", encoding="utf-8") as f:
        f.write("0;0;0;0;sea;false;ocean;0\n")
        for pid in range(1, province_count + 1):
            r, g, b = colors.get(pid, (1, 1, 1))
            if pid in land_ids:
                ptype, terrain, cont = "land", "plains", 1
                c = "true" if pid in coastal else "false"
            elif pid in lake_ids:
                ptype, terrain, cont = "lake", "lakes", 0
                c = "false"
            else:
                ptype, terrain, cont = "sea", "ocean", 0
                c = "false"
            f.write(f"{pid};{r};{g};{b};{ptype};{c};{terrain};{cont}\n")

    # === default.map — 必须自己生成 ===
    with open(os.path.join(map_dir, "default.map"), "w", encoding="utf-8") as f:
        f.write('definitions = "definition.csv"\n')
        f.write('provinces = "provinces.bmp"\n')
        f.write('positions = "positions.txt"\n')
        f.write('terrain = "terrain.bmp"\n')
        f.write('rivers = "rivers.bmp"\n')
        f.write('heightmap = "heightmap.bmp"\n')
        f.write('tree_definition = "trees.bmp"\n')
        f.write('continent = "continent.txt"\n')
        f.write('adjacency_rules = "adjacency_rules.txt"\n')
        f.write('adjacencies = "adjacencies.csv"\n')
        f.write('ambient_object = "ambient_object.txt"\n')
        f.write('seasons = "seasons.txt"\n\n')
        f.write('tree = { 3 4 7 10 }\n')

    # === 从原版复制的文件（格式最保险）===
    _copy_vanilla("seasons.txt", map_dir)
    _copy_vanilla("adjacency_rules.txt", map_dir)
    _copy_vanilla("ambient_object.txt", map_dir)

    # continent.txt — 自己生成（简化为1个大陆）
    with open(os.path.join(map_dir, "continent.txt"), "w", encoding="utf-8") as f:
        f.write("continents = {\n\teurope\n}\n")

    # adjacencies.csv — 空但格式正确
    with open(os.path.join(map_dir, "adjacencies.csv"), "w", encoding="utf-8") as f:
        f.write("From;To;Type;Through;start_x;start_y;stop_x;stop_y;adjacency_rule_name;Comment\n")
        f.write(";;;;;;;;;\n")

    # 空文件（原版也有但可以为空）
    for name in ["weatherpositions.txt", "unitstacks.txt", "rocket_sites.txt"]:
        open(os.path.join(map_dir, name), "w").close()

    # positions.txt — 原版是空文件(0字节)
    open(os.path.join(map_dir, "positions.txt"), "w").close()

    # supply 文件 — Lv1 也需要存在（wiki说不编辑会崩溃）
    with open(os.path.join(map_dir, "supply_nodes.txt"), "w", encoding="utf-8") as f:
        f.write(f"1 {min(land_ids) if land_ids else 1}\n")
    with open(os.path.join(map_dir, "railways.txt"), "w", encoding="utf-8") as f:
        land_sorted = sorted(land_ids)
        if len(land_sorted) >= 2:
            f.write(f"1 2 {land_sorted[0]} {land_sorted[1]}\n")
        else:
            f.write(f"1 1 {land_sorted[0] if land_sorted else 1}\n")
    with open(os.path.join(map_dir, "buildings.txt"), "w", encoding="utf-8") as f:
        f.write("1;infrastructure;500.00;11.00;1000.00;0.00;0\n")


def _copy_vanilla(filename: str, dest_dir: str) -> bool:
    """从原版 map/ 复制文件，如果原版不存在则创建空文件"""
    src = os.path.join(VANILLA_MAP, filename)
    dst = os.path.join(dest_dir, filename)
    if os.path.exists(src):
        shutil.copy2(src, dst)
        return True
    open(dst, "w").close()
    return False


# ════════════════════════════════════════════════════════════
#  Lv2: State + 国家 + 补给 + 战略区域
# ════════════════════════════════════════════════════════════

def _auto_split_states(land_ids_sorted, province_map, per_state=15):
    if not land_ids_sorted:
        return {}
    ids = list(land_ids_sorted)
    states = {}
    for i in range(0, len(ids), per_state):
        sid = i // per_state + 1
        states[sid] = ids[i:i + per_state]
    return states


def _write_states(states, tag, output_dir):
    d = os.path.join(output_dir, "history", "states")
    os.makedirs(d, exist_ok=True)
    for sid, provs in states.items():
        if not provs:
            continue
        with open(os.path.join(d, f"{sid}-STATE_{sid}.txt"), "w", encoding="utf-8") as f:
            f.write("state = {\n")
            f.write(f"\tid = {sid}\n")
            f.write(f'\tname = "STATE_WT_{sid}"\n')
            f.write(f"\tmanpower = {len(provs) * 50000}\n")
            f.write("\tstate_category = town\n\n")
            f.write("\thistory = {\n")
            f.write(f"\t\towner = {tag}\n")
            f.write(f"\t\tadd_core_of = {tag}\n")
            f.write("\t\tbuildings = {\n\t\t\tinfrastructure = 1\n\t\t}\n")
            f.write(f"\t\tvictory_points = {{ {provs[0]} 1 }}\n")
            f.write("\t}\n\n")
            f.write("\tprovinces = {\n")
            f.write("\t\t" + " ".join(str(p) for p in provs) + "\n")
            f.write("\t}\n}\n")


def _write_country(tag, name, color, capital, output_dir, append_tag=False):
    os.makedirs(os.path.join(output_dir, "common", "country_tags"), exist_ok=True)
    os.makedirs(os.path.join(output_dir, "common", "countries"), exist_ok=True)
    os.makedirs(os.path.join(output_dir, "history", "countries"), exist_ok=True)
    os.makedirs(os.path.join(output_dir, "history", "units"), exist_ok=True)

    mode = "a" if append_tag else "w"
    with open(os.path.join(output_dir, "common", "country_tags", "00_countries.txt"), mode) as f:
        f.write(f'{tag} = "countries/{tag}.txt"\n')

    r, g, b = color
    with open(os.path.join(output_dir, "common", "countries", f"{tag}.txt"), "w", encoding="utf-8") as f:
        f.write("graphical_culture = western_european_gfx\n")
        f.write("graphical_culture_2d = western_european_2d\n")
        f.write(f"color = {{ {r} {g} {b} }}\n")

    with open(os.path.join(output_dir, "history", "countries", f"{tag} - {name}.txt"), "w", encoding="utf-8") as f:
        f.write(f"capital = {capital}\n")
        f.write(f'oob = "{tag}_1936"\n')
        f.write("set_research_slots = 3\n")
        f.write("set_politics = {\n\truling_party = neutrality\n")
        f.write('\tlast_election = "1932.1.1"\n\telection_frequency = 48\n')
        f.write("\telections_allowed = no\n}\n")
        f.write("set_popularities = {\n\tdemocratic = 10\n\tfascism = 5\n")
        f.write("\tcommunism = 5\n\tneutrality = 80\n}\n\n")

    with open(os.path.join(output_dir, "history", "units", f"{tag}_1936.txt"), "w", encoding="utf-8") as f:
        f.write("units = { }\n\n")


def _write_supply(states, province_map, output_dir):
    d = os.path.join(output_dir, "map")
    nodes = []
    state_list = [(sid, provs) for sid, provs in states.items() if provs]
    with open(os.path.join(d, "supply_nodes.txt"), "w", encoding="utf-8") as f:
        for i, (sid, provs) in enumerate(state_list):
            if i % 5 == 0:
                f.write(f"1 {provs[0]}\n")
                nodes.append(provs[0])

    with open(os.path.join(d, "railways.txt"), "w", encoding="utf-8") as f:
        for i in range(len(nodes) - 1):
            f.write(f"1 2 {nodes[i]} {nodes[i+1]}\n")
        if len(nodes) < 2:
            f.write(f"1 1 {nodes[0] if nodes else 1}\n")

    # buildings.txt — 每个State一个建筑
    flat_pm = province_map.ravel()
    n = int(province_map.max()) + 1
    pid_count = np.bincount(flat_pm, minlength=n)
    ys, xs = np.mgrid[0:MAP_HEIGHT, 0:MAP_WIDTH]
    sum_y = np.bincount(flat_pm, weights=ys.ravel().astype(np.float64), minlength=n)
    sum_x = np.bincount(flat_pm, weights=xs.ravel().astype(np.float64), minlength=n)

    with open(os.path.join(d, "buildings.txt"), "w", encoding="utf-8") as f:
        for sid, provs in states.items():
            if not provs:
                continue
            pid = provs[0]
            if pid >= n or pid_count[pid] == 0:
                continue
            cx = sum_x[pid] / pid_count[pid]
            cy = sum_y[pid] / pid_count[pid]
            f.write(f"{sid};infrastructure;{cx:.2f};11.00;{cy:.2f};0.00;0\n")

    # supplyareas
    sa_dir = os.path.join(d, "supplyareas")
    os.makedirs(sa_dir, exist_ok=True)
    with open(os.path.join(sa_dir, "1-SupplyArea.txt"), "w", encoding="utf-8") as f:
        f.write("supply_area={\n\tid=1\n")
        f.write('\tname="SUPPLYAREA_WT_1"\n\tvalue=5\n')
        f.write("\tstates={\n\t\t" + " ".join(str(s) for s in states) + "\n\t}\n}\n")


def _write_strategic_regions(province_count, output_dir):
    """单一战略区域包含所有省份"""
    d = os.path.join(output_dir, "map", "strategicregions")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "1-strategic_region.txt"), "w", encoding="utf-8") as f:
        f.write("strategic_region={\n")
        f.write("\tid=1\n")
        f.write('\tname="STRATEGICREGION_WT_1"\n')
        f.write("\tprovinces={\n\t\t")
        f.write(" ".join(str(p) for p in range(1, province_count + 1)))
        f.write("\n\t}\n")
        f.write("\tweather={\n\t\tperiod={\n")
        f.write("\t\t\tbetween={ 0.0 30.0 }\n")
        f.write("\t\t\ttemperature={ -5.0 25.0 }\n")
        f.write("\t\t\tno_phenomenon=0.500\n")
        f.write("\t\t\train_light=0.200\n")
        f.write("\t\t\train_heavy=0.100\n")
        f.write("\t\t\tmud=0.050\n")
        f.write("\t\t\tblizzard=0.050\n")
        f.write("\t\t\tsandstorm=0.000\n")
        f.write("\t\t\tsnow=0.100\n")
        f.write("\t\t}\n\t}\n}\n")


# ════════════════════════════════════════════════════════════
#  Lv3: Bookmark
# ════════════════════════════════════════════════════════════

def _write_bookmark(tags, output_dir):
    d = os.path.join(output_dir, "common", "bookmarks")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "the_gathering_storm.txt"), "w", encoding="utf-8") as f:
        f.write("bookmarks = {\n\tbookmark = {\n")
        f.write('\t\tname = FANTASY_BOOKMARK\n')
        f.write('\t\tdesc = FANTASY_BOOKMARK_DESC\n')
        f.write('\t\tdate = 1936.1.1.12\n')
        f.write('\t\tpicture = GFX_select_date_1936\n')
        f.write(f'\t\tdefault_country = "{tags[0]}"\n')
        f.write("\t\tdefault = yes\n\n")
        for i, tag in enumerate(tags):
            f.write(f'\t\t"{tag}" = {{\n')
            f.write(f'\t\t\thistory = "{tag}_BOOKMARK_DESC"\n')
            f.write('\t\t\tideology = neutrality\n')
            if i > 0:
                f.write('\t\t\tminor = yes\n')
            f.write('\t\t}\n')
        f.write('\t\t"---" = {\n\t\t\thistory = OTHER_BOOKMARK_DESC\n\t\t}\n')
        f.write('\t\teffect = {\n\t\t\trandomize_weather = 22345\n\t\t}\n')
        f.write("\t}\n}\n")


# ════════════════════════════════════════════════════════════
#  Lv4: 意识形态 + State类别 + replace_path
# ════════════════════════════════════════════════════════════

def _write_ideologies(output_dir):
    d = os.path.join(output_dir, "common", "ideologies")
    os.makedirs(d, exist_ok=True)
    # 最保险：从原版复制再修改
    vanilla = os.path.join(DEFAULT_HOI4_PATH, "common", "ideologies", "00_ideologies.txt")
    if os.path.exists(vanilla):
        shutil.copy2(vanilla, os.path.join(d, "00_ideologies.txt"))
        return
    # 回退：自己生成
    ideologies = [
        ("democratic", "{ 0 0 200 }", ["conservatism", "liberalism", "socialism"],
         "ai_democratic", "0.25", "0.1"),
        ("fascism", "{ 169 68 66 }", ["fascism_ideology", "nazism", "falangism"],
         "ai_fascist", "0.8", "0.5"),
        ("communism", "{ 200 0 0 }", ["marxism", "leninism", "stalinism"],
         "ai_communist", "0.8", "0.5"),
        ("neutrality", "{ 125 127 126 }", ["despotism", "oligarchism", "moderatism", "centrism"],
         "ai_neutral", "1.0", "0.5"),
    ]
    with open(os.path.join(d, "00_ideologies.txt"), "w", encoding="utf-8") as f:
        f.write("ideologies = {\n\n")
        for name, color, subtypes, ai_flag, war_t, fac_t in ideologies:
            f.write(f"\t{name} = {{\n\n\t\ttypes = {{\n")
            for st in subtypes:
                f.write(f"\t\t\t{st} = {{\n\t\t\t}}\n")
            f.write(f"\t\t}}\n\n\t\tcolor = {color}\n\n")
            f.write(f"\t\trules = {{\n\t\t\tcan_create_factions = yes\n\t\t}}\n\n")
            f.write(f"\t\twar_impact_on_world_tension = {war_t}\n")
            f.write(f"\t\tfaction_impact_on_world_tension = {fac_t}\n\n")
            f.write(f"\t\tmodifiers = {{\n\t\t}}\n\n")
            f.write(f"\t\t{ai_flag} = yes\n\t\tcan_be_boosted = yes\n\t}}\n\n")
        f.write("}\n")


def _write_state_categories(output_dir):
    d = os.path.join(output_dir, "common", "state_category")
    os.makedirs(d, exist_ok=True)
    # 从原版复制所有文件
    vanilla_dir = os.path.join(DEFAULT_HOI4_PATH, "common", "state_category")
    if os.path.isdir(vanilla_dir):
        for fn in os.listdir(vanilla_dir):
            if fn.endswith(".txt"):
                shutil.copy2(os.path.join(vanilla_dir, fn), os.path.join(d, fn))
        return
    # 回退
    categories = [
        ("wasteland", 0, (40, 40, 40)), ("pastoral", 1, (160, 160, 0)),
        ("tiny", 1, (180, 180, 0)), ("small", 2, (190, 190, 0)),
        ("town", 4, (200, 200, 0)), ("large_town", 5, (150, 200, 0)),
        ("city", 6, (0, 200, 0)), ("large_city", 8, (0, 150, 0)),
        ("megalopolis", 10, (0, 100, 0)),
    ]
    for name, slots, (cr, cg, cb) in categories:
        with open(os.path.join(d, f"{name}.txt"), "w", encoding="utf-8") as f:
            f.write(f"state_categories={{\n\t{name} = {{\n")
            f.write(f"\t\tlocal_building_slots = {slots}\n")
            f.write(f"\t\tcolor = {{ {cr} {cg} {cb} }}\n\t}}\n}}\n")


# ════════════════════════════════════════════════════════════
#  本地化
# ════════════════════════════════════════════════════════════

def _write_localisation_lv1(states, output_dir):
    d = os.path.join(output_dir, "localisation")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "test_l_english.yml"), "w", encoding="utf-8-sig") as f:
        f.write("l_english:\n")
        for sid in states:
            f.write(f' STATE_WT_{sid}:0 "State {sid}"\n')
        f.write(' STRATEGICREGION_WT_1:0 "Region 1"\n')
        f.write(' SUPPLYAREA_WT_1:0 "Supply Area"\n')
        f.write(' AAA:0 "Test Nation"\n')
        f.write(' AAA_DEF:0 "Test Nation"\n')
        f.write(' AAA_ADJ:0 "Tester"\n')


def _write_localisation_lv2(output_dir):
    d = os.path.join(output_dir, "localisation")
    with open(os.path.join(d, "test_l_english.yml"), "a", encoding="utf-8") as f:
        f.write(' BBB:0 "Test Republic"\n')
        f.write(' BBB_DEF:0 "Test Republic"\n')
        f.write(' BBB_ADJ:0 "Republican"\n')
        f.write(' AAA_BOOKMARK_DESC:0 "Play as Test Nation"\n')
        f.write(' BBB_BOOKMARK_DESC:0 "Play as Test Republic"\n')
        f.write(' FANTASY_BOOKMARK:0 "Fantasy World"\n')
        f.write(' FANTASY_BOOKMARK_DESC:0 "A test world."\n')
        f.write(' OTHER_BOOKMARK_DESC:0 "Other nations"\n')


# ════════════════════════════════════════════════════════════
#  descriptor.mod
# ════════════════════════════════════════════════════════════

def _write_descriptor(output_dir, level):
    # 自定义地图必须替换的目录（否则原版State/国家引用不存在的省份ID会崩溃）
    essential_rp = [
        "history/countries", "history/states", "history/units", "history/general",
        "map/strategicregions", "map/supplyareas",
        "common/countries", "common/country_tags",
        "common/bookmarks",  # 原版bookmark引用不存在的国家TAG
    ]
    if level >= 3:
        essential_rp.extend(["common/ideologies", "common/state_category"])
    if level >= 4:
        essential_rp.extend([p for p in REPLACE_PATHS if p not in essential_rp])

    rp = "\n".join(f'replace_path="{p}"' for p in essential_rp) + "\n"
    from services.game_assets import resolve_supported_version
    supported = resolve_supported_version()

    with open(os.path.join(output_dir, "descriptor.mod"), "w", encoding="utf-8") as f:
        f.write(f'version="0.1"\n')
        f.write('tags={\n\t"Alternative History"\n\t"Map"\n\t"Total Conversion"\n}\n')
        f.write(f'name="TestMOD_Lv{level}"\n')
        f.write(f'supported_version="{supported}"\n')
        if rp:
            f.write(rp)

    mod_dir_name = os.path.basename(output_dir)
    outer_mod = os.path.join(os.path.dirname(output_dir), f"{mod_dir_name}.mod")
    with open(outer_mod, "w", encoding="utf-8") as f:
        f.write(f'version="0.1"\n')
        f.write('tags={\n\t"Alternative History"\n\t"Map"\n\t"Total Conversion"\n}\n')
        f.write(f'name="TestMOD_Lv{level}"\n')
        if rp:
            f.write(rp)
        f.write(f'supported_version="{supported}"\n')
        abs_path = os.path.abspath(output_dir).replace("\\", "/")
        f.write(f'path="{abs_path}"\n')


# ════════════════════════════════════════════════════════════
#  辅助函数
# ════════════════════════════════════════════════════════════

def _create_replace_dirs(output_dir, level):
    """确保 descriptor 里声明的所有 replace_path 目录都存在"""
    essential = [
        "history/countries", "history/states", "history/units", "history/general",
        "map/strategicregions", "map/supplyareas",
        "common/countries", "common/country_tags", "common/bookmarks",
    ]
    if level >= 3:
        essential.extend(["common/ideologies", "common/state_category"])
    if level >= 4:
        essential.extend(REPLACE_PATHS)
    for p in essential:
        os.makedirs(os.path.join(output_dir, p), exist_ok=True)


def _classify_provinces(province_count, province_map, tile_map):
    flat_pm = province_map.ravel()
    flat_tm = tile_map.ravel()
    n = province_count + 1
    land_c = np.bincount(flat_pm, weights=(flat_tm == TILE_LAND), minlength=n)
    sea_c = np.bincount(flat_pm, weights=(flat_tm == TILE_SEA), minlength=n)
    lake_c = np.bincount(flat_pm, weights=(flat_tm == TILE_LAKE), minlength=n)
    land_ids, sea_ids, lake_ids = set(), set(), set()
    for pid in range(1, province_count + 1):
        l, s, k = land_c[pid], sea_c[pid], lake_c[pid]
        if l >= s and l >= k:
            land_ids.add(pid)
        elif k > s:
            lake_ids.add(pid)
        else:
            sea_ids.add(pid)
    return land_ids, sea_ids, lake_ids


def _write_normal_map(hm, output_dir):
    from scipy.ndimage import sobel
    d = os.path.join(output_dir, "map")
    os.makedirs(d, exist_ok=True)
    h = hm.astype(np.float32) / 255.0
    dx = sobel(h, axis=1)
    dy = -sobel(h, axis=0)
    nx, ny, nz = -dx, -dy, np.ones_like(h)
    length = np.sqrt(nx**2 + ny**2 + nz**2)
    length[length == 0] = 1
    nx /= length; ny /= length; nz /= length
    r = ((nx + 1) / 2 * 255).clip(0, 255).astype(np.uint8)
    g = ((ny + 1) / 2 * 255).clip(0, 255).astype(np.uint8)
    b = ((nz + 1) / 2 * 255).clip(0, 255).astype(np.uint8)

    row = MAP_WIDTH * 3
    pad = (4 - (row % 4)) % 4
    pix = (row + pad) * MAP_HEIGHT
    with open(os.path.join(d, "world_normal.bmp"), "wb") as f:
        f.write(b"BM")
        f.write(struct.pack("<I", 54 + pix))
        f.write(struct.pack("<HH", 0, 0))
        f.write(struct.pack("<I", 54))
        f.write(struct.pack("<I", 40))
        f.write(struct.pack("<ii", MAP_WIDTH, MAP_HEIGHT))
        f.write(struct.pack("<HH", 1, 24))
        f.write(struct.pack("<I", 0))
        f.write(struct.pack("<I", pix))
        f.write(struct.pack("<ii", 2835, 2835))
        f.write(struct.pack("<II", 0, 0))
        pb = b"\x00" * pad
        for y in range(MAP_HEIGHT - 1, -1, -1):
            f.write(np.stack([b[y], g[y], r[y]], axis=1).tobytes())
            if pad:
                f.write(pb)
