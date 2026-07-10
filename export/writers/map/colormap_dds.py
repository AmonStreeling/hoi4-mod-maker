"""
map/terrain/colormap_rgb_cityemissivemask_a.dds 生成.

HOI4 zoom out 到战略视角时, 引擎用这张 2816x1024 的 DDS 作为"全球总览"背景纹理.
vanilla 文件画的是地球大陆 (北美/欧洲/非洲), 架空 MOD 不覆盖 → 用户缩远就看到地球.

格式: DDS, 2816x1024, 无压缩 BGRA8, 128 字节头.
RGB channel 存颜色, Alpha channel 存城市夜间灯光 mask (0 = 无灯, 255 = 亮城市).
灯光 mask 从 urban 地形自动点亮 (+光晕), 无 urban 地形时 alpha 全 0.

生成逻辑: 把 tile_map 从 5632x2048 降采样到 2816x1024, 陆地涂土色 / 海洋涂深蓝.
"""

from __future__ import annotations

import os
import struct

import numpy as np

from data.constants import TILE_LAND, TILE_SEA, TILE_LAKE

# 不在模块顶部固化 _DDS_WIDTH/_DDS_HEIGHT — 那样会绑定到 import 时的 MAP_WIDTH
# (5632), set_map_size 后不会更新, 导致 DDS 文件头与实际像素尺寸不符 → 损坏文件.
# 所有尺寸一律在函数内从 tile_map.shape 取.

# 默认颜色 (B, G, R, A) — DDS 字节顺序. 用户通过 ColormapSettings 覆盖.
_DEFAULT_COLOR_LAND = (60, 90, 95, 0)
_DEFAULT_COLOR_SEA  = (90, 55, 30, 0)
_DEFAULT_COLOR_LAKE = (140, 110, 70, 0)

# 按 terrain type 的战略视图着色 (B, G, R, A) — 提高饱和度让色块明显
_TERRAIN_TYPE_COLORS: dict[str, tuple[int, int, int, int]] = {
    "plains":   (60, 140, 110, 0),   # 鲜亮草绿
    "forest":   (40, 95, 50, 0),     # 深森林绿
    "hills":    (75, 130, 150, 0),   # 黄褐 (饱和度提高)
    "mountain": (110, 115, 120, 0),  # 灰褐 (亮一点, 山顶配雪)
    "desert":   (80, 175, 215, 0),   # 沙黄 (饱和度提高)
    "marsh":    (60, 100, 70, 0),    # 沼泽暗绿
    "jungle":   (30, 90, 45, 0),     # 丛林深绿
    "urban":    (90, 100, 110, 0),   # 城市灰
    "ocean":    (90, 55, 30, 0),
    "lakes":    (180, 130, 80, 0),
}


def _build_dds_header(width: int, height: int) -> bytes:
    """构造 128 字节 DDS 文件头 (无压缩 BGRA8, 单 mipmap)."""
    # 匹配 vanilla 参数: flags=0x100f, pitch=width*4, pf_flags=0x41 (ALPHAPIXELS|RGB)
    header = bytearray(128)
    header[0:4] = b"DDS "
    struct.pack_into("<I", header, 4, 124)           # dwSize
    struct.pack_into("<I", header, 8, 0x100f)        # dwFlags (CAPS+HEIGHT+WIDTH+PITCH+PIXELFORMAT)
    struct.pack_into("<I", header, 12, height)       # dwHeight
    struct.pack_into("<I", header, 16, width)        # dwWidth
    struct.pack_into("<I", header, 20, width * 4)    # dwPitchOrLinearSize
    struct.pack_into("<I", header, 24, 0)            # dwDepth
    struct.pack_into("<I", header, 28, 1)            # dwMipMapCount
    # dwReserved1[11] — 44 字节 0
    # ddspf at offset 76
    struct.pack_into("<I", header, 76, 32)           # dwSize
    struct.pack_into("<I", header, 80, 0x41)         # dwFlags (ALPHAPIXELS | RGB)
    struct.pack_into("<I", header, 84, 0)            # dwFourCC
    struct.pack_into("<I", header, 88, 32)           # dwRGBBitCount
    struct.pack_into("<I", header, 92, 0x00FF0000)   # R mask
    struct.pack_into("<I", header, 96, 0x0000FF00)   # G mask
    struct.pack_into("<I", header, 100, 0x000000FF)  # B mask
    struct.pack_into("<I", header, 104, 0xFF000000)  # A mask
    struct.pack_into("<I", header, 108, 0x1000)      # dwCaps (TEXTURE)
    return bytes(header)


