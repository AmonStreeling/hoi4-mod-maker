"""
游戏资产读取 — 预览功能从用户的 HOI4 安装目录读取原版资源。

预览要用游戏自己的"配方"合成接近游戏内观感的画面：
- common/terrain/00_terrain.txt 的 terrain={} 块:
    terrain.bmp 调色板索引 → atlas 瓦片号 (texture = N)
- map/terrain/atlas0.dds:        地形材质图集, 4×4 网格 × 512px 瓦片
- map/terrain/atlas_normal0.dds: 法线贴图 (凹凸光影)

所有文件运行时按需读取并缓存; 游戏目录/文件缺失时各 getter 返回 None,
由调用方降级为纯色渲染。本模块不依赖 Qt。

参考: 参考/Map modding.txt 行 344-362 (atlas 瓦片排列为行优先:
texture = 11 即 4×4 网格第 3 行最右格)。
"""

from __future__ import annotations

import os
import re

import numpy as np

from data.constants import DEFAULT_HOI4_PATH

# atlas 图集固定为 4×4 瓦片网格
ATLAS_GRID = 4

TERRAIN_DEF_RELPATH = "common/terrain/00_terrain.txt"
ATLAS_RELPATH = "map/terrain/atlas0.dds"
ATLAS_NORMAL_RELPATH = "map/terrain/atlas_normal0.dds"
# 区域色调图 (RGB=色调, A=城市灯光遮罩); 分辨率是所属地图的一半
COLORMAP_RGB_RELPATH = "map/terrain/colormap_rgb_cityemissivemask_a.dds"


def find_hoi4_install() -> str | None:
    """返回 HOI4 安装目录, 找不到返回 None。

    目前只检查配置的默认路径 (DEFAULT_HOI4_PATH);
    自动扫描 Steam 库列表属于 M3 (公开发布准备)。
    """
    if os.path.isfile(os.path.join(DEFAULT_HOI4_PATH, TERRAIN_DEF_RELPATH)):
        return DEFAULT_HOI4_PATH
    return None


# 匹配图形地形条目: { ... color = { 索引列表 } ... texture = N ... }
# 条目体除 color 的大括号外不含其他大括号 ([^{}] 保证不会跨条目匹配);
# categories 块的条目没有 texture 字段, 不会被匹配。
_GFX_ENTRY_RE = re.compile(
    r"\{[^{}]*?color\s*=\s*\{([\d\s]+)\}[^{}]*?texture\s*=\s*(\d+)[^{}]*?\}",
    re.S,
)
_TYPE_RE = re.compile(r"type\s*=\s*(\w+)")


def parse_graphical_terrain(text: str) -> list[dict]:
    """解析 00_terrain.txt 的图形地形条目。

    返回 [{"type": "plains", "indices": [0], "texture": 1}, ...]。
    只认同时具备 color 和 texture 字段的条目 (即 terrain={} 块内容)。
    """
    text = re.sub(r"#[^\n]*", "", text)  # 去注释
    entries: list[dict] = []
    for m in _GFX_ENTRY_RE.finditer(text):
        type_m = _TYPE_RE.search(m.group(0))
        entries.append({
            "type": type_m.group(1) if type_m else "",
            "indices": [int(x) for x in m.group(1).split()],
            "texture": int(m.group(2)),
        })
    return entries


def parse_terrain_to_texture(text: str) -> dict[int, int]:
    """解析 00_terrain.txt 文本, 返回 {terrain.bmp 调色板索引: atlas 瓦片号}。

    一个条目的 color 可以列多个索引, 都映射到同一瓦片。
    texture = 255 (湖泊) 原样保留, 由合成器决定如何处理。
    """
    mapping: dict[int, int] = {}
    for e in parse_graphical_terrain(text):
        for idx in e["indices"]:
            mapping[idx] = e["texture"]
    return mapping


def parse_water_palette_indices(text: str) -> set[int]:
    """返回 terrain.bmp 中属于水体 (ocean/lakes) 的调色板索引集合。"""
    water: set[int] = set()
    for e in parse_graphical_terrain(text):
        if e["type"] in ("ocean", "lakes"):
            water.update(e["indices"])
    return water


def slice_atlas(atlas: np.ndarray, grid: int = ATLAS_GRID) -> np.ndarray:
    """把图集切成瓦片数组, 返回 (grid*grid, 高, 宽, 通道), 行优先排列。"""
    h, w = atlas.shape[:2]
    th, tw = h // grid, w // grid
    c = atlas.shape[2]
    tiles = atlas[: grid * th, : grid * tw].reshape(grid, th, grid, tw, c)
    return tiles.swapaxes(1, 2).reshape(grid * grid, th, tw, c)


