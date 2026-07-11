"""
MOD 输出验证器 — 检查导出的所有文件是否符合 HOI4 格式要求
不启动游戏就能发现大部分格式错误

用法:
    python -m export.verify_mod  D:/path/to/exported/mod
"""
import os
import struct
import sys
import re
from collections import Counter


class ModVerifier:
    """逐文件检查 HOI4 MOD 输出，报告所有发现的问题"""

    def __init__(self, mod_dir: str, *, quiet: bool = False):
        self.mod_dir = mod_dir
        self.errors: list[str] = []    # 必定崩溃
        self.warnings: list[str] = []  # 可能有问题
        self._quiet = quiet

    def _run_all_checks(self) -> None:
        """执行所有验证检查（内部方法，不打印）"""
        self._check_required_files()
        self._check_provinces_bmp()
        self._check_definition_csv()
        self._check_default_map()
        self._check_heightmap_bmp()
        self._check_terrain_bmp()
        self._check_rivers_bmp()
        self._check_states()
        self._check_strategic_regions()
        self._check_supply_files()
        self._check_countries()
        self._check_ideologies()
        self._check_state_categories()
        self._check_bookmarks()
        self._check_localisation()
        self._check_descriptor()
        self._check_seasons()
        self._cross_validate()

    def verify_all(self) -> bool:
        """运行所有检查，返回 True = 通过"""
        print(f"验证 MOD: {self.mod_dir}\n")

        self._run_all_checks()

        # 报告
        print("\n" + "=" * 60)
        if self.errors:
            print(f"\n❌ 发现 {len(self.errors)} 个错误（会导致崩溃）:")
            for i, e in enumerate(self.errors, 1):
                print(f"  {i}. {e}")
        if self.warnings:
            print(f"\n⚠️  发现 {len(self.warnings)} 个警告:")
            for i, w in enumerate(self.warnings, 1):
                print(f"  {i}. {w}")
        if not self.errors and not self.warnings:
            print("\n✅ 所有检查通过！")

        return len(self.errors) == 0

    @classmethod
    def verify_quiet(cls, mod_dir: str) -> tuple[list[str], list[str]]:
        """静默运行所有检查，返回 (errors, warnings)。
        不打印任何内容，适合 UI 调用。"""
        v = cls(mod_dir, quiet=True)
        v._run_all_checks()
        return v.errors, v.warnings

    def _log(self, msg: str) -> None:
        if not self._quiet:
            print(msg)

    def _path(self, *parts):
        return os.path.join(self.mod_dir, *parts)

    def _exists(self, *parts):
        return os.path.exists(self._path(*parts))

    # ──────────────── 检查项 ────────────────

    def _check_required_files(self):
        """检查所有必需文件是否存在"""
        self._log("[1/16] 检查必需文件...")
        required = [
            ("map/provinces.bmp", "省份地图"),
            ("map/definition.csv", "省份定义"),
            ("map/default.map", "地图配置"),
            ("map/heightmap.bmp", "高度图"),
            ("map/terrain.bmp", "地形图"),
            ("map/rivers.bmp", "河流图"),
            ("map/trees.bmp", "树木图"),
            ("map/continent.txt", "大陆定义"),
            ("map/adjacencies.csv", "邻接定义"),
            ("map/adjacency_rules.txt", "邻接规则"),
            ("map/ambient_object.txt", "环境物体"),
            ("map/seasons.txt", "季节定义"),
            ("map/positions.txt", "省份坐标"),
            ("map/supply_nodes.txt", "补给节点"),
            ("map/railways.txt", "铁路"),
            ("map/buildings.txt", "建筑"),
            ("descriptor.mod", "MOD描述文件"),
        ]
        for path, name in required:
            if not self._exists(path):
                self.errors.append(f"缺少必需文件: {path} ({name})")

    def _check_provinces_bmp(self):
        """检查 provinces.bmp 格式"""
        self._log("[2/16] 检查 provinces.bmp...")
        path = self._path("map", "provinces.bmp")
        if not os.path.exists(path):
            return

        with open(path, "rb") as f:
            sig = f.read(2)
            if sig != b"BM":
                self.errors.append("provinces.bmp: 不是有效的BMP文件")
                return

            f.seek(18)
            w = struct.unpack("<i", f.read(4))[0]
            h = struct.unpack("<i", f.read(4))[0]
            f.read(2)  # planes
            bits = struct.unpack("<H", f.read(2))[0]

            valid_sizes = {(2048, 1024), (3072, 1536), (4096, 2048), (5632, 2048)}
            if (w, abs(h)) not in valid_sizes:
                self.errors.append(
                    f"provinces.bmp: 尺寸 {w}x{abs(h)}，"
                    f"应为 2048x1024/3072x1536/4096x2048/5632x2048 之一"
                )
            if bits != 24:
                self.errors.append(f"provinces.bmp: 位深 {bits}，应为 24")
            if h < 0:
                self.errors.append("provinces.bmp: top-down 格式，应为 bottom-up (高度值应为正)")

            # 检查是否有 (0,0,0) 像素
            f.seek(10)
            offset = struct.unpack("<I", f.read(4))[0]
            f.seek(offset)

            row_bytes = w * 3
            padding = (4 - (row_bytes % 4)) % 4
            has_black = False
            for _ in range(min(10, h)):  # 抽查前10行
                row = f.read(row_bytes)
                f.read(padding)
                for x in range(0, len(row), 3):
                    if row[x] == 0 and row[x + 1] == 0 and row[x + 2] == 0:
                        has_black = True
                        break
                if has_black:
                    break
            if has_black:
                self.errors.append("provinces.bmp: 包含 RGB(0,0,0) 像素，HOI4 会崩溃")

    def _check_definition_csv(self):
        """检查 definition.csv 格式"""
        self._log("[3/16] 检查 definition.csv...")
        path = self._path("map", "definition.csv")
        if not os.path.exists(path):
            return

        with open(path, "r") as f:
            lines = f.readlines()

        if not lines:
            self.errors.append("definition.csv: 文件为空")
            return

        # 第一行必须是ID=0
        first = lines[0].strip()
        if not first.startswith("0;"):
            self.errors.append(f"definition.csv: 第一行应以 '0;' 开头，实际是 '{first[:20]}'")

        seen_colors = set()
        seen_ids = set()
        valid_types = {"land", "sea", "lake"}
        self._province_ids = set()
        self._land_province_ids = set()

        for i, line in enumerate(lines):
            line = line.rstrip("\n")
            if line.endswith(" ") or line.endswith("\t"):
                self.errors.append(f"definition.csv 第{i + 1}行: 行尾有空格/tab")
            parts = line.strip().split(";")
            if len(parts) != 8:
                self.errors.append(f"definition.csv 第{i + 1}行: {len(parts)}个字段，应为8个")
                continue

            pid = int(parts[0])
            r, g, b = int(parts[1]), int(parts[2]), int(parts[3])
            ptype = parts[4]

            if pid in seen_ids:
                self.errors.append(f"definition.csv: 省份ID {pid} 重复")
            seen_ids.add(pid)

            if pid > 0:
                self._province_ids.add(pid)
                if ptype == "land":
                    self._land_province_ids.add(pid)

                color = (r, g, b)
                if color == (0, 0, 0):
                    self.errors.append(f"definition.csv 省份{pid}: 颜色是(0,0,0)，HOI4禁止")
                if color in seen_colors:
                    self.errors.append(f"definition.csv 省份{pid}: 颜色{color}与其他省份重复")
                seen_colors.add(color)

            if ptype not in valid_types:
                self.warnings.append(f"definition.csv 省份{pid}: type='{ptype}'，非标准类型")

        self._log(f"    → {len(self._province_ids)} 个省份 ({len(self._land_province_ids)} 陆地)")

    def _check_default_map(self):
        """检查 default.map"""
        self._log("[4/16] 检查 default.map...")
        path = self._path("map", "default.map")
        if not os.path.exists(path):
            return

        with open(path, "r") as f:
            content = f.read()

        required_refs = [
            "definition.csv", "provinces.bmp", "positions.txt",
            "terrain.bmp", "rivers.bmp", "heightmap.bmp",
            "trees.bmp", "continent.txt", "adjacencies.csv",
            "seasons.txt",
        ]
        for ref in required_refs:
            if ref not in content:
                self.errors.append(f"default.map: 缺少 {ref} 引用")

        if "sea_starts" in content:
            self.errors.append("default.map: 包含 sea_starts（1.17不支持，用definition.csv的type代替）")
        if "max_provinces" in content:
            self.warnings.append("default.map: 包含 max_provinces（1.17可能不支持）")

    def _get_provinces_bmp_size(self) -> tuple[int, int] | None:
        """读取 provinces.bmp 的尺寸，用于和其他 BMP 做一致性校验"""
        path = self._path("map", "provinces.bmp")
        if not os.path.exists(path):
            return None
        with open(path, "rb") as f:
            if f.read(2) != b"BM":
                return None
            f.seek(18)
            w = struct.unpack("<i", f.read(4))[0]
            h = abs(struct.unpack("<i", f.read(4))[0])
            return (w, h)

    def _check_heightmap_bmp(self):
        """检查 heightmap.bmp"""
        self._log("[5/16] 检查 heightmap.bmp...")
        size = self._get_provinces_bmp_size()
        if size:
            self._check_8bit_bmp("map/heightmap.bmp", "heightmap.bmp", size[0], size[1])

    def _check_terrain_bmp(self):
        """检查 terrain.bmp"""
        self._log("[6/16] 检查 terrain.bmp...")
        size = self._get_provinces_bmp_size()
        if size:
            self._check_8bit_bmp("map/terrain.bmp", "terrain.bmp", size[0], size[1])

    def _check_rivers_bmp(self):
        """检查 rivers.bmp"""
        self._log("[7/16] 检查 rivers.bmp...")
        size = self._get_provinces_bmp_size()
        if size:
            self._check_8bit_bmp("map/rivers.bmp", "rivers.bmp", size[0], size[1])

    def _check_8bit_bmp(self, rel_path, name, expected_w, expected_h):
        path = self._path(rel_path)
        if not os.path.exists(path):
            return
        with open(path, "rb") as f:
            sig = f.read(2)
            if sig != b"BM":
                self.errors.append(f"{name}: 不是有效的BMP文件")
                return
            f.seek(18)
            w = struct.unpack("<i", f.read(4))[0]
            h = struct.unpack("<i", f.read(4))[0]
            f.read(2)
            bits = struct.unpack("<H", f.read(2))[0]

            if w != expected_w or abs(h) != expected_h:
                self.errors.append(f"{name}: 尺寸 {w}x{abs(h)}，应为 {expected_w}x{expected_h}")
            if bits != 8:
                self.errors.append(f"{name}: 位深 {bits}，应为 8")

    def _check_states(self):
        """检查 State 文件"""
        self._log("[8/16] 检查 States...")
        state_dir = self._path("history", "states")
        if not os.path.isdir(state_dir):
            self.errors.append("缺少 history/states/ 目录")
            return

        files = [f for f in os.listdir(state_dir) if f.endswith(".txt")]
        if not files:
            self.errors.append("history/states/ 目录为空，至少需要1个State")
            return

        self._state_provinces = set()  # 所有State中的省份
        self._state_ids = set()
        self._state_prov_lists = {}    # {state_id: [pid...]} — 供战略区交叉检查用

        for fn in files:
            with open(os.path.join(state_dir, fn), "r") as f:
                content = f.read()

            # 提取 State ID
            id_match = re.search(r'id\s*=\s*(\d+)', content)
            if id_match:
                self._state_ids.add(int(id_match.group(1)))

            # 提取省份列表
            prov_match = re.search(r'provinces\s*=\s*\{([^}]+)\}', content)
            if prov_match:
                prov_text = prov_match.group(1)
                provs = [int(x) for x in prov_text.split() if x.isdigit()]
                for p in provs:
                    if p in self._state_provinces:
                        self.errors.append(f"{fn}: 省份 {p} 在多个State中（必须唯一）")
                    self._state_provinces.add(p)
                if id_match:
                    self._state_prov_lists[int(id_match.group(1))] = provs

            # 检查 owner
            if "owner" not in content:
                self.errors.append(f"{fn}: 缺少 owner 字段")

        self._log(f"    → {len(files)} 个State文件, {len(self._state_provinces)} 个省份被分配")

    def _check_strategic_regions(self):
        """检查战略区域"""
        self._log("[9/16] 检查战略区域...")
        sr_dir = self._path("map", "strategicregions")
        if not os.path.isdir(sr_dir):
            self.errors.append("缺少 map/strategicregions/ 目录")
            return

        files = [f for f in os.listdir(sr_dir) if f.endswith(".txt")]
        if not files:
            self.errors.append("map/strategicregions/ 目录为空")
            return

        self._region_provinces = set()
        pid_to_rid = {}  # {pid: region_id} — 供 state 跨区检查用
        for fn in files:
            with open(os.path.join(sr_dir, fn), "r") as f:
                content = f.read()
            id_match = re.search(r'id\s*=\s*(\d+)', content)
            rid = int(id_match.group(1)) if id_match else 0
            if rid == 0:
                self.errors.append(f"战略区域 {fn}: 缺少 id 字段")
            prov_match = re.search(r'provinces\s*=\s*\{([^}]+)\}', content)
            if prov_match:
                provs = [int(x) for x in prov_match.group(1).split() if x.isdigit()]
                for p in provs:
                    if p in self._region_provinces:
                        self.errors.append(f"战略区域 {fn}: 省份 {p} 在多个战略区中（必须唯一）")
                    self._region_provinces.add(p)
                    if rid > 0:  # 缺 id 的文件不参与跨区判断, 避免误报
                        pid_to_rid[p] = rid

            if "weather" not in content:
                self.errors.append(f"战略区域 {fn}: 缺少 weather 块")

        # state ↔ 战略区交叉检查: 一个 state 的省份必须都在同一战略区
        # (nudge: "provinces are not belong to same strategic region")
        cross = []
        for sid, provs in sorted(getattr(self, "_state_prov_lists", {}).items()):
            rids = {pid_to_rid[p] for p in provs if p in pid_to_rid}
            if len(rids) > 1:
                cross.append(sid)
        if cross:
            preview = ", ".join(str(s) for s in cross[:10])
            more = f" 等共 {len(cross)} 个" if len(cross) > 10 else ""
            self.warnings.append(
                f"{len(cross)} 个 State 的省份跨多个战略区 (State {preview}{more})。"
                f"游戏 nudge 会警告但不崩溃; 通常是 state 含飞地/离岸岛"
            )

        self._log(f"    → {len(files)} 个区域, 覆盖 {len(self._region_provinces)} 个省份")

    def _check_supply_files(self):
        """检查补给文件"""
        self._log("[10/16] 检查补给系统...")
        for fname in ["supply_nodes.txt", "railways.txt", "buildings.txt"]:
            path = self._path("map", fname)
            if os.path.exists(path):
                size = os.path.getsize(path)
                if size == 0:
                    self.errors.append(f"map/{fname}: 文件为空（不允许）")
            else:
                self.errors.append(f"缺少 map/{fname}")

    def _check_countries(self):
        """检查国家文件"""
        self._log("[11/16] 检查国家...")
        # 兼容新旧两种 TAG 注册文件名：新版用 02_worldtest_countries.txt 避免覆盖 vanilla
        ct_dir = self._path("common", "country_tags")
        tag_file = None
        for candidate in ("02_worldtest_countries.txt", "00_countries.txt"):
            p = os.path.join(ct_dir, candidate)
            if os.path.exists(p):
                tag_file = p
                break
        if tag_file is None:
            self.errors.append(
                "缺少 common/country_tags/02_worldtest_countries.txt（或旧版 00_countries.txt）"
            )
            return

        with open(tag_file, "r") as f:
            content = f.read()

        self._country_tags = re.findall(r'^([A-Z]{3})\s*=', content, re.MULTILINE)
        if not self._country_tags:
            self.errors.append(f"{os.path.basename(tag_file)}: 没有找到任何国家TAG")
            return

        for tag in self._country_tags:
            # common/countries/TAG.txt
            if not self._exists("common", "countries", f"{tag}.txt"):
                self.errors.append(f"缺少 common/countries/{tag}.txt")

            # history/countries/TAG.txt — 必须与 country_tags 注册路径严格一致
            if not self._exists("history", "countries", f"{tag}.txt"):
                self.errors.append(f"缺少 history/countries/{tag}.txt")

            # history/units/TAG_1936.txt
            if not self._exists("history", "units", f"{tag}_1936.txt"):
                self.errors.append(f"缺少 history/units/{tag}_1936.txt")

        self._log(f"    → {len(self._country_tags)} 个国家: {', '.join(self._country_tags)}")

    def _check_ideologies(self):
        """检查意识形态"""
        self._log("[12/16] 检查意识形态...")
        path = self._path("common", "ideologies", "00_ideologies.txt")
        if not os.path.exists(path):
            self.warnings.append("缺少意识形态文件（如果replace了common/ideologies则会崩溃）")
            return

        with open(path, "r") as f:
            content = f.read()

        required = ["democratic", "fascism", "communism", "neutrality"]
        for ideo in required:
            if ideo not in content:
                self.errors.append(f"意识形态: 缺少 {ideo}")

        if "types" not in content:
            self.errors.append("意识形态: 缺少 types 子块（必须有，否则崩溃）")

    def _check_state_categories(self):
        """检查 State 类别"""
        self._log("[13/16] 检查State类别...")
        sc_dir = self._path("common", "state_category")
        if not os.path.isdir(sc_dir):
            self.warnings.append("缺少 common/state_category/（如果replace了则会崩溃）")
            return

        files = [f for f in os.listdir(sc_dir) if f.endswith(".txt")]
        # 检查 town（默认类别）是否存在
        has_town = any("town" in open(os.path.join(sc_dir, f)).read() for f in files)
        if not has_town:
            self.errors.append("state_category: 缺少 'town' 类别（State默认使用）")

    def _check_bookmarks(self):
        """检查 Bookmark"""
        self._log("[14/16] 检查Bookmark...")
        bm_dir = self._path("common", "bookmarks")
        if not os.path.isdir(bm_dir):
            self.warnings.append("缺少 common/bookmarks/（如果replace了则会崩溃）")
            return

        files = [f for f in os.listdir(bm_dir) if f.endswith(".txt")]
        if not files:
            self.errors.append("common/bookmarks/ 目录为空")
            return

        for fn in files:
            with open(os.path.join(bm_dir, fn), "r") as f:
                content = f.read()
            if "randomize_weather" not in content:
                self.errors.append(f"Bookmark {fn}: 缺少 randomize_weather（必须有）")
            if "date" not in content:
                self.errors.append(f"Bookmark {fn}: 缺少 date 字段")

    def _check_localisation(self):
        """检查本地化"""
        self._log("[15/16] 检查本地化...")
        loc_dir = self._path("localisation")
        if not os.path.isdir(loc_dir):
            self.warnings.append("缺少 localisation/ 目录")
            return

        yml_files = [f for f in os.listdir(loc_dir) if f.endswith("_l_english.yml")]
        if not yml_files:
            self.warnings.append("localisation/ 中没有 *_l_english.yml 文件")
            return

        for fn in yml_files:
            path = os.path.join(loc_dir, fn)
            with open(path, "rb") as f:
                bom = f.read(3)
                if bom != b"\xef\xbb\xbf":
                    self.errors.append(f"本地化 {fn}: 缺少 UTF-8 BOM（必须有）")
            with open(path, "r", encoding="utf-8-sig") as f:
                first_line = f.readline().strip()
                if first_line != "l_english:":
                    self.errors.append(f"本地化 {fn}: 首行应为 'l_english:'，实际是 '{first_line}'")

    def _check_descriptor(self):
        """检查 descriptor.mod"""
        self._log("[16/16] 检查 descriptor.mod...")
        path = self._path("descriptor.mod")
        if not os.path.exists(path):
            return

        with open(path, "r") as f:
            content = f.read()

        # path= 不能出现在内部 descriptor（只有外层 .mod 才有）
        # 注意不能误匹配 replace_path=
        import re
        if re.search(r'^path\s*=', content, re.MULTILINE):
            self.errors.append("内部 descriptor.mod 不应包含 path= 字段")

        # 检查外层 .mod 文件
        mod_dir_name = os.path.basename(self.mod_dir)
        outer = os.path.join(os.path.dirname(self.mod_dir), f"{mod_dir_name}.mod")
        if os.path.exists(outer):
            with open(outer, "r") as f:
                outer_content = f.read()
            if "path=" not in outer_content:
                self.errors.append(f"外层 {mod_dir_name}.mod 缺少 path= 字段")
        else:
            self.errors.append(f"缺少外层 .mod 文件: {outer}")

        # 检查 replace_path 指向的目录是否存在
        for m in re.finditer(r'replace_path="([^"]+)"', content):
            rp = m.group(1)
            if not self._exists(rp):
                self.errors.append(f"replace_path=\"{rp}\" 指向的目录不存在")

    def _check_seasons(self):
        """检查 seasons.txt"""
        path = self._path("map", "seasons.txt")
        if not os.path.exists(path):
            return
        with open(path, "r") as f:
            content = f.read()
        for season in ["winter", "spring", "summer", "autumn"]:
            if season not in content:
                self.errors.append(f"seasons.txt: 缺少 {season} 定义")

    def _cross_validate(self):
        """交叉验证：省份分配完整性"""
        self._log("\n[交叉验证] 省份分配一致性...")

        if not hasattr(self, '_land_province_ids'):
            return

        # 每个陆地省份必须在某个 State 中
        if hasattr(self, '_state_provinces'):
            unassigned = self._land_province_ids - self._state_provinces
            if unassigned:
                sample = sorted(list(unassigned))[:10]
                self.errors.append(
                    f"有 {len(unassigned)} 个陆地省份不在任何State中: {sample}..."
                )

        # 每个省份必须在某个战略区域中
        if hasattr(self, '_region_provinces') and hasattr(self, '_province_ids'):
            unassigned_sr = self._province_ids - self._region_provinces
            if unassigned_sr:
                sample = sorted(list(unassigned_sr))[:10]
                self.errors.append(
                    f"有 {len(unassigned_sr)} 个省份不在任何战略区域中: {sample}..."
                )


def main():
    if len(sys.argv) < 2:
        print("用法: python -m export.verify_mod <MOD目录路径>")
        print("示例: python -m export.verify_mod D:/Documents/Paradox Interactive/Hearts of Iron IV/mod/TestMOD")
        sys.exit(1)

    mod_dir = sys.argv[1]
    if not os.path.isdir(mod_dir):
        print(f"错误: 目录不存在: {mod_dir}")
        sys.exit(1)

    v = ModVerifier(mod_dir)
    ok = v.verify_all()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