def write_water_colormap_dds(
    tile_map: np.ndarray,
    output_dir: str,
) -> None:
    """生成 map/terrain/colormap_water_0/1/2.dds — 海洋颜色, 三个 MIP 级别.

    渐变公式在 domain/water_colormap (预览海面同款):
    距陆地 < 80px 青绿 → 深蓝, 远海纯深蓝.
    """
    try:
        from domain.water_colormap import water_color_rgb
        rgb = water_color_rgb(tile_map)
    except ImportError:
        # 没 scipy 退回纯色
        return _write_water_colormap_solid(tile_map, output_dir)

    rgb = np.clip(rgb, 0, 255).astype(np.uint8)
    full_pixels = np.empty((*tile_map.shape, 4), dtype=np.uint8)
    full_pixels[..., 0] = rgb[..., 2]   # B
    full_pixels[..., 1] = rgb[..., 1]   # G
    full_pixels[..., 2] = rgb[..., 0]   # R
    full_pixels[..., 3] = 255

    out_dir = os.path.join(output_dir, "map", "terrain")
    os.makedirs(out_dir, exist_ok=True)

    src_h, src_w = tile_map.shape
    for level, divisor in enumerate([2, 4, 8]):
        dds_w = src_w // divisor
        dds_h = src_h // divisor
        if dds_w < 1 or dds_h < 1:
            break
        ds = full_pixels[::divisor, ::divisor][:dds_h, :dds_w]
        header = _build_dds_header(dds_w, dds_h)
        with open(os.path.join(out_dir, f"colormap_water_{level}.dds"), "wb") as f:
            f.write(header)
            f.write(np.ascontiguousarray(ds).tobytes())


def _write_water_colormap_solid(tile_map, output_dir):
    """scipy 不可用时的 fallback (纯色)."""
    water_color = np.array([110, 70, 30, 255], dtype=np.uint8)
    out_dir = os.path.join(output_dir, "map", "terrain")
    os.makedirs(out_dir, exist_ok=True)
    src_h, src_w = tile_map.shape
    for level, divisor in enumerate([2, 4, 8]):
        dds_w = src_w // divisor
        dds_h = src_h // divisor
        if dds_w < 1 or dds_h < 1:
            break
        pixels = np.empty((dds_h, dds_w, 4), dtype=np.uint8)
        pixels[:] = water_color
        header = _build_dds_header(dds_w, dds_h)
        with open(os.path.join(out_dir, f"colormap_water_{level}.dds"), "wb") as f:
            f.write(header)
            f.write(pixels.tobytes())


