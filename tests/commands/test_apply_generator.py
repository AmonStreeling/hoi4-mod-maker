"""
ApplyGeneratorCommand 测试 — 全图/掩码写入与撤销, 原地修改保持别名。
"""

from types import SimpleNamespace

import numpy as np
import pytest

from commands.map.apply_generator import ApplyGeneratorCommand


def _md():
    return SimpleNamespace(height_map=np.full((8, 8), 50, dtype=np.uint8))


def test_full_apply_and_undo():
    md = _md()
    alias = md.height_map                       # 模拟画布持有的别名
    new = np.full((8, 8), 200, dtype=np.uint8)

    cmd = ApplyGeneratorCommand(md, "height_map", new, label="测试生成")
    cmd.execute()
    assert np.all(md.height_map == 200)
    assert alias is md.height_map               # 原地写入, 别名不断

    cmd.undo()
    assert np.all(md.height_map == 50)
    assert cmd.label == "测试生成"


def test_masked_apply_and_undo():
    md = _md()
    new = np.full((8, 8), 200, dtype=np.uint8)
    mask = np.zeros((8, 8), dtype=bool)
    mask[:4] = True

    cmd = ApplyGeneratorCommand(md, "height_map", new, mask=mask)
    cmd.execute()
    assert np.all(md.height_map[:4] == 200)
    assert np.all(md.height_map[4:] == 50)

    cmd.undo()
    assert np.all(md.height_map == 50)


def test_wrong_layer_name_fails_loudly():
    """图层名写错必须当场炸, 不能悄悄没生效。"""
    with pytest.raises(AttributeError):
        ApplyGeneratorCommand(_md(), "hieght_map",
                              np.zeros((8, 8), dtype=np.uint8))
