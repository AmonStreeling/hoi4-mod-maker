"""
导入MOD地图 — 从 HOI4 mod/vanilla 目录读取地图图层。

读取 map/ 子目录下的:
- provinces.bmp (24-bit) → province_map + color→ID 映射
- definition.csv → tile_map (land/sea/lake) + provincial_terrain
- terrain.bmp (8-bit indexed) → terrain_map
- heightmap.bmp (8-bit grayscale) → height_map
- rivers.bmp (8-bit indexed) → river_map
"""

from __future__ import annotations

import csv
import os
import re
from typing import Any

import numpy as np
from PIL import Image

from data.constants import TILE_LAND, TILE_SEA, TILE_LAKE


# definition.csv 类型名 → 内部常量
_TYPE_MAP = {
    "land": TILE_LAND,
    "sea": TILE_SEA,
    "lake": TILE_LAKE,
}


def validate_mod_directory(mod_dir: str) -> list[str]:
    """检查目录结构，返回缺失文件列表。

    如果 MOD 没有 map/provinces.bmp，尝试从 vanilla 目录补。
    很多 MOD 不含地图文件（只改 history/common），这种情况用 vanilla 的地图。
    """
    from data.constants import DEFAULT_HOI4_PATH
    provinces_path = os.path.join(mod_dir, "map", "provinces.bmp")
    if not os.path.isfile(provinces_path):
        # 尝试 vanilla fallback
        vanilla_provinces = os.path.join(DEFAULT_HOI4_PATH, "map", "provinces.bmp")
        if os.path.isfile(vanilla_provinces):
            return [f"map/provinces.bmp 不在此 MOD 中（该 MOD 使用 vanilla 地图）。\n"
                    f"如需导入地图，请直接导入 vanilla 目录:\n{DEFAULT_HOI4_PATH}"]
        return ["map/provinces.bmp（该 MOD 和 vanilla 都找不到地图文件）"]
    return []


def _parse_definition_csv(csv_path: str) -> dict[tuple[int, int, int], dict[str, Any]]:
    """解析 definition.csv，返回 {(R,G,B): {id, type, terrain}} 映射。

    格式: ID;R;G;B;type;coastal;terrain;continent
    """
    color_info: dict[tuple[int, int, int], dict[str, Any]] = {}
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f, delimiter=";")
        for row in reader:
            if len(row) < 5:
                continue
            try:
                pid = int(row[0])
                r, g, b = int(row[1]), int(row[2]), int(row[3])
                ptype = row[4].strip().lower()
                terrain = row[6].strip() if len(row) > 6 else ""
            except (ValueError, IndexError):
                continue
            if pid <= 0:
                continue
            color_info[(r, g, b)] = {
                "id": pid,
                "type": ptype,
                "terrain": terrain,
            }
    return color_info


def _read_provinces_bmp(bmp_path: str) -> tuple[np.ndarray, dict[tuple[int, int, int], int]]:
    """读取 provinces.bmp，返回 (rgb_array[H,W,3], color→auto_id 映射)。

    PIL 会自动处理 BMP 的 bottom-up 行序。
    """
    img = Image.open(bmp_path).convert("RGB")
    rgb = np.array(img, dtype=np.uint8)
    # 扫描唯一颜色，跳过 (0,0,0)
    h, w = rgb.shape[:2]
    flat = rgb.reshape(-1, 3)
    # 用结构化数组做 unique
    flat_view = flat.view(np.dtype([("r", np.uint8), ("g", np.uint8), ("b", np.uint8)]))
    unique_colors = np.unique(flat_view)

    auto_map: dict[tuple[int, int, int], int] = {}
    next_id = 1
    for c in unique_colors:
        r, g, b = int(c["r"]), int(c["g"]), int(c["b"])
        if (r, g, b) == (0, 0, 0):
            continue
        auto_map[(r, g, b)] = next_id
        next_id += 1

    return rgb, auto_map


