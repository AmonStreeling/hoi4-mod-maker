"""
RefineHeightRegionCommand — 局部精修高度图（支持 undo）。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from commands.base import Command
from domain.map_data import MapData
from services.terrain_service import refine_heightmap_region


@dataclass(frozen=True)
class RefineParams:
    """精修参数（对话框收集后传入 Command）。"""
    strength: float = 0.5
    enable_ridge: bool = True
    enable_erosion: bool = True
    enable_noise: bool = False
    enable_shrink: bool = False
    shrink_distance: float = 25.0
    seed: int = 42
    # True = 选区内从零重新生成真实感地势 (忽略上面的精修开关)
    regenerate: bool = False


class RefineHeightRegionCommand(Command):
    """把 refine_heightmap_region 的结果写入 map_data，支持 undo。"""

    label = "局部精修高度"

    def __init__(
        self,
        map_data: MapData,
        mask: np.ndarray,
        params: RefineParams,
    ) -> None:
        self._map_data = map_data
        self._mask = mask.copy()
        self._params = params
        self._old_heights: np.ndarray | None = None

    def execute(self) -> None:
        hm = self._map_data.height_map
        # 只备份 mask 内原值（省内存）
        self._old_heights = hm[self._mask].copy()
        new_hm = refine_heightmap_region(
            height_map=hm,
            mask=self._mask,
            tile_map=self._map_data.tile_map,
            strength=self._params.strength,
            enable_ridge=self._params.enable_ridge,
            enable_erosion=self._params.enable_erosion,
            enable_noise=self._params.enable_noise,
            enable_shrink=self._params.enable_shrink,
            shrink_distance=self._params.shrink_distance,
            seed=self._params.seed,
            regenerate=self._params.regenerate,
        )
        # 把 mask 内新值写回（mask 外已和原图相同）
        hm[self._mask] = new_hm[self._mask]

    def undo(self) -> None:
        if self._old_heights is not None:
            self._map_data.height_map[self._mask] = self._old_heights
