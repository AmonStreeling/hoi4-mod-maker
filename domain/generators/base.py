"""
生成器统一协议 — "自动生成打底 + 手动精修"(路线 C) 的标准模子。

约定 (所有图层生成器共同遵守, 地形/高度/树木/城市/色调都照此实现):

1. **纯函数式**: generate() 只读 map_data, 返回一张完整尺寸的新数组,
   绝不直接修改项目数据 — 写入由命令层负责, 保证可撤销。
2. **参数化 + 种子**: 参数是 frozen dataclass, 自带 seed;
   同参数同种子结果可复现, "换一批"=换种子重新 generate。
3. **可选 mask**: 传入 bool 掩码时, 掩码外的像素保持原图层不变
   (局部重新生成/保护手动精修区域)。

接入 UI 的标准路径:
    generator.generate(map_data, params) → 写入命令 (如
    commands/map/generate_terrain.GenerateTerrainCommand) →
    cmd_history.execute() → 可撤销。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass(frozen=True)
class GeneratorParams:
    """生成器参数基类 — 至少有种子。"""
    seed: int = 0


class Generator(Protocol):
    """图层生成器协议。"""

    id: str             # 全局唯一, 如 "terrain_detail"
    target_layer: str   # 写入 MapData 的哪个数组属性, 如 "terrain_map"

    def default_params(self) -> GeneratorParams:
        """返回默认参数 (UI 初始值)。"""
        ...

    def generate(
        self,
        map_data,
        params: GeneratorParams,
        mask: np.ndarray | None = None,
    ) -> np.ndarray:
        """产出完整尺寸的新图层数组, 不修改 map_data。"""
        ...
