"""CountryController 单元测试 — 信息/分配双模式。"""
import pytest
import numpy as np

from model.project import Project
from model.events import EventBus
from commands.history import CommandHistory
from controllers.country import CountryController


@pytest.fixture
def country_setup():
    """Project + CountryController: 2 省份 2 州, 1 个国家占州 1。"""
    bus = EventBus()
    project = Project(event_bus=bus)
    history = CommandHistory(event_bus=bus)

    project.map_data.province_map = np.array([
        [1, 1, 2, 2],
        [1, 1, 2, 2],
        [1, 1, 2, 2],
        [1, 1, 2, 2],
    ], dtype=np.int32)
    project.map_data.tile_map = np.ones((4, 4), dtype=np.uint8)

    project.state_mgr.create_state([1])   # State 1 ← 省份 1
    project.state_mgr.create_state([2])   # State 2 ← 省份 2

    ctrl = CountryController(project, history)
    ctrl.create_country("AAA", "Alpha", (10, 20, 30))
    project.country_mgr.assign_state(1, "AAA")
    return ctrl, project, history


def test_default_is_info_mode(country_setup):
    ctrl, _, _ = country_setup
    assert ctrl.assign_mode is False


def test_info_mode_click_selects_owner_not_reassign(country_setup):
    ctrl, project, _ = country_setup
    ctrl.create_country("BBB", "Beta", (40, 50, 60))
    project.country_mgr.assign_state(2, "BBB")
    ctrl.selected_country_tag = "AAA"

    ctrl.on_province_clicked(2)   # 信息模式点 BBB 的地

    # 只切换选中, 不改归属
    assert ctrl.selected_country_tag == "BBB"
    assert project.country_mgr.get_owner_of_state(2) == "BBB"


def test_assign_mode_click_assigns(country_setup):
    ctrl, project, _ = country_setup
    ctrl.selected_country_tag = "AAA"
    ctrl.set_assign_mode(True)

    ctrl.on_province_clicked(2)

    assert project.country_mgr.get_owner_of_state(2) == "AAA"


def test_assign_undo_returns_to_previous_owner(country_setup):
    ctrl, project, history = country_setup
    ctrl.create_country("BBB", "Beta", (40, 50, 60))
    project.country_mgr.assign_state(2, "BBB")
    ctrl.selected_country_tag = "AAA"
    ctrl.set_assign_mode(True)

    ctrl.on_province_clicked(2)   # BBB 的州 2 → AAA
    assert project.country_mgr.get_owner_of_state(2) == "AAA"

    history.undo()                # 撤销 → 归还 BBB
    assert project.country_mgr.get_owner_of_state(2) == "BBB"


def test_assign_mode_without_selection_does_nothing(country_setup):
    ctrl, project, _ = country_setup
    ctrl.selected_country_tag = ""
    ctrl.set_assign_mode(True)

    ctrl.on_province_clicked(2)

    assert project.country_mgr.get_owner_of_state(2) == ""


def test_deactivate_resets_assign_mode(country_setup):
    ctrl, _, _ = country_setup
    ctrl.set_assign_mode(True)
    ctrl.deactivate()
    assert ctrl.assign_mode is False