def _build_province_map(
    rgb: np.ndarray,
    color_to_id: dict[tuple[int, int, int], int],
) -> np.ndarray:
    """从 RGB 数组和颜色映射构建 province_map (int32)。

    用 24-bit 直接查找表（16M 条目 = 64MB）实现 O(N) 映射，
    替代之前的 np.unique + inverse（O(N log N)，1150 万像素要 20 秒）。
    """
    h, w = rgb.shape[:2]

    # RGB → 24-bit int
    flat = rgb.reshape(-1, 3).astype(np.int32)
    keys = (flat[:, 0] << 16) | (flat[:, 1] << 8) | flat[:, 2]

    # 直接查找表: 24-bit key → province ID
    lut = np.zeros(1 << 24, dtype=np.int32)
    for (r, g, b), pid in color_to_id.items():
        lut[(r << 16) | (g << 8) | b] = pid

    province_map = lut[keys].reshape(h, w)
    return province_map


def _build_tile_map(
    province_map: np.ndarray,
    color_to_id: dict[tuple[int, int, int], int],
    definition_info: dict[tuple[int, int, int], dict[str, Any]] | None,
) -> tuple[np.ndarray, dict[int, str]]:
    """构建 tile_map (land/sea/lake) 和 provincial_terrain 字典。

    用 LUT 直接映射 province_id → tile_type，O(像素) 不逐省份扫描。
    """
    h, w = province_map.shape
    provincial_terrain: dict[int, str] = {}

    if definition_info is None:
        return np.full((h, w), TILE_LAND, dtype=np.uint8), provincial_terrain

    # 构建 province_id → tile_type 查找表
    max_pid = int(province_map.max())
    type_lut = np.full(max_pid + 1, TILE_LAND, dtype=np.uint8)
    for color, info in definition_info.items():
        pid = info["id"]
        if pid <= 0 or pid > max_pid:
            continue
        ptype = _TYPE_MAP.get(info["type"], TILE_LAND)
        type_lut[pid] = ptype
        if info.get("terrain"):
            provincial_terrain[pid] = info["terrain"]

    # 直接 LUT 映射 — O(像素), 不逐省份
    tile_map = type_lut[province_map]
    return tile_map, provincial_terrain


def _read_indexed_bmp(bmp_path: str) -> np.ndarray:
    """读取 8-bit 索引 BMP，返回调色板索引数组 (uint8)。"""
    img = Image.open(bmp_path)
    if img.mode == "P":
        # 直接获取调色板索引
        data = np.array(img, dtype=np.uint8)
    elif img.mode == "L":
        # 灰度图直接用
        data = np.array(img, dtype=np.uint8)
    else:
        # 转灰度作为 fallback
        data = np.array(img.convert("L"), dtype=np.uint8)
    return data


