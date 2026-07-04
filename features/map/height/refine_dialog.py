"""
RefineDialog — 局部精修高度图参数对话框。

含强度滑块 + 3 个开关 + 种子 + 实时预览。
确认时把算好的新 height 通过回调或返回值给调用者（外部用 RefineHeightRegionCommand push undo）。
"""
from __future__ import annotations

import numpy as np
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QSlider, QCheckBox, QSpinBox, QPushButton, QDialogButtonBox,
)

from commands.map.refine_height_region import RefineParams
from services.terrain_service import refine_heightmap_region
from ui.i18n import tr
from ui.styles import _LABEL_STYLE, _DIM_LABEL_STYLE, _SLIDER_STYLE, _SPINBOX_STYLE


class RefineDialog(QDialog):
    """局部精修参数对话框。

    调用方需要：
    1. 在打开前 snapshot 当前 height_map（以便取消时恢复、预览时覆写）
    2. 连接 preview_updated 信号 → 更新 canvas 显示
    3. accept() 后读 self.params 和 self.new_height_map 构造 Command
    """

    preview_updated = pyqtSignal(np.ndarray)  # (H,W) uint8

    def __init__(
        self,
        parent,
        height_map: np.ndarray,
        mask: np.ndarray,
        tile_map: np.ndarray,
    ) -> None:
        super().__init__(parent)
        self._original = height_map.copy()
        self._mask = mask
        self._tile_map = tile_map
        self._preview_enabled = True
        self._new_height: np.ndarray = height_map.copy()

        self.setWindowTitle(tr("refine_dlg_title"))
        self.setMinimumWidth(360)
        self._init_ui()

        # debounce 预览刷新（250ms，避免拖滑块时把自己卡住）
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(250)
        self._preview_timer.timeout.connect(self._refresh_preview)

        # 初次展开就跑一次
        self._schedule_preview()

    def _init_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(10)

        # 从零重新生成 (山链/平原/大陆架) — 勾上时下方精修控件全部禁用
        self._cb_regen = QCheckBox(tr("refine_dlg_regen"))
        self._cb_regen.setChecked(False)
        self._cb_regen.setToolTip(tr("refine_dlg_regen_tooltip"))
        self._cb_regen.toggled.connect(self._on_regen_toggled)
        self._cb_regen.toggled.connect(self._on_param_changed)
        lay.addWidget(self._cb_regen)

        # 强度滑块
        srow = QHBoxLayout()
        sl = QLabel(tr("refine_dlg_strength"))
        sl.setStyleSheet(_LABEL_STYLE)
        srow.addWidget(sl)
        self._strength_label = QLabel("50%")
        self._strength_label.setStyleSheet(_DIM_LABEL_STYLE)
        srow.addStretch()
        srow.addWidget(self._strength_label)
        lay.addLayout(srow)

        self._strength_slider = QSlider(Qt.Orientation.Horizontal)
        self._strength_slider.setRange(0, 100)
        self._strength_slider.setValue(50)
        self._strength_slider.setStyleSheet(_SLIDER_STYLE)
        self._strength_slider.valueChanged.connect(self._on_param_changed)
        self._strength_slider.valueChanged.connect(
            lambda v: self._strength_label.setText(f"{v}%")
        )
        lay.addWidget(self._strength_slider)

        # 三个开关
        self._cb_ridge = QCheckBox(tr("refine_dlg_ridge"))
        self._cb_ridge.setChecked(True)
        self._cb_ridge.toggled.connect(self._on_param_changed)
        lay.addWidget(self._cb_ridge)

        self._cb_erosion = QCheckBox(tr("refine_dlg_erosion"))
        self._cb_erosion.setChecked(True)
        self._cb_erosion.toggled.connect(self._on_param_changed)
        lay.addWidget(self._cb_erosion)

        self._cb_noise = QCheckBox(tr("refine_dlg_noise"))
        self._cb_noise.setChecked(False)
        self._cb_noise.toggled.connect(self._on_param_changed)
        lay.addWidget(self._cb_noise)

        # 收缩山脉（把画太大的山脉拉小）
        self._cb_shrink = QCheckBox(tr("refine_dlg_shrink"))
        self._cb_shrink.setChecked(False)
        self._cb_shrink.toggled.connect(self._on_param_changed)
        self._cb_shrink.toggled.connect(self._update_shrink_row_visible)
        lay.addWidget(self._cb_shrink)

        # 收缩距离（仅 shrink 开启时可见）
        self._shrink_row = QHBoxLayout()
        sd_label = QLabel(tr("refine_dlg_shrink_distance"))
        sd_label.setStyleSheet(_LABEL_STYLE)
        self._shrink_row.addWidget(sd_label)
        self._shrink_dist_label = QLabel("25px")
        self._shrink_dist_label.setStyleSheet(_DIM_LABEL_STYLE)
        self._shrink_row.addStretch()
        self._shrink_row.addWidget(self._shrink_dist_label)
        lay.addLayout(self._shrink_row)

        self._shrink_slider = QSlider(Qt.Orientation.Horizontal)
        self._shrink_slider.setRange(5, 100)
        self._shrink_slider.setValue(25)
        self._shrink_slider.setStyleSheet(_SLIDER_STYLE)
        self._shrink_slider.valueChanged.connect(
            lambda v: self._shrink_dist_label.setText(f"{v}px")
        )
        self._shrink_slider.valueChanged.connect(self._on_param_changed)
        lay.addWidget(self._shrink_slider)
        # 默认隐藏（只有勾上才显示）
        self._shrink_slider.setVisible(False)
        self._shrink_dist_label.setVisible(False)
        sd_label.setVisible(False)
        self._shrink_labels = [sd_label]

        # 种子
        seed_row = QHBoxLayout()
        sdl = QLabel(tr("refine_dlg_seed"))
        sdl.setStyleSheet(_LABEL_STYLE)
        seed_row.addWidget(sdl)
        self._seed_spin = QSpinBox()
        self._seed_spin.setRange(0, 99999)
        self._seed_spin.setValue(42)
        self._seed_spin.setStyleSheet(_SPINBOX_STYLE)
        self._seed_spin.valueChanged.connect(self._on_param_changed)
        seed_row.addWidget(self._seed_spin)
        rand_btn = QPushButton(tr("refine_dlg_randomize"))
        rand_btn.clicked.connect(self._randomize_seed)
        seed_row.addWidget(rand_btn)
        seed_row.addStretch()
        lay.addLayout(seed_row)

        # 实时预览勾选
        self._cb_preview = QCheckBox(tr("refine_dlg_preview"))
        self._cb_preview.setChecked(True)
        self._cb_preview.toggled.connect(self._on_preview_toggled)
        lay.addWidget(self._cb_preview)

        # 确定/取消
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _on_preview_toggled(self, on: bool) -> None:
        self._preview_enabled = on
        if on:
            self._schedule_preview()
        else:
            # 预览关闭 → 恢复原图显示
            self.preview_updated.emit(self._original)

    def _randomize_seed(self) -> None:
        import random
        self._seed_spin.setValue(random.randint(0, 99999))

    def _on_param_changed(self) -> None:
        if self._preview_enabled:
            self._schedule_preview()

    def _schedule_preview(self) -> None:
        self._preview_timer.start()

    def _update_shrink_row_visible(self, on: bool) -> None:
        self._shrink_slider.setVisible(on)
        self._shrink_dist_label.setVisible(on)
        for lbl in self._shrink_labels:
            lbl.setVisible(on)

    def _on_regen_toggled(self, on: bool) -> None:
        """重新生成模式下, 精修控件不适用 → 全部禁用防误解。"""
        for wdg in (self._strength_slider, self._cb_ridge, self._cb_erosion,
                    self._cb_noise, self._cb_shrink, self._shrink_slider):
            wdg.setEnabled(not on)

    def _refresh_preview(self) -> None:
        self._new_height = refine_heightmap_region(
            height_map=self._original,
            mask=self._mask,
            tile_map=self._tile_map,
            strength=self._strength_slider.value() / 100.0,
            enable_ridge=self._cb_ridge.isChecked(),
            enable_erosion=self._cb_erosion.isChecked(),
            enable_noise=self._cb_noise.isChecked(),
            enable_shrink=self._cb_shrink.isChecked(),
            shrink_distance=float(self._shrink_slider.value()),
            seed=int(self._seed_spin.value()),
            regenerate=self._cb_regen.isChecked(),
        )
        self.preview_updated.emit(self._new_height)

    # ─── 对外 API ───

    @property
    def params(self) -> RefineParams:
        return RefineParams(
            strength=self._strength_slider.value() / 100.0,
            enable_ridge=self._cb_ridge.isChecked(),
            enable_erosion=self._cb_erosion.isChecked(),
            enable_noise=self._cb_noise.isChecked(),
            enable_shrink=self._cb_shrink.isChecked(),
            shrink_distance=float(self._shrink_slider.value()),
            seed=int(self._seed_spin.value()),
            regenerate=self._cb_regen.isChecked(),
        )

    def reject(self) -> None:  # type: ignore[override]
        # 取消时广播原图，让画布恢复
        self.preview_updated.emit(self._original)
        super().reject()
