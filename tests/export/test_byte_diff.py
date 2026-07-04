"""
Phase 2 字节 diff 测试 — 保证拆 mod_exporter 前后输出完全一致.

策略:
1. 首次运行: 用小测试工程导出 MOD, 记录所有文件的 sha256 到 baseline.json
2. 后续运行: 再次导出, 比对所有文件哈希, 任一不匹配则测试失败
3. 重构 mod_exporter 时, 这个测试是安全网

⚠ 已知假失败源: 导出内容里有一部分是从游戏本体抄写清洗的 vanilla 文件
(如 common/decisions/categories/*)。**Steam 更新游戏后这些文件会变**,
byte-diff 会在没有任何代码改动的情况下失败。确认失败文件都是 vanilla
派生内容且游戏目录 mtime 晚于基线时间, 则删除 baseline.json 重建即可
(2026-06-12 和 2026-07-04 各发生过一次, 排查记录见项目记忆)。
"""

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pytest

from domain.managers.state import StateManager
from domain.managers.country import CountryManager
from domain.managers.continent import ContinentManager
from export.mod_exporter import export_full_mod
from data.constants import MAP_WIDTH, MAP_HEIGHT, TILE_LAND, TILE_SEA


BASELINE_FILE = Path(__file__).parent.parent / "fixtures" / "export_baseline.json"


def _build_tiny_project():
    """构造一个迷你测试工程: 全陆地 + 2 省份 + 1 state + 1 国家."""
    tile_map = np.full((MAP_HEIGHT, MAP_WIDTH), TILE_LAND, dtype=np.uint8)
    # 边框海 (避免 coastal 报错)
    tile_map[0, :] = TILE_SEA
    tile_map[-1, :] = TILE_SEA
    tile_map[:, 0] = TILE_SEA
    tile_map[:, -1] = TILE_SEA

    province_map = np.zeros((MAP_HEIGHT, MAP_WIDTH), dtype=np.int32)
    # 省 1: 左半陆, 省 2: 右半陆, 省 3: 边框海
    mid = MAP_WIDTH // 2
    province_map[1:-1, 1:mid] = 1
    province_map[1:-1, mid:-1] = 2
    province_map[tile_map == TILE_SEA] = 3

    state_mgr = StateManager()
    from domain.managers.state import StateData
    s1 = StateData(id=1, name="TestState", provinces=[1, 2],
                   manpower=100000, category="town", owner_tag="TST")
    state_mgr._states[1] = s1
    state_mgr._province_to_state = {1: 1, 2: 1}
    state_mgr._next_id = 2

    country_mgr = CountryManager()
    country_mgr.create_country("TST", "TestLand", (100, 100, 200))
    country_mgr.set_capital("TST", 1)
    country_mgr.assign_state(1, "TST")

    continent_mgr = ContinentManager()

    return tile_map, province_map, state_mgr, country_mgr, continent_mgr


def _hash_all_files(output_dir: str) -> dict[str, str]:
    """递归收集 output_dir 下所有文件, 返回 {相对路径: sha256}."""
    result: dict[str, str] = {}
    root = Path(output_dir)
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = str(path.relative_to(root)).replace(os.sep, "/")
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        result[rel] = h.hexdigest()
    return result


def _run_export_to_tmp() -> dict[str, str]:
    tile_map, province_map, state_mgr, country_mgr, continent_mgr = _build_tiny_project()
    tmpdir = tempfile.mkdtemp(prefix="hoi4_export_test_")
    try:
        export_full_mod(
            tile_map=tile_map,
            province_map=province_map,
            output_dir=tmpdir,
            mod_name="ByteDiffTest",
            tag="TST",
            state_mgr=state_mgr,
            country_mgr=country_mgr,
            continent_mgr=continent_mgr,
        )
        return _hash_all_files(tmpdir)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.slow
def test_export_byte_diff_matches_baseline():
    """导出的所有文件哈希必须与 baseline.json 完全一致.

    第一次运行 (baseline 不存在): 生成 baseline.json, 测试跳过.
    后续运行: 比对.
    """
    current = _run_export_to_tmp()

    if not BASELINE_FILE.exists():
        BASELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(BASELINE_FILE, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2, sort_keys=True)
        pytest.skip(f"Baseline 已创建: {BASELINE_FILE} ({len(current)} 个文件)")

    with open(BASELINE_FILE, "r", encoding="utf-8") as f:
        baseline: dict[str, str] = json.load(f)

    missing = set(baseline.keys()) - set(current.keys())
    extra = set(current.keys()) - set(baseline.keys())
    changed = {
        k for k in baseline.keys() & current.keys()
        if baseline[k] != current[k]
    }

    msg_parts = []
    if missing:
        msg_parts.append(f"缺失 {len(missing)} 个文件: {sorted(missing)[:5]}")
    if extra:
        msg_parts.append(f"多出 {len(extra)} 个文件: {sorted(extra)[:5]}")
    if changed:
        msg_parts.append(f"{len(changed)} 个文件内容变了: {sorted(changed)[:5]}")

    assert not msg_parts, " | ".join(msg_parts)
