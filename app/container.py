"""
应用装配容器 — 创建所有 manager 和 Feature, 注入给 UI.

加新功能的步骤 (重构目标):
1. 在 features/map/ 或 features/content/ 建新目录
2. 新目录的 __init__.py 定义 Feature 子类
3. 在本文件的 _register_map_features / _register_content_features 加一行 register
4. 其他地方零改动

这是"单文件扩展点"的核心. 不要绕过它直接改 main_window / tool_panel.
"""

from __future__ import annotations

from app.registry import FeatureRegistry
from commands.bus import CommandBus

# domain managers
from domain.managers.state import StateManager
from domain.managers.country import CountryManager
from domain.managers.continent import ContinentManager
from domain.undo_manager import UndoManager

# map features
from features.map.land import LandFeature
from features.map.province import ProvinceFeature
from features.map.terrain import TerrainFeature
from features.map.height import HeightFeature
from features.map.state import StateFeature
from features.map.country import CountryFeature
from features.map.river import RiverFeature
from features.map.continent import ContinentFeature
from features.map.logistics import LogisticsFeature
from features.map.colormap import ColormapFeature
from features.map.default_map import DefaultMapFeature
from features.map.strategic_region import StrategicRegionFeature
from features.map.preview import PreviewFeature

# content features (2.0 空壳, 当前不在 UI 暴露)
from features.content.tech_tree import TechTreeFeature
from features.content.focus_tree import FocusTreeFeature
from features.content.events import EventsFeature
from features.content.decisions import DecisionsFeature
from features.content.characters import CharactersFeature
from features.content.portraits import PortraitsFeature
from features.content.oob import OobFeature
from features.content.namelist import NamelistFeature
from features.content.flags import FlagsFeature
from features.content.ideas import IdeasFeature


class AppContainer:
    """全局应用容器. MainWindow 持有一个实例, 从这里取所有服务."""

    def __init__(self) -> None:
        # ─── domain 数据管理器 ───
        self.state_mgr = StateManager()
        self.country_mgr = CountryManager()
        self.continent_mgr = ContinentManager()
        self.undo_mgr = UndoManager(max_steps=30)

        # ─── 命令总线 (新功能用, 旧 undo 继续用 UndoManager) ───
        self.command_bus = CommandBus(max_history=30)

        # ─── Feature 注册表 ───
        self.features = FeatureRegistry()
        self._register_map_features()
        self._register_content_features()

    def _register_map_features(self) -> None:
        """注册 1.0 地图功能."""
        for f in [
            LandFeature(),
            ProvinceFeature(),
            TerrainFeature(),
            HeightFeature(),
            StateFeature(),
            CountryFeature(),
            RiverFeature(),
            ContinentFeature(),
            LogisticsFeature(),
            ColormapFeature(),
            DefaultMapFeature(),
            StrategicRegionFeature(),
            PreviewFeature(),
        ]:
            self.features.register(f)

    def _register_content_features(self) -> None:
        """注册 2.0 内容功能 (目前全是空壳, UI 可选不暴露)."""
        for f in [
            TechTreeFeature(),
            FocusTreeFeature(),
            EventsFeature(),
            DecisionsFeature(),
            CharactersFeature(),
            PortraitsFeature(),
            OobFeature(),
            NamelistFeature(),
            FlagsFeature(),
            IdeasFeature(),
        ]:
            self.features.register(f)

    def map_feature_count(self) -> int:
        return len(self.features.by_category("map"))

    def content_feature_count(self) -> int:
        return len(self.features.by_category("content"))
