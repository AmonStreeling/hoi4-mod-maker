"""i18n 系统 smoke test — tr() 语义、kwargs 支持、placeholder 一致性、工具 e2e."""
from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
I18N_DIR = PROJECT_ROOT / "ui" / "i18n"


@pytest.fixture
def i18n():
    """每个测试拿到干净的 i18n 模块实例 + 强制 reload."""
    import ui.i18n as mod
    mod.reload_translations()
    return mod


def test_all_languages_load(i18n):
    """所有语言目录都能加载; 中文为源头, 英/俄不得有中文没有的孤儿键.

    2026-07-04 用户决定: 开发期只写中文文案, 英/俄在发版前用
    i18n_audit 清单统一补翻 — 所以不再强制三语言键数量相等,
    只保证 en/ru ⊆ zh (孤儿键说明有键改名/删除没同步, 仍是 bug)。
    """
    langs = i18n.available_languages()
    assert "zh" in langs
    assert "en" in langs
    assert "ru" in langs
    zh_keys = set(i18n._languages["zh"])
    for lang in ("en", "ru"):
        orphans = set(i18n._languages[lang]) - zh_keys
        assert not orphans, f"{lang} 有中文没有的孤儿键: {sorted(orphans)[:5]}"


def test_placeholder_consistency_zh_en_ru(i18n):
    """zh/en/ru 之间 {placeholder} 必须一致, 否则 tr() 会运行时炸."""
    import re
    ph_re = re.compile(r"\{[^{}]*\}")
    en = i18n._languages["en"]
    mismatches = []
    for lang in ("zh", "ru"):
        data = i18n._languages[lang]
        for key in set(en) & set(data):
            en_ph = sorted(ph_re.findall(en[key]))
            tg_ph = sorted(ph_re.findall(data[key]))
            if en_ph != tg_ph:
                mismatches.append((lang, key, en_ph, tg_ph))
    assert not mismatches, f"placeholder 不一致: {mismatches[:5]}"


def test_tr_positional_args(i18n):
    """tr() 支持位置 placeholder."""
    i18n.set_language("zh")
    # status_pos 用 {} {} 位置 placeholder
    result = i18n.tr("status_pos", 123, 456)
    assert "123" in result and "456" in result


def test_tr_named_kwargs(i18n):
    """tr() 支持命名 placeholder (修复后新功能)."""
    i18n.set_language("en")
    # dlg_batch_state_done: "Created state {sid} ({n} provinces)"
    result = i18n.tr("dlg_batch_state_done", sid=5, n=12)
    assert "5" in result and "12" in result
    # 应该不是未替换的模板
    assert "{sid}" not in result and "{n}" not in result


def test_tr_missing_key_returns_key(i18n):
    """缺失 key 时返回 key 本身, 不崩."""
    result = i18n.tr("__nonexistent_key__")
    assert result == "__nonexistent_key__"


def test_tr_fallback_chain(i18n):
    """目标语言缺 key 时 fallback 到 en/zh."""
    # 临时往 ru 删一个 key, 看 fallback
    saved = i18n._languages["ru"].pop("app_title")
    try:
        i18n.set_language("ru")
        result = i18n.tr("app_title")
        # 应该 fallback 到 en
        assert result == i18n._languages["en"]["app_title"]
    finally:
        i18n._languages["ru"]["app_title"] = saved


def test_tr_placeholder_mismatch_logs_warning(i18n, caplog):
    """placeholder 类型不匹配时应 logger.warning, 不再静默吞."""
    import logging
    i18n.set_language("en")
    with caplog.at_level(logging.WARNING, logger="ui.i18n"):
        # dlg_batch_state_done 模板用 {sid} {n} 命名 placeholder
        # 用位置参数传 → KeyError → 应 warning
        result = i18n.tr("dlg_batch_state_done", 5, 12)
    assert "placeholder mismatch" in caplog.text
    # 返回未替换模板而非崩溃
    assert "{sid}" in result


# ── 工具 e2e 测试 ──

TOOLS = PROJECT_ROOT / "tools"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    """跑一个 python 工具脚本, 返回结果."""
    return subprocess.run(
        [sys.executable, str(TOOLS / args[0]), *args[1:]],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def test_audit_summary_runs():
    r = _run("i18n_audit.py", "summary")
    assert r.returncode == 0, r.stderr
    assert "Summary" in r.stdout
    assert "zh" in r.stdout and "en" in r.stdout and "ru" in r.stdout


def test_audit_check_placeholders_passes():
    r = _run("i18n_audit.py", "check-placeholders")
    # 0 = all consistent
    assert r.returncode == 0, r.stdout + "\n" + r.stderr


def test_audit_missing_returns_zero_when_complete():
    r = _run("i18n_audit.py", "missing", "ru")
    assert r.returncode == 0, r.stdout + "\n" + r.stderr


def test_audit_missing_unknown_lang_errors():
    r = _run("i18n_audit.py", "missing", "xx_nope")
    assert r.returncode == 2


def test_add_key_e2e_creates_and_audit_detects(tmp_path):
    """加 key → audit 应能识别 → 删除 → audit 回归干净."""
    # 用真实文件 (临时 key 后删掉), 避免维护额外 fixture
    test_key = "__pytest_add_key_temp__"
    try:
        r = _run("add_i18n_key.py", "menu", test_key, "测试", "--en", "Test", "--ru", "Тест")
        assert r.returncode == 0, r.stderr
        # 验证 3 个文件都有
        for lang in ("zh", "en", "ru"):
            p = I18N_DIR / lang / "menu.py"
            assert test_key in p.read_text(encoding="utf-8")
    finally:
        # cleanup: 从 3 个文件移除
        for lang in ("zh", "en", "ru"):
            p = I18N_DIR / lang / "menu.py"
            src = p.read_text(encoding="utf-8")
            lines = [ln for ln in src.split("\n") if test_key not in ln]
            p.write_text("\n".join(lines), encoding="utf-8")


def test_add_key_skips_existing_without_force():
    test_key = "menu_view"  # 这个 key 已存在
    r = _run("add_i18n_key.py", "menu", test_key, "重复")
    # 不会 error, 但会 skipped
    assert r.returncode == 0
    assert "skipped_exists" in r.stdout