def write_fow_dds(
    tile_map: np.ndarray,
    output_dir: str,
    height_map: np.ndarray | None = None,
) -> None:
    """生成 map/terrain/fow_rgb_waterspec_a.dds — 战争迷雾明暗 + 水面反射.

    通道语义 (2026-07-10 解码 vanilla 实测, wiki 无文档):
    - RGB: 迷雾下的灰度明暗, 陆地亮 (~150, 随高度增亮) / 海洋暗 (~64)
    - A:   水面反射强度, 海 ~46 / 陆 ~21
    尺寸为 provinces.bmp 的一半. 不覆盖会回退 vanilla 的地球形状贴图,
    自定义地图上反光和迷雾底纹按地球海陆分布走 → 错位.
    """
    ds = tile_map[::2, ::2]
    h, w = ds.shape
    sea = (ds == TILE_SEA) | (ds == 0)
    lake = ds == TILE_LAKE
    land = ~sea & ~lake

    gray = np.full((h, w), 64.0, dtype=np.float32)
    gray[lake] = 80.0
    if height_map is not None and height_map.shape == tile_map.shape:
        ds_height = height_map[::2, ::2].astype(np.float32)
        # 海平面 (~95) 附近 ~130, 高山 ~185 — 对齐 vanilla 陆地 140~170 区间
        gray[land] = np.clip(130.0 + (ds_height[land] - 95.0) * 0.4, 120.0, 185.0)
    else:
        gray[land] = 150.0
    alpha = np.where(land, 21.0, 46.0).astype(np.float32)

    # 轻度模糊: 海岸过渡自然 (vanilla 低分辨率手绘无硬边)
    try:
        from scipy.ndimage import gaussian_filter
        gray = gaussian_filter(gray, sigma=1.5)
        alpha = gaussian_filter(alpha, sigma=1.5)
    except ImportError:
        pass

    pixels = np.empty((h, w, 4), dtype=np.uint8)
    pixels[..., :3] = np.clip(gray, 0, 255).astype(np.uint8)[..., None]
    pixels[..., 3] = np.clip(alpha, 0, 255).astype(np.uint8)

    out_dir = os.path.join(output_dir, "map", "terrain")
    os.makedirs(out_dir, exist_ok=True)
    header = _build_dds_header(w, h)
    with open(os.path.join(out_dir, "fow_rgb_waterspec_a.dds"), "wb") as f:
        f.write(header)
        f.write(pixels.tobytes())


