"""
ApplyGeneratorCommand — 生成器产出的通用可撤销写入。

任何符合 domain/generators/base.py 协议的生成器, 其结果都经此命令
写入 MapData 的目标图层 (terrain 例外: 它要同步 provincial_terrain,
继续走 GenerateTerrainCommand)。

快照策略与 GenerateTerrainCommand 一致: 全图存整张旧图层,
mask 模式只存掩码内像素。原地写入 ([:] / 掩码赋值), 保持画布
对同一数组的别名引用有效。
"""

from __future__ import annotations

import numpy as np

from commands.base import Command


class ApplyGeneratorCommand(Command):
    """把生成器的新图层数组写入 MapData, 可撤销。"""

    label = "应用生成器"

    def __init__(
        self,
        map_data,
        target_layer: str,
        new_array: np.ndarray,
        mask: np.ndarray | None = None,
        label: str | None = None,
    ) -> None:
        """
        参数:
            map_data: 地图数据对象
            target_layer: 要写入的图层属性名 (如 "height_map");
                          不存在会直接 AttributeError — 故意不兜底,
                          写错名字必须当场炸而不是悄悄没生效
            new_array: 生成器产出的完整尺寸新数组
            mask: bool 掩码, 只写掩码内 (None = 全图)
            label: 撤销历史里的显示名
        """
        if label:
            self.label = label
        self._map_data = map_data
        self._target_layer = target_layer
        self._mask = mask

        current = getattr(map_data, target_layer)
        if mask is not None:
            self._new_values = new_array[mask].copy()
            self._old_values = current[mask].copy()
        else:
            self._new_array = new_array.copy()
            self._old_array = current.copy()

    def execute(self) -> None:
        arr = getattr(self._map_data, self._target_layer)
        if self._mask is not None:
            arr[self._mask] = self._new_values
        else:
            arr[:] = self._new_array

    def undo(self) -> None:
        arr = getattr(self._map_data, self._target_layer)
        if self._mask is not None:
            arr[self._mask] = self._old_values
        else:
            arr[:] = self._old_array
