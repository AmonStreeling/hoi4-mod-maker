"""
game_assets 测试 — 映射表解析 / 图集切片 / 缺失降级。

真实游戏文件不进 CI: 集成测试仅在本机存在 HOI4 安装时运行。
"""

import json
import os

import numpy as np
import pytest

import services.game_assets as ga
from services.game_assets import (
    GameAssets, parse_terrain_to_texture, parse_graphical_terrain,
    parse_water_palette_indices, slice_atlas,
    TERRAIN_DEF_RELPATH, ATLAS_GRID,
)
from data.constants import DEFAULT_HOI4_PATH


# ═══════ 映射表解析 ═══════

SAMPLE = """
categories =  {
    unknown = {
        color = { 255 0 0 }
    }
    forest = {
        color = { 89 199 85 }
        movement_cost = 1.5
        buildings_max_level = {
            bunker = 4
        }
        units = {
            attack = -0.15
        }
    }
}

terrain = {
    terrain_0   = { type = plains  color = { 	0	 } texture = 1 }
    desert      = { type = desert  color = { 3 } texture = 9 }
    multi       = { type = plains  color = { 20 21 } texture = 7 }  # 多索引
    lake_14     = { type = lakes   color = { 14 } texture = 255 }
    ocean_15    = { type = ocean   color = { 15 } texture = 9 }
    city        = { type = urban   color = { 13 } texture = 10 spawn_city = yes }
}
"""


def test_parse_graphical_terrain_captures_type():
    """每个图形地形条目带回 type, 跨条目不会串。"""
    entries = parse_graphical_terrain(SAMPLE)
    by_texture = {e["texture"]: e["type"] for e in entries}
    assert by_texture[1] == "plains"
    assert by_texture[10] == "urban"
    assert len(entries) == 6


def test_parse_water_palette_indices():
    """ocean/lakes 类型的调色板索引被识别为水体。"""
    assert parse_water_palette_indices(SAMPLE) == {14, 15}


def test_parse_graphical_terrain_entries():
    """图形地形条目被解析, 多索引共享同一瓦片号。"""
    mapping = parse_terrain_to_texture(SAMPLE)
    assert mapping[0] == 1
    assert mapping[3] == 9
    assert mapping[20] == 7
    assert mapping[21] == 7
    assert mapping[13] == 10
    assert mapping[14] == 255  # 湖泊原样保留


def test_parse_ignores_categories_block():
    """categories 块的 RGB color (无 texture) 不会被误认成调色板索引。"""
    mapping = parse_terrain_to_texture(SAMPLE)
    # unknown 的 color = {255 0 0} 若被误解析, 索引 255 会出现在映射里
    assert 255 not in mapping
    assert 89 not in mapping  # forest 类别的 RGB 同理


# ═══════ 图集切片 ═══════

def test_slice_atlas_row_major_order():
    """8×8 图集按 4×4 网格切成 16 个 2×2 瓦片, 行优先排列。"""
    atlas = np.zeros((8, 8, 4), dtype=np.uint8)
    # 每个瓦片填充自己的行优先编号
    for row in range(4):
        for col in range(4):
            atlas[row * 2:(row + 1) * 2, col * 2:(col + 1) * 2] = row * 4 + col

    tiles = slice_atlas(atlas, grid=4)

    assert tiles.shape == (16, 2, 2, 4)
    for i in range(16):
        assert int(tiles[i].min()) == i == int(tiles[i].max())


# ═══════ 缺失降级 ═══════

def test_missing_install_dir_degrades_to_none(tmp_path):
    """目录不存在: available() False, 各 getter 返回 None 并记录原因。"""
    assets = GameAssets(install_dir=None)
    # find_hoi4_install 可能在本机找到真实安装, 强制指向空目录测降级
    assets.install_dir = None
    assert not assets.available()
    assert assets.terrain_to_texture() is None
    assert assets.atlas_tiles() is None
    assert assets.last_error != ""


def test_missing_file_degrades_to_none(tmp_path):
    """目录存在但缺文件: getter 返回 None 并记录路径。"""
    assets = GameAssets(install_dir=str(tmp_path))
    assert assets.terrain_to_texture() is None
    assert TERRAIN_DEF_RELPATH.split("/")[-1] in assets.last_error


# ═══════ 游戏目录持久化配置 ═══════

def _fake_game_dir(tmp_path):
    game = tmp_path / "game"
    (game / "common" / "terrain").mkdir(parents=True)
    (game / "common" / "terrain" / "00_terrain.txt").write_text(
        "terrain = { t = { type = plains color = { 0 } texture = 1 } }")
    return str(game)


def test_chosen_game_dir_persists_and_wins(tmp_path, monkeypatch):
    """选择目录写进配置 (保留已有键), 之后查找优先用它。"""
    cfg = tmp_path / "cfg.json"
    cfg.write_text('{"language": "zh"}', encoding="utf-8")
    monkeypatch.setattr(ga, "CONFIG_PATH", str(cfg))
    monkeypatch.setattr(ga, "_default_assets", None)
    game_dir = _fake_game_dir(tmp_path)

    assets = ga.set_default_install_dir(game_dir)

    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["hoi4_game_dir"] == game_dir
    assert data["language"] == "zh"          # 不丢其他设置
    assert ga.find_hoi4_install() == game_dir
    assert assets.install_dir == game_dir


def test_stale_config_game_dir_ignored(tmp_path, monkeypatch):
    """配置里的目录已失效 (游戏被卸载/盘符变了) → 忽略, 走默认查找。"""
    cfg = tmp_path / "cfg.json"
    cfg.write_text('{"hoi4_game_dir": "Z:/no/such/dir"}', encoding="utf-8")
    monkeypatch.setattr(ga, "CONFIG_PATH", str(cfg))
    assert ga._read_config_game_dir() is None


# ═══════ 真实游戏文件集成 (仅本机) ═══════

_HAS_GAME = os.path.isfile(os.path.join(DEFAULT_HOI4_PATH, TERRAIN_DEF_RELPATH))


@pytest.mark.skipif(not _HAS_GAME, reason="本机无 HOI4 安装")
def test_real_game_assets_load():
    """真实游戏资产: 映射表非空, 图集为 16 个 512×512 RGBA 瓦片。"""
    assets = GameAssets()
    assert assets.available()

    mapping = assets.terrain_to_texture()
    assert mapping is not None
    # vanilla 已知映射抽查 (00_terrain.txt 行 324/331)
    assert mapping[0] == 1    # 平原
    assert mapping[6] == 11   # 山地

    tiles = assets.atlas_tiles()
    assert tiles is not None
    assert tiles.shape == (ATLAS_GRID * ATLAS_GRID, 512, 512, 4)

    normals = assets.atlas_normal_tiles()
    assert normals is not None
    assert normals.shape == tiles.shape