def write_colormap_dds(
    tile_map: np.ndarray,
    output_dir: str,
    settings=None,
    terrain_map: np.ndarray | None = None,
    height_map: np.ndarray | None = None,
) -> None:
    """从 tile_map + terrain_map 生成 map/terrain/colormap_rgb_cityemissivemask_a.dds.

    - tile_map: (MAP_HEIGHT, MAP_WIDTH) uint8, TILE_LAND/SEA/LAKE
    - terrain_map: (MAP_HEIGHT, MAP_WIDTH) uint8, 可选, 有则按地形着色
    - settings: ColormapSettings 实例, None 用默认色
    - 输出: 降采样 BGRA8 DDS
    """
    # 不再校验与全局 MAP_WIDTH/HEIGHT 一致 — 以 tile_map.shape 为权威，
    # HOI4 只要求 256 倍数, 不限定预设尺寸.

    # 决定三色
    if settings is not None:
        color_land = settings.land.to_bgra()
        color_sea = settings.sea.to_bgra()
        color_lake = settings.lake.to_bgra()
    else:
        color_land = _DEFAULT_COLOR_LAND
        color_sea = _DEFAULT_COLOR_SEA
        color_lake = _DEFAULT_COLOR_LAKE

    downsampled = tile_map[::2, ::2]
    h, w = downsampled.shape
    pixels = np.empty((h, w, 4), dtype=np.uint8)
    pixels[:] = color_sea
    land_mask = downsampled == TILE_LAND
    lake_mask = downsampled == TILE_LAKE
    urban_mask = np.zeros((h, w), dtype=bool)  # 城市灯光 (alpha 通道) 用

    if terrain_map is not None and terrain_map.shape == tile_map.shape:
        # 按地形类型着色陆地
        from data.terrain_types import PALETTE_TO_TYPE
        ds_terrain = terrain_map[::2, ::2]
        # 先填默认陆地色
        pixels[land_mask] = color_land
        # 再按地形类型覆盖
        for idx in np.unique(ds_terrain[land_mask]):
            ttype = PALETTE_TO_TYPE.get(int(idx))
            if ttype and ttype in _TERRAIN_TYPE_COLORS:
                tmask = land_mask & (ds_terrain == idx)
                pixels[tmask] = _TERRAIN_TYPE_COLORS[ttype]
                if ttype == "urban":
                    urban_mask |= tmask
    else:
        pixels[land_mask] = color_land

    pixels[lake_mask] = color_lake

    # ── 高度调制 + 雪山 + 海岸沙滩 (有 heightmap 才做) ──
    if height_map is not None and height_map.shape == tile_map.shape:
        ds_height = height_map[::2, ::2].astype(np.float32)
        # 1. 雪山: 高度 > 200 → 渐进白
        snow_t = np.clip((ds_height - 200) / 40.0, 0, 1)  # 200→0, 240→1
        snow_color = np.array([240, 240, 250], dtype=np.float32)
        # 2. 高度调亮: 100 (海岸)=1.0, 200=1.25, 50=0.8 (深谷暗)
        brightness = np.clip(0.7 + (ds_height - 95) / 200.0, 0.65, 1.35)
        rgb = pixels[..., :3].astype(np.float32)
        rgb = rgb * brightness[..., None]
        # 雪混入
        rgb[land_mask] = (
            rgb[land_mask] * (1 - snow_t[land_mask, None])
            + snow_color * snow_t[land_mask, None]
        )
        pixels[..., :3] = np.clip(rgb, 0, 255).astype(np.uint8)
        # 3. 海岸沙滩: 距海 < 4px 的陆地 → 浅黄
        try:
            from scipy.ndimage import distance_transform_edt
            sea_full = (tile_map == TILE_SEA) | (tile_map == 0)
            dist_to_sea_full = distance_transform_edt(~sea_full).astype(np.float32)
            ds_dist = dist_to_sea_full[::2, ::2]
            beach_t = np.clip(1 - ds_dist / 4.0, 0, 1) * 0.6  # 4px 内 60% 沙色
            beach = np.array([130, 200, 235], dtype=np.float32)  # BGR 浅沙色
            rgb = pixels[..., :3].astype(np.float32)
            mix = land_mask & (ds_dist < 4)
            rgb[mix] = rgb[mix] * (1 - beach_t[mix, None]) + beach * beach_t[mix, None]
            pixels[..., :3] = np.clip(rgb, 0, 255).astype(np.uint8)
        except ImportError:
            pass

    # ── 消除"拼贴"硬边：给陆地加噪声 + gaussian 模糊 ──
    # 为什么：vanilla colormap 是画家手绘 + 噪声，几千种颜色；
    # 我们按地形类型填纯色只有 7 种颜色，atlas 材质叠上去就是硬边块。
    # 加噪声 + 轻度模糊后，相邻地形之间有渐变带，肉眼看不到"拼贴"。
    try:
        from scipy.ndimage import gaussian_filter
        rng = np.random.default_rng(42)
        # 只对陆地 BGR 三通道做抖动 + 模糊（alpha 保持 0）
        rgb = pixels[..., :3].astype(np.float32)
        noise = rng.integers(-12, 13, size=rgb.shape, dtype=np.int16).astype(np.float32)
        rgb = rgb + noise
        for c in range(3):
            rgb[..., c] = gaussian_filter(rgb[..., c], sigma=2.5)
        rgb = np.clip(rgb, 0, 255).astype(np.uint8)
        pixels[..., :3] = rgb
        # 模糊会让颜色渗进海洋/湖泊，重新覆盖回纯海色/湖色（海面另有 colormap_water 渲染）
        pixels[downsampled == TILE_SEA] = color_sea
        pixels[lake_mask] = color_lake
    except ImportError:
        pass  # scipy 不在时退回硬边版本

    # ── 城市夜间灯光: alpha 通道, urban 地形处发光 + 模糊光晕 ──
    # (wiki: "more opacity means stronger night lights"; 平铺灯光纹理
    #  citylights_rgb_snowmask_a 用 vanilla 的即可, 位置全由这个 mask 定)
    alpha = np.zeros((h, w), dtype=np.float32)
    alpha[urban_mask] = 200.0
    if urban_mask.any():
        try:
            from scipy.ndimage import gaussian_filter
            # 城市本体保持全亮, 光晕取模糊结果的最大值 (小城不被模糊削暗)
            alpha = np.maximum(alpha, gaussian_filter(alpha, sigma=2.0))
        except ImportError:
            pass
    # 灯光只留在陆地上 (模糊会渗进海面)
    alpha[~land_mask] = 0.0
    pixels[..., 3] = np.clip(alpha, 0, 255).astype(np.uint8)

    # 写文件
    out_dir = os.path.join(output_dir, "map", "terrain")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "colormap_rgb_cityemissivemask_a.dds")
    # 用动态尺寸 — 与 pixels (= downsampled.shape) 一致
    header = _build_dds_header(w, h)
    with open(out_path, "wb") as f:
        f.write(header)
        f.write(pixels.tobytes())