def _extract_block_value(text: str, key: str) -> str:
    """从 Clausewitz 脚本里提取 key={...} 或 key=value。"""
    import re
    # key = { ... }
    m = re.search(rf'{key}\s*=\s*\{{([^}}]*)\}}', text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # key = value
    m = re.search(rf'{key}\s*=\s*(\S+)', text)
    if m:
        return m.group(1).strip().strip('"')
    return ""


def _parse_state_file(path: str) -> dict | None:
    """解析 history/states/*.txt，返回 {id, name, provinces, owner, manpower, category}。"""
    with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
        text = f.read()

    sid_str = _extract_block_value(text, "id")
    if not sid_str:
        return None
    try:
        sid = int(sid_str)
    except ValueError:
        return None

    name = _extract_block_value(text, "name") or f"STATE_{sid}"
    owner = _extract_block_value(text, "owner") or ""
    manpower_str = _extract_block_value(text, "manpower")
    manpower = int(manpower_str) if manpower_str.isdigit() else 100000
    category = _extract_block_value(text, "state_category") or "town"

    # 省份列表
    provinces_str = _extract_block_value(text, "provinces")
    province_ids = []
    for token in provinces_str.split():
        try:
            province_ids.append(int(token))
        except ValueError:
            pass

    if not province_ids:
        return None

    # 解析 victory_points = { pid value } （可能多个）
    import re
    victory_points: dict[int, int] = {}
    for m in re.finditer(r'victory_points\s*=\s*\{\s*(\d+)\s+(\d+)\s*\}', text):
        vp_pid, vp_val = int(m.group(1)), int(m.group(2))
        if vp_val > 0:
            victory_points[vp_pid] = vp_val

    return {
        "id": sid,
        "name": name,
        "provinces": province_ids,
        "owner": owner,
        "manpower": manpower,
        "category": category,
        "victory_points": victory_points,
    }


def _parse_strategic_region_file(path: str) -> dict | None:
    """解析 map/strategicregions/*.txt，返回 {id, name, provinces, weather_preset, naval_terrain}。"""
    with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
        text = f.read()

    rid_str = _extract_block_value(text, "id")
    if not rid_str:
        return None
    try:
        rid = int(rid_str)
    except ValueError:
        return None

    name = _extract_block_value(text, "name") or f"STRATEGICREGION_{rid}"
    provinces_str = _extract_block_value(text, "provinces")
    province_ids = []
    for token in provinces_str.split():
        try:
            province_ids.append(int(token))
        except ValueError:
            pass

    # 读取 naval_terrain（vanilla 合法值: water_deep_ocean/water_shallow_sea/water_fjords）
    naval_terrain = ""
    import re
    nt_match = re.search(r'naval_terrain\s*=\s*(\S+)', text)
    if nt_match:
        raw = nt_match.group(1).strip().strip('"')
        if raw in ("water_deep_ocean", "water_shallow_sea", "water_fjords"):
            naval_terrain = raw
        # 兼容老 MOD 残留的短名
        elif raw in ("deep_ocean", "ocean"):
            naval_terrain = "water_deep_ocean"
        elif raw == "shallow_sea":
            naval_terrain = "water_shallow_sea"
        elif raw == "fjords":
            naval_terrain = "water_fjords"

    # 从 weather 的 temperature 推断天气 preset
    weather_preset = _guess_weather_preset(text)

    return {
        "id": rid,
        "name": name,
        "provinces": province_ids,
        "weather_preset": weather_preset,
        "naval_terrain": naval_terrain,
    }


def _guess_weather_preset(text: str) -> str:
    """从 weather block 的 temperature 值推断最接近的天气预设。"""
    import re
    temps = re.findall(r'temperature\s*=\s*\{\s*([-\d.]+)\s+([-\d.]+)\s*\}', text)
    if not temps:
        return "temperate"

    # 取所有月份的平均高温
    avg_high = sum(float(t[1]) for t in temps) / len(temps)
    avg_low = sum(float(t[0]) for t in temps) / len(temps)

    # 检查沙尘暴（沙漠特征）
    sandstorms = re.findall(r'sandstorm\s*=\s*([\d.]+)', text)
    has_sandstorm = any(float(s) > 0.1 for s in sandstorms)

    if has_sandstorm:
        return "desert"
    if avg_high >= 28 and avg_low >= 15:
        return "tropical"
    if avg_high <= 5:
        return "polar"
    if avg_high <= 15:
        return "cold"
    return "temperate"


def import_mod_map(mod_dir: str) -> dict[str, Any]:
    """从 HOI4 mod/vanilla 目录导入地图图层。

    参数:
        mod_dir: 包含 map/ 子目录的根目录

    返回:
        {
            "width": int,
            "height": int,
            "tile_map": np.ndarray,
            "province_map": np.ndarray,
            "terrain_map": np.ndarray,
            "height_map": np.ndarray,
            "river_map": np.ndarray,
            "province_count": int,
            "provincial_terrain": dict[int, str],
            "warnings": list[str],
        }

    异常:
        FileNotFoundError: provinces.bmp 不存在
        ValueError: BMP 格式错误
    """
    mod_dir = os.path.normpath(mod_dir)
    map_dir = os.path.join(mod_dir, "map")
    provinces_path = os.path.join(map_dir, "provinces.bmp")

    # 大小写不敏感查找（用户文件可能是 Provinces.bmp / PROVINCES.BMP）
    if not os.path.isfile(provinces_path) and os.path.isdir(map_dir):
        for f in os.listdir(map_dir):
            if f.lower() == "provinces.bmp":
                provinces_path = os.path.join(map_dir, f)
                break

    if not os.path.isfile(provinces_path):
        raise FileNotFoundError(f"provinces.bmp 不存在: {provinces_path}")

    warnings: list[str] = []

    # 1. 读取 provinces.bmp（只读 RGB，不扫唯一颜色——那个 O(N log N) 太慢）
    img = Image.open(provinces_path).convert("RGB")
    rgb = np.array(img, dtype=np.uint8)
    h, w = rgb.shape[:2]

    # 2. 读取 definition.csv (可选) — 有 csv 直接用它的 color→ID，跳过像素扫描
    definition_path = os.path.join(map_dir, "definition.csv")
    definition_info: dict[tuple[int, int, int], dict[str, Any]] | None = None
    if os.path.isfile(definition_path):
        definition_info = _parse_definition_csv(definition_path)
        color_to_id: dict[tuple[int, int, int], int] = {
            c: info["id"] for c, info in definition_info.items()
        }
    else:
        # 没有 definition.csv → 退回扫描唯一颜色自动分配 ID（慢路径）
        _, color_to_id = _read_provinces_bmp(provinces_path)
        warnings.append("未找到 definition.csv，省份类型全部设为陆地")

    # 3. 构建 province_map
    province_map = _build_province_map(rgb, color_to_id)
    province_count = int(province_map.max())

    # 4. 构建 tile_map + provincial_terrain
    tile_map, provincial_terrain = _build_tile_map(
        province_map, color_to_id, definition_info
    )

    # 5. 读取 terrain.bmp (可选)
    terrain_path = os.path.join(map_dir, "terrain.bmp")
    if os.path.isfile(terrain_path):
        terrain_map = _read_indexed_bmp(terrain_path)
        if terrain_map.shape != (h, w):
            warnings.append(
                f"terrain.bmp 尺寸 {terrain_map.shape[1]}x{terrain_map.shape[0]} "
                f"与 provinces.bmp {w}x{h} 不匹配，已缩放"
            )
            img = Image.fromarray(terrain_map)
            img = img.resize((w, h), Image.Resampling.NEAREST)
            terrain_map = np.array(img, dtype=np.uint8)
    else:
        terrain_map = np.zeros((h, w), dtype=np.uint8)
        warnings.append("未找到 terrain.bmp，地形图层设为空")

    # 6. 读取 heightmap.bmp (可选)
    heightmap_path = os.path.join(map_dir, "heightmap.bmp")
    if os.path.isfile(heightmap_path):
        height_map = _read_indexed_bmp(heightmap_path)
        if height_map.shape != (h, w):
            warnings.append(
                f"heightmap.bmp 尺寸 {height_map.shape[1]}x{height_map.shape[0]} "
                f"与 provinces.bmp {w}x{h} 不匹配，已缩放"
            )
            img = Image.fromarray(height_map)
            img = img.resize((w, h), Image.Resampling.NEAREST)
            height_map = np.array(img, dtype=np.uint8)
    else:
        height_map = np.full((h, w), 40, dtype=np.uint8)
        warnings.append("未找到 heightmap.bmp，高度图层设为默认值")

    # 7. 读取 rivers.bmp (可选)
    rivers_path = os.path.join(map_dir, "rivers.bmp")
    if os.path.isfile(rivers_path):
        river_map = _read_indexed_bmp(rivers_path)
        if river_map.shape != (h, w):
            warnings.append(
                f"rivers.bmp 尺寸 {river_map.shape[1]}x{river_map.shape[0]} "
                f"与 provinces.bmp {w}x{h} 不匹配，已缩放"
            )
            img = Image.fromarray(river_map)
            img = img.resize((w, h), Image.Resampling.NEAREST)
            river_map = np.array(img, dtype=np.uint8)
    else:
        river_map = np.full((h, w), 255, dtype=np.uint8)
        warnings.append("未找到 rivers.bmp，河流图层设为空")

    # 8. 读取 states (可选)
    states_dir = os.path.join(mod_dir, "history", "states")
    states_data: list[dict] = []
    if os.path.isdir(states_dir):
        for fn in sorted(os.listdir(states_dir)):
            if not fn.endswith(".txt"):
                continue
            try:
                sd = _parse_state_file(os.path.join(states_dir, fn))
                if sd:
                    states_data.append(sd)
            except Exception:
                pass
        if states_data:
            warnings.append(f"读取了 {len(states_data)} 个 State 文件")
    else:
        warnings.append("未找到 history/states/ 目录")

    # 9a. 扫描美术资产（colormap / world_normal 等 HOI4 会读但工具不生成的文件）
    assets = _collect_art_assets(mod_dir)
    if assets:
        warnings.append(f"保留了 {len(assets)} 个原始美术资产（导出时不会覆盖）")

    # 9. 读取 strategic regions (可选)
    sr_dir = os.path.join(mod_dir, "map", "strategicregions")
    sr_data: list[dict] = []
    if os.path.isdir(sr_dir):
        for fn in sorted(os.listdir(sr_dir)):
            if not fn.endswith(".txt"):
                continue
            try:
                rd = _parse_strategic_region_file(os.path.join(sr_dir, fn))
                if rd:
                    sr_data.append(rd)
            except Exception:
                pass
        if sr_data:
            warnings.append(f"读取了 {len(sr_data)} 个战略区域文件")
    else:
        warnings.append("未找到 map/strategicregions/ 目录")

    # 9c. 读取本地化 → 替换 state 名字（STATE_1 → "Corsica"）
    loc_map = _scan_localisation(mod_dir)
    if loc_map:
        for sd in states_data:
            key = sd.get("name", "")
            if key in loc_map:
                sd["name"] = loc_map[key]
            # VP 城市名
            vp_names: dict[int, str] = {}
            for vp_pid in sd.get("victory_points", {}):
                vp_key = f"VICTORY_POINTS_{vp_pid}"
                if vp_key in loc_map:
                    vp_names[vp_pid] = loc_map[vp_key]
            if vp_names:
                sd["vp_names"] = vp_names
        # 战略区域名
        for rd in sr_data:
            key = rd.get("name", "")
            if key in loc_map:
                rd["name"] = loc_map[key]
        warnings.append(f"读取了 {len(loc_map)} 条本地化文本")

    # 10. 读取 railways (可选)
    railways_data: list[dict] = []
    railways_path = os.path.join(map_dir, "railways.txt")
    if os.path.isfile(railways_path):
        railways_data = _parse_railways(railways_path)
        if railways_data:
            warnings.append(f"读取了 {len(railways_data)} 条铁路")

    # 11. 读取 supply_nodes (可选)
    supply_data: list[dict] = []
    supply_path = os.path.join(map_dir, "supply_nodes.txt")
    if os.path.isfile(supply_path):
        supply_data = _parse_supply_nodes(supply_path)
        if supply_data:
            warnings.append(f"读取了 {len(supply_data)} 个补给节点")

    # 12. 读取 adjacencies (可选)
    adjacencies_data: list[dict] = []
    adj_path = os.path.join(map_dir, "adjacencies.csv")
    if os.path.isfile(adj_path):
        adjacencies_data = _parse_adjacencies(adj_path)
        if adjacencies_data:
            warnings.append(f"读取了 {len(adjacencies_data)} 条邻接关系")

    # 13. 读取国家颜色 (可选)
    country_colors: dict[str, tuple[int, int, int]] = {}
    colors_path = os.path.join(mod_dir, "common", "countries", "colors.txt")
    if os.path.isfile(colors_path):
        country_colors = _parse_country_colors(colors_path)
        if country_colors:
            warnings.append(f"读取了 {len(country_colors)} 个国家颜色")

    # 14. 读取国家历史 (首都/政体, 可选)
    country_history = _parse_country_history_dir(mod_dir)
    if country_history:
        warnings.append(f"读取了 {len(country_history)} 个国家历史文件")

    return {
        "width": w,
        "height": h,
        "tile_map": tile_map,
        "province_map": province_map,
        "terrain_map": terrain_map,
        "height_map": height_map,
        "river_map": river_map,
        "province_count": province_count,
        "provincial_terrain": provincial_terrain,
        "states": states_data,
        "strategic_regions": sr_data,
        "railways": railways_data,
        "supply_nodes": supply_data,
        "adjacencies": adjacencies_data,
        "assets": assets,
        "country_colors": country_colors,
        "country_history": country_history,
        # TAG → 本地化国名等 (states/战略区名已就地替换, 国家名在填充时查)
        "localisation": loc_map,
        "warnings": warnings,
    }


# ── 国家颜色解析 ──────────────────────────────────────────────


def _parse_country_colors(path: str) -> dict[str, tuple[int, int, int]]:
    """解析 common/countries/colors.txt → {TAG: (R, G, B)}。"""
    import re
    colors: dict[str, tuple[int, int, int]] = {}
    with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
        text = f.read()
    for m in re.finditer(
        r'(\b[A-Z]{3})\s*=\s*\{[^}]*?color\s*=\s*rgb\s*\{\s*(\d+)\s+(\d+)\s+(\d+)',
        text, re.DOTALL,
    ):
        tag = m.group(1)
        r, g, b = int(m.group(2)), int(m.group(3)), int(m.group(4))
        colors[tag] = (r, g, b)
    return colors


# ── 本地化扫描 ──────────────────────────────────────────────


def _scan_localisation(mod_dir: str) -> dict[str, str]:
    """扫描 MOD 的 localisation/ 下所有 .yml 文件，提取 KEY: "value" 映射。

    优先读 english/ 子目录（最完整），再读根目录。
    返回 {KEY: value} 字典，用于替换 state name 等。
    """
    import re
    result: dict[str, str] = {}
    loc_dir = os.path.join(mod_dir, "localisation")
    if not os.path.isdir(loc_dir):
        return result

    def _scan_dir(d: str) -> None:
        if not os.path.isdir(d):
            return
        for root, _dirs, files in os.walk(d):
            for fn in files:
                if not fn.endswith(".yml"):
                    continue
                try:
                    with open(os.path.join(root, fn), "r", encoding="utf-8-sig", errors="ignore") as f:
                        for line in f:
                            # 格式: " KEY:0 \"value\"" 或 " KEY: \"value\""
                            m = re.match(r'\s+(\S+?):\d*\s+"([^"]*)"', line)
                            if m:
                                result[m.group(1)] = m.group(2)
                except OSError:
                    pass

    # 优先英文
    _scan_dir(os.path.join(loc_dir, "english"))
    # 再扫根目录（有些 MOD 直接放 localisation/ 下）
    for fn in os.listdir(loc_dir):
        full = os.path.join(loc_dir, fn)
        if os.path.isfile(full) and fn.endswith(".yml"):
            try:
                with open(full, "r", encoding="utf-8-sig", errors="ignore") as f:
                    for line in f:
                        import re as _re
                        m = _re.match(r'\s+(\S+?):\d*\s+"([^"]*)"', line)
                        if m and m.group(1) not in result:
                            result[m.group(1)] = m.group(2)
            except OSError:
                pass

    return result


# ── 后勤文件解析 ──────────────────────────────────────────────


def _parse_railways(path: str) -> list[dict]:
    """解析 map/railways.txt。每行: level count pid1 pid2 pid3 ..."""
    result = []
    with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            tokens = line.split()
            if len(tokens) < 4:  # level + count + 至少2个省份
                continue
            try:
                level = int(tokens[0])
                count = int(tokens[1])
                pids = [int(t) for t in tokens[2:2 + count]]
                if len(pids) >= 2:
                    result.append({"level": level, "province_ids": pids})
            except ValueError:
                continue
    return result


def _parse_supply_nodes(path: str) -> list[dict]:
    """解析 map/supply_nodes.txt。每行: level province_id"""
    result = []
    with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            tokens = line.split()
            if len(tokens) < 2:
                continue
            try:
                level = int(tokens[0])
                pid = int(tokens[1])
                result.append({"level": level, "province_id": pid})
            except ValueError:
                continue
    return result


def _parse_adjacencies(path: str) -> list[dict]:
    """解析 map/adjacencies.csv。格式: From;To;Type;Through;start_x;start_y;stop_x;stop_y;rule;Comment"""
    result = []
    with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("From"):
                continue
            parts = line.split(";")
            if len(parts) < 4:
                continue
            try:
                from_id = int(parts[0])
                to_id = int(parts[1])
                if from_id < 0 or to_id < 0:
                    continue  # 哨兵行 -1;-1;...
                adj_type = parts[2].strip() or "sea"
                through = int(parts[3]) if len(parts) > 3 and parts[3].strip().lstrip('-').isdigit() else -1
                start_x = int(parts[4]) if len(parts) > 4 and parts[4].strip().lstrip('-').isdigit() else -1
                start_y = int(parts[5]) if len(parts) > 5 and parts[5].strip().lstrip('-').isdigit() else -1
                stop_x = int(parts[6]) if len(parts) > 6 and parts[6].strip().lstrip('-').isdigit() else -1
                stop_y = int(parts[7]) if len(parts) > 7 and parts[7].strip().lstrip('-').isdigit() else -1
                rule = parts[8].strip() if len(parts) > 8 else ""
                comment = parts[9].strip() if len(parts) > 9 else ""
                result.append({
                    "from_id": from_id, "to_id": to_id,
                    "type": adj_type, "through_id": through,
                    "start_x": start_x, "start_y": start_y,
                    "stop_x": stop_x, "stop_y": stop_y,
                    "rule": rule, "comment": comment,
                })
            except (ValueError, IndexError):
                continue
    return result


# ── 美术资产扫描 ──────────────────────────────────────────────
# "结构性文件" = 工具会从数据重新生成的文件（不保留原字节）
# 其它文件 = 美术资产（保留原字节，除非用户编辑触发 dirty）

# 这些 map/ 下文件工具会从 MapData / managers 重新生成 → 不收进 assets
_STRUCTURAL_MAP_FILES = {
    "provinces.bmp",
    "heightmap.bmp",
    "terrain.bmp",
    "rivers.bmp",
    "trees.bmp",
    "cities.bmp",
    "definition.csv",
    "default.map",
    "continent.txt",
    "adjacencies.csv",
    "adjacency_rules.txt",
    "ambient_object.txt",
    "buildings.txt",
    "positions.txt",
    "railways.txt",
    "supply_nodes.txt",
    "unitstacks.txt",
    "airports.txt",
    "rocket_sites.txt",
    "weatherpositions.txt",
    "seasons.txt",
    "cities.txt",
    "colors.txt",
}


def _collect_art_assets(mod_dir: str) -> dict[str, bytes]:
    """扫描 MOD 的 map/ 和 map/terrain/ 下所有非结构性文件，返回 {rel_path: bytes}。

    结构性文件（provinces/heightmap/terrain 等）由工具从数据重新生成，不收集。
    美术资产（colormap_*.dds、world_normal.bmp 等）原样保留。

    返回值的 key 形如 "map/terrain/colormap_rgb_cityemissivemask_a.dds"（斜杠分隔）。
    """
    assets: dict[str, bytes] = {}
    map_dir = os.path.join(mod_dir, "map")
    if not os.path.isdir(map_dir):
        return assets

    def _add_file(full_path: str, rel_to_mod: str) -> None:
        try:
            with open(full_path, "rb") as f:
                assets[rel_to_mod.replace(os.sep, "/")] = f.read()
        except OSError:
            pass

    # 扫 map/ 根目录
    for fn in os.listdir(map_dir):
        full = os.path.join(map_dir, fn)
        if not os.path.isfile(full):
            continue
        if fn in _STRUCTURAL_MAP_FILES:
            continue
        # 收非结构性文件（world_normal.bmp 等）
        _add_file(full, f"map/{fn}")

    # 扫 map/terrain/ 下所有 .dds / .bmp（全都是美术，vanilla 生成，无结构性文件）
    terrain_dir = os.path.join(map_dir, "terrain")
    if os.path.isdir(terrain_dir):
        for fn in os.listdir(terrain_dir):
            full = os.path.join(terrain_dir, fn)
            if not os.path.isfile(full):
                continue
            _add_file(full, f"map/terrain/{fn}")

    return assets


# ── 国家历史 ────────────────────────────────────────────────

_CAPITAL_RE = re.compile(r"^\s*capital\s*=\s*(\d+)", re.M)
_RULING_PARTY_RE = re.compile(r"ruling_party\s*=\s*(\w+)")


def _parse_country_history_dir(mod_dir: str) -> dict[str, dict]:
    """解析 history/countries/*.txt → {TAG: {capital_state, ruling_party}}。

    文件名约定 "TAG - Name.txt"。只提取最常用的两个字段:
    - capital: 注意 HOI4 这里是 State ID, 不是省份 ID,
      填充进 CountryData 前必须换算 (见 _populate_imported_data)
    - set_politics 块里的 ruling_party
    """
    out: dict[str, dict] = {}
    hist_dir = os.path.join(mod_dir, "history", "countries")
    if not os.path.isdir(hist_dir):
        return out
    for fn in sorted(os.listdir(hist_dir)):
        if not fn.endswith(".txt"):
            continue
        tag = fn[:3].upper()
        if len(tag) != 3 or not tag.isascii() or not tag.isalnum():
            continue
        try:
            with open(os.path.join(hist_dir, fn), "r",
                      encoding="utf-8-sig", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        cap_m = _CAPITAL_RE.search(text)
        party_m = _RULING_PARTY_RE.search(text)
        out[tag] = {
            "capital_state": int(cap_m.group(1)) if cap_m else 0,
            "ruling_party": party_m.group(1) if party_m else "",
        }
    return out