class GameAssets:
    """惰性读取 + 进程内缓存的游戏资产容器。

    用法:
        assets = GameAssets()
        if not assets.available():
            ... 提示用户选择游戏目录, 或降级纯色渲染 ...
        tiles = assets.atlas_tiles()   # None = 该文件读取失败
    """

    def __init__(self, install_dir: str | None = None) -> None:
        self.install_dir = install_dir if install_dir else find_hoi4_install()
        self._cache: dict[str, object] = {}
        # 最近一次读取失败的原因, 供 UI 提示和排查
        self.last_error: str = ""

    def available(self) -> bool:
        return self.install_dir is not None

    # ─────────── 各资产 getter ───────────

    def terrain_to_texture(self) -> dict[int, int] | None:
        """调色板索引 → atlas 瓦片号 映射。"""
        return self._cached("terrain_to_texture", self._load_terrain_mapping)

    def atlas_tiles(self) -> np.ndarray | None:
        """地形材质瓦片 (16, 512, 512, 4) uint8。"""
        return self._cached(
            "atlas_tiles", lambda: self._load_dds_tiles(ATLAS_RELPATH))

    def atlas_normal_tiles(self) -> np.ndarray | None:
        """法线贴图瓦片 (16, 512, 512, 4) uint8。"""
        return self._cached(
            "atlas_normal_tiles", lambda: self._load_dds_tiles(ATLAS_NORMAL_RELPATH))

    def water_palette_indices(self) -> set[int] | None:
        """terrain.bmp 中水体 (ocean/lakes) 的调色板索引。"""
        def _load():
            path = self._abs(TERRAIN_DEF_RELPATH)
            if path is None:
                return None
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    return parse_water_palette_indices(f.read())
            except OSError as e:
                self.last_error = f"读取 {path} 失败: {e}"
                return None
        return self._cached("water_palette_indices", _load)

    def colormap_rgb(self) -> np.ndarray | None:
        """vanilla 区域色调图 (H, W, 3) uint8 (alpha 通道是城市灯光遮罩, 丢弃)。

        分辨率是 vanilla 地图的一半, 只配 vanilla 地图数据使用;
        自制地图的色调走本工具自己的 colormap 功能。
        """
        def _load():
            arr = self._read_dds(COLORMAP_RGB_RELPATH)
            return None if arr is None else arr[:, :, :3]
        return self._cached("colormap_rgb", _load)

    # ─────────── 内部实现 ───────────

    def _cached(self, key: str, loader):
        if key not in self._cache:
            self._cache[key] = loader()
        return self._cache[key]

    def _abs(self, relpath: str) -> str | None:
        if self.install_dir is None:
            self.last_error = "未找到 HOI4 安装目录"
            return None
        path = os.path.join(self.install_dir, relpath)
        if not os.path.isfile(path):
            self.last_error = f"游戏文件不存在: {path}"
            return None
        return path

    def _load_terrain_mapping(self) -> dict[int, int] | None:
        path = self._abs(TERRAIN_DEF_RELPATH)
        if path is None:
            return None
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                mapping = parse_terrain_to_texture(f.read())
        except OSError as e:
            self.last_error = f"读取 {path} 失败: {e}"
            return None
        if not mapping:
            self.last_error = f"{path} 中未找到图形地形定义"
            return None
        return mapping

    def _read_dds(self, relpath: str) -> np.ndarray | None:
        """读取 DDS 为 (H, W, 4) uint8, 失败返回 None。"""
        path = self._abs(relpath)
        if path is None:
            return None
        try:
            from PIL import Image
            with Image.open(path) as im:
                return np.asarray(im.convert("RGBA"))
        except Exception as e:  # PIL 解码失败种类繁多, 统一降级
            self.last_error = f"解码 {path} 失败: {e}"
            return None

    def _load_dds_tiles(self, relpath: str) -> np.ndarray | None:
        arr = self._read_dds(relpath)
        if arr is None:
            return None
        if arr.shape[0] % ATLAS_GRID or arr.shape[1] % ATLAS_GRID:
            self.last_error = f"{relpath} 尺寸 {arr.shape} 不是 {ATLAS_GRID}×{ATLAS_GRID} 网格"
            return None
        return slice_atlas(arr)
