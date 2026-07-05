"""LandPage 参考底图卡片改版 — 新控件与新信号。"""

import pytest
from PyQt5.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def page(qapp):
    from features.map.land.page import LandPage
    return LandPage()


def test_open_vanilla_signal(page):
    fired = []
    page.open_vanilla_requested.connect(lambda: fired.append(1))
    page._open_vanilla_btn.click()
    assert fired == [1]


def test_vanilla_has_scale_slider(page):
    assert page._vanilla_ref_scale_slider.minimum() == 10
    assert page._vanilla_ref_scale_slider.maximum() == 500
    assert page._vanilla_ref_scale_slider.value() == 100
    # 铺满按钮已删除（强制拉伸变形, 用户裁定移除）
    assert not hasattr(page, "_vanilla_ref_fit_btn")
    assert not hasattr(page, "_ref_fit_btn")


def test_adjust_toggle_emits_and_enables_radios(page):
    got = []
    page.ref_adjust_toggled.connect(got.append)
    assert not page._adjust_custom_radio.isEnabled()   # 平时置灰
    page._ref_adjust_btn.setChecked(True)
    assert got == [True]
    assert page._adjust_custom_radio.isEnabled()
    page._ref_adjust_btn.setChecked(False)
    assert got == [True, False]
    assert not page._adjust_custom_radio.isEnabled()


def test_adjust_target_radio_emits_only_selected(page):
    page._ref_adjust_btn.setChecked(True)
    got = []
    page.ref_adjust_target_changed.connect(got.append)
    page._adjust_vanilla_radio.setChecked(True)
    assert got == ["vanilla"]                          # custom 的 toggled(False) 不发
    assert page.current_adjust_target() == "vanilla"


def test_set_ref_scale_percent_no_signal_loop(page):
    fired = []
    page._vanilla_ref_scale_slider.valueChanged.connect(fired.append)
    page.set_ref_scale_percent("vanilla", 150)
    assert page._vanilla_ref_scale_slider.value() == 150
    assert fired == []                                 # blockSignals 生效
    assert page._vanilla_ref_scale_label.text() == "150%"


def test_set_ref_adjust_checked_syncs_button(page):
    page._ref_adjust_btn.setChecked(True)
    page.set_ref_adjust_checked(False)                 # 模拟画布 ESC 退出
    assert not page._ref_adjust_btn.isChecked()
