"""
CSV / 文本文件写入器 — 生成 definition.csv 和其他地图配置文件
"""
import os
import numpy as np

from data.constants import (
    MAP_WIDTH, MAP_HEIGHT,
    TILE_LAND, TILE_SEA, TILE_LAKE,
    TILE_TYPE_NAMES,
    DEFAULT_MOD_NAME, DEFAULT_MOD_VERSION,
)
from data.terrain_types import DEFAULT_TERRAIN_FOR_TILE
from domain.validators.province import get_coastal_provinces
from domain.generators.province import generate_province_colors

_FALLBACK_SEASONS = """
winter = { start_date=00.12.01 end_date=00.02.10
    hsv_north={ 0 0.1 1 } colorbalance_north={ 0.9 0.9 1 }
    hsv_center={ 0.0 1.0 1.0 } colorbalance_center={ 1.0 1.0 1.0 }
    hsv_south={ 0.0 1.0 1.0 } colorbalance_south={ 1.0 1.0 1.0 }
}
spring = { start_date=00.03.10 end_date=00.04.22
    hsv_north={ 0 0.1 1 } colorbalance_north={ 0.9 0.9 1 }
    hsv_center={ 0.0 1.0 1.0 } colorbalance_center={ 1.0 1.0 1.0 }
    hsv_south={ 0.0 1.0 1.0 } colorbalance_south={ 1.0 1.0 1.0 }
}
summer = { start_date=00.05.20 end_date=00.09.10
    hsv_north={ 0 0.1 1 } colorbalance_north={ 0.9 0.9 1 }
    hsv_center={ 0.0 1.0 1.0 } colorbalance_center={ 1.0 1.0 1.0 }
    hsv_south={ 0.0 1.0 1.0 } colorbalance_south={ 1.0 1.0 1.0 }
}
autumn = { start_date=00.10.10 end_date=00.10.31
    hsv_north={ 0 0.1 1 } colorbalance_north={ 0.9 0.9 1 }
    hsv_center={ 0.0 1.0 1.0 } colorbalance_center={ 1.0 1.0 1.0 }
    hsv_south={ 0.0 1.0 1.0 } colorbalance_south={ 1.0 1.0 1.0 }
}
"""


def write_definition_csv(
    province_map: np.ndarray,
    tile_map: np.ndarray,
    output_dir: str,
    colors: dict[int, tuple[int, int, int]] | None = None,
    continent_mgr=None,
    terrain_map: np.ndarray | None = None,
) -> None:
    """
    生成 definition.csv 文件。

    格式: 省份ID;R;G;B;类型;沿海;地形;大陆ID
    """
    map_dir = os.path.join(output_dir, "map")
    os.makedirs(map_dir, exist_ok=True)

    province_count = int(province_map.max())

    if colors is None:
        colors = generate_province_colors(province_count)

    # 获取沿海省份集合
    coastal_set = get_coastal_provinces(tile_map, province_map)

    # 判断每个省份的类型
    province_types = _get_province_types(province_map, tile_map)

    file_path = os.path.join(map_dir, "definition.csv")
    with open(file_path, "w", encoding="utf-8") as f:
        # 第一行：ID=0 特殊行（HOI4 要求，无表头）
        f.write("0;0;0;0;sea;false;ocean;0\n")

        for pid in range(1, province_count + 1):
            r, g, b = colors.get(pid, (1, 1, 1))
            ptype = province_types.get(pid, "land")

            # 沿海状态
            is_coastal = "true" if pid in coastal_set else "false"
            # 海洋和湖泊省份不标记为沿海
            if ptype in ("sea", "lake"):
                is_coastal = "false"

            # 地形：优先从 terrain_map 查实际 graphical terrain 的 type
            terrain = _resolve_terrain(ptype, pid, province_map, terrain_map)

            # 大陆ID：海洋/湖泊=0，陆地按 continent_mgr 指派（未指派则归 1 号大陆）
            is_land = ptype not in ("sea", "lake")
            if continent_mgr is not None:
                continent = continent_mgr.get_province_continent_hoi4_id(pid, is_land)
            else:
                continent = 0 if not is_land else 1

            f.write(f"{pid};{r};{g};{b};{ptype};{is_coastal};{terrain};{continent}\n")


