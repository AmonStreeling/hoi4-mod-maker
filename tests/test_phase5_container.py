"""
Phase 5 验收: 应用容器能创建 + Feature 全注册成功.
"""

import pytest


def test_container_creates_all_managers():
    from app.container import AppContainer
    c = AppContainer()
    assert c.state_mgr is not None
    assert c.country_mgr is not None
    assert c.continent_mgr is not None
    assert c.undo_mgr is not None
    assert c.command_bus is not None


def test_container_registers_all_map_features():
    from app.container import AppContainer
    c = AppContainer()
    assert c.map_feature_count() == 13
    ids = {f.id for f in c.features.by_category("map")}
    assert ids == {
        "map.land", "map.province", "map.terrain", "map.height",
        "map.state", "map.country", "map.river", "map.continent",
        "map.logistics", "map.colormap", "map.default_map",
        "map.strategic_region", "map.preview",
    }


def test_container_registers_10_content_features():
    from app.container import AppContainer
    c = AppContainer()
    assert c.content_feature_count() == 10
    ids = {f.id for f in c.features.by_category("content")}
    expected = {
        "content.tech_tree", "content.focus_tree", "content.events",
        "content.decisions", "content.characters", "content.portraits",
        "content.oob", "content.namelist", "content.flags", "content.ideas",
    }
    assert ids == expected


def test_command_bus_integrates_with_container():
    from app.container import AppContainer
    from commands.base import Command

    class Noop(Command):
        label = "noop"
        def execute(self): pass
        def undo(self): pass

    c = AppContainer()
    c.command_bus.execute(Noop())
    assert c.command_bus.undo_depth() == 1
    c.command_bus.undo()
    assert c.command_bus.undo_depth() == 0