def _get_province_types(
    province_map: np.ndarray,
    tile_map: np.ndarray,
) -> dict[int, str]:
    """
    判断每个省份的类型（land/sea/lake）。
    基于省份内占多数的地块类型决定。
    """
    province_count = int(province_map.max())
    types = {}

    for pid in range(1, province_count + 1):
        mask = province_map == pid
        if not np.any(mask):
            types[pid] = "land"
            continue

        tiles = tile_map[mask]
        land_count = int(np.sum(tiles == TILE_LAND))
        sea_count = int(np.sum(tiles == TILE_SEA))
        lake_count = int(np.sum(tiles == TILE_LAKE))

        if sea_count >= land_count and sea_count >= lake_count:
            types[pid] = "sea"
        elif lake_count >= land_count:
            types[pid] = "lake"
        else:
            types[pid] = "land"

    return types


def _default_terrain(province_type: str) -> str:
    """获取省份类型对应的默认地形"""
    if province_type == "sea":
        return "ocean"
    elif province_type == "lake":
        return "lakes"
    else:
        return "plains"


def _resolve_terrain(
    ptype: str,
    pid: int,
    province_map: np.ndarray,
    terrain_map: np.ndarray | None,
) -> str:
    """从 terrain_map 解析省份的 provincial terrain type."""
    # 海/湖强制
    if ptype == "sea":
        return "ocean"
    if ptype == "lake":
        return "lakes"

    if terrain_map is None:
        return "plains"

    from data.terrain_types import PALETTE_TO_TYPE

    # 取该省份区域内 terrain_map 的众数 (最多的那个索引)
    mask = province_map == pid
    indices = terrain_map[mask]
    if indices.size == 0:
        return "plains"

    counts = np.bincount(indices)
    dominant_index = int(counts.argmax())
    return PALETTE_TO_TYPE.get(dominant_index, "plains")


def write_adjacencies_csv(output_dir: str) -> None:
    """生成空的 adjacencies.csv（只有表头和结尾分号行）"""
    map_dir = os.path.join(output_dir, "map")
    os.makedirs(map_dir, exist_ok=True)

    file_path = os.path.join(map_dir, "adjacencies.csv")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("From;To;Type;Through;start_x;start_y;stop_x;stop_y;adjacency_rule_name;Comment\n")
        f.write(";;;;;;;;;\n")


def write_default_map(
    output_dir: str,
    province_map: np.ndarray,
    tile_map: np.ndarray,
) -> None:
    """
    生成 default.map 文件。
    """
    map_dir = os.path.join(output_dir, "map")
    os.makedirs(map_dir, exist_ok=True)

    province_count = int(province_map.max())

    # 收集海洋省份ID
    sea_ids = []
    lake_ids = []
    province_types = _get_province_types(province_map, tile_map)
    for pid, ptype in province_types.items():
        if ptype == "sea":
            sea_ids.append(pid)
        elif ptype == "lake":
            lake_ids.append(pid)

    file_path = os.path.join(map_dir, "default.map")
    with open(file_path, "w", encoding="utf-8") as f:
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
        f.write('seasons = "seasons.txt"\n')
        f.write('\ntree = { 3 4 7 10 }\n')


def write_continent_txt(output_dir: str) -> None:
    """生成 continent.txt"""
    map_dir = os.path.join(output_dir, "map")
    os.makedirs(map_dir, exist_ok=True)

    file_path = os.path.join(map_dir, "continent.txt")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("continents = {\n")
        f.write("\tfantasy_continent\n")
        f.write("}\n")


def write_empty_files(output_dir: str) -> None:
    """生成必须存在但可以为空的文件"""
    map_dir = os.path.join(output_dir, "map")
    os.makedirs(map_dir, exist_ok=True)

    # positions.txt — 空文件
    with open(os.path.join(map_dir, "positions.txt"), "w", encoding="utf-8") as f:
        pass

    # adjacency_rules.txt — 空文件
    with open(os.path.join(map_dir, "adjacency_rules.txt"), "w", encoding="utf-8") as f:
        pass

    # ambient_object.txt — 由 ambient_object writer 单独生成，这里不覆盖

    # seasons.txt — 从原版复制，如果没有则写最小可用内容
    vanilla_seasons = os.path.join(
        "G:/SteamLibrary/steamapps/common/Hearts of Iron IV/map/seasons.txt"
    )
    if os.path.exists(vanilla_seasons):
        import shutil
        shutil.copy2(vanilla_seasons, os.path.join(map_dir, "seasons.txt"))
    else:
        with open(os.path.join(map_dir, "seasons.txt"), "w", encoding="utf-8") as f:
            f.write(_FALLBACK_SEASONS)

    # weatherpositions.txt — 空文件
    with open(os.path.join(map_dir, "weatherpositions.txt"), "w", encoding="utf-8") as f:
        pass

    # unitstacks.txt — 空文件
    with open(os.path.join(map_dir, "unitstacks.txt"), "w", encoding="utf-8") as f:
        pass

    # rocket_sites.txt — 空文件
    with open(os.path.join(map_dir, "rocket_sites.txt"), "w", encoding="utf-8") as f:
        pass


def write_supply_files(output_dir: str, first_land_province: int) -> None:
    """
    生成 supply_nodes.txt 和 railways.txt（最小可用版本）。
    至少需要一个节点和一条铁路，否则游戏崩溃。
    """
    map_dir = os.path.join(output_dir, "map")
    os.makedirs(map_dir, exist_ok=True)

    # supply_nodes.txt — 至少一个等级1节点
    with open(os.path.join(map_dir, "supply_nodes.txt"), "w", encoding="utf-8") as f:
        f.write(f"1 {first_land_province}\n")

    # railways.txt — 至少一条等级1铁路
    # 格式: 等级 省份数量 省份ID1 省份ID2 ...
    # 需要至少两个省份，这里用同一个省份占位（最小可用）
    with open(os.path.join(map_dir, "railways.txt"), "w", encoding="utf-8") as f:
        f.write(f"1 2 {first_land_province} {first_land_province}\n")


def write_buildings_txt(output_dir: str, first_land_province: int) -> None:
    """
    生成 buildings.txt（最小可用版本）。
    """
    map_dir = os.path.join(output_dir, "map")
    os.makedirs(map_dir, exist_ok=True)

    with open(os.path.join(map_dir, "buildings.txt"), "w", encoding="utf-8") as f:
        # StateID;建筑类型;X;Y;Z;旋转;相邻海省ID
        # 注意：infrastructure 不是 3D 建筑，不能出现在 buildings.txt 里；用 bunker 占位
        f.write(f"1;bunker;100.0;10.0;100.0;0.0;0\n")


def write_strategic_region(
    output_dir: str,
    province_ids: list[int],
) -> None:
    """生成一个包含所有省份的战略区域"""
    sr_dir = os.path.join(output_dir, "map", "strategicregions")
    os.makedirs(sr_dir, exist_ok=True)

    file_path = os.path.join(sr_dir, "1-fantasy_region.txt")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("strategic_region = {\n")
        f.write("    id = 1\n")
        f.write('    name = "STRATEGICREGION_WT_1"\n')
        f.write("    provinces = {\n")
        # 每行最多 20 个ID
        for i in range(0, len(province_ids), 20):
            chunk = province_ids[i:i + 20]
            f.write("        " + " ".join(str(x) for x in chunk) + "\n")
        f.write("    }\n")
        f.write("    weather = {\n")
        f.write("        period = {\n")
        f.write("            between = { 0.0 30.0 }\n")
        f.write("            temperature = { -5.0 25.0 }\n")
        f.write("            no_phenomenon = 0.500\n")
        f.write("            rain_light = 0.200\n")
        f.write("            rain_heavy = 0.100\n")
        f.write("            mud = 0.050\n")
        f.write("            blizzard = 0.050\n")
        f.write("            sandstorm = 0.000\n")
        f.write("            snow = 0.100\n")
        f.write("        }\n")
        f.write("    }\n")
        f.write("}\n")


def write_state_file(
    output_dir: str,
    state_id: int,
    province_ids: list[int],
    owner_tag: str = "AAA",
    manpower: int = 100000,
) -> None:
    """生成一个 State 文件"""
    states_dir = os.path.join(output_dir, "history", "states")
    os.makedirs(states_dir, exist_ok=True)

    file_path = os.path.join(states_dir, f"{state_id}-STATE_{state_id}.txt")
    first_province = province_ids[0] if province_ids else 1

    with open(file_path, "w", encoding="utf-8") as f:
        f.write("state = {\n")
        f.write(f"    id = {state_id}\n")
        f.write(f'    name = "STATE_WT_{state_id}"\n')
        f.write(f"    manpower = {manpower}\n")
        f.write("    state_category = town\n\n")
        f.write("    history = {\n")
        f.write(f'        owner = {owner_tag}\n')
        f.write("        buildings = {\n")
        f.write("            infrastructure = 1\n")
        f.write("        }\n")
        f.write("        victory_points = {\n")
        f.write(f"            {first_province} 1\n")
        f.write("        }\n")
        f.write("    }\n\n")
        f.write("    provinces = {\n")
        f.write("        " + " ".join(str(x) for x in province_ids) + "\n")
        f.write("    }\n")
        f.write("}\n")


def write_country_files(output_dir: str, tag: str = "AAA") -> None:
    """生成最小可用的国家定义文件"""
    # country_tags
    tags_dir = os.path.join(output_dir, "common", "country_tags")
    os.makedirs(tags_dir, exist_ok=True)
    # 用 02_worldtest_ 前缀避免覆盖 vanilla 00_countries.txt（country_tags 不再 replace）
    with open(os.path.join(tags_dir, "02_worldtest_countries.txt"), "w", encoding="utf-8") as f:
        f.write(f'{tag} = "countries/{tag}.txt"\n')

    # country 文件
    countries_dir = os.path.join(output_dir, "common", "countries")
    os.makedirs(countries_dir, exist_ok=True)
    with open(os.path.join(countries_dir, f"{tag}.txt"), "w", encoding="utf-8") as f:
        f.write("graphical_culture = western_european_gfx\n")
        f.write("graphical_culture_2d = western_european_2d\n")
        f.write("color = { 100 100 200 }\n")

    # history 文件
    history_dir = os.path.join(output_dir, "history", "countries")
    os.makedirs(history_dir, exist_ok=True)
    with open(os.path.join(history_dir, f"{tag} - FantasyCountry.txt"), "w", encoding="utf-8") as f:
        f.write("capital = 1\n")
        f.write(f'oob = "{tag}_1936"\n')
        f.write("set_politics = {\n")
        f.write("    ruling_party = neutrality\n")
        f.write('    last_election = "1932.1.1"\n')
        f.write("    election_frequency = 48\n")
        f.write("    elections_allowed = no\n")
        f.write("}\n")
        f.write("set_popularities = {\n")
        f.write("    democratic = 10\n")
        f.write("    fascism = 5\n")
        f.write("    communism = 5\n")
        f.write("    neutrality = 80\n")
        f.write("}\n")

    # OOB（空的部队编制）
    oob_dir = os.path.join(output_dir, "history", "units")
    os.makedirs(oob_dir, exist_ok=True)
    with open(os.path.join(oob_dir, f"{tag}_1936.txt"), "w", encoding="utf-8") as f:
        f.write("units = { }\n")


def write_descriptor_mod(output_dir: str, mod_name: str = DEFAULT_MOD_NAME) -> None:
    """生成 descriptor.mod"""
    file_path = os.path.join(output_dir, "descriptor.mod")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(f'version="{DEFAULT_MOD_VERSION}"\n')
        f.write("tags={\n")
        f.write('    "Alternative History"\n')
        f.write('    "Map"\n')
        f.write('    "Total Conversion"\n')
        f.write("}\n")
        f.write(f'name="{mod_name}"\n')
        from services.game_assets import resolve_supported_version
        f.write(f'supported_version="{resolve_supported_version()}"\n')
        f.write('replace_path="map"\n')
        f.write('replace_path="map/strategicregions"\n')
        f.write('replace_path="map/supplyareas"\n')
        f.write('replace_path="history/countries"\n')
        f.write('replace_path="history/states"\n')
        f.write('replace_path="history/units"\n')
        f.write('replace_path="common/country_tags"\n')
        f.write('replace_path="common/countries"\n')
        f.write('replace_path="common/national_focus"\n')
        f.write('replace_path="common/characters"\n')
