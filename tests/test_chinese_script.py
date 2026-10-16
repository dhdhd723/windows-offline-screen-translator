"""Offline script conversion tests, not translation-quality assertions."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import builtins
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from screen_translator.core import chinese_script
from screen_translator.core import _opencc_t2s_data as data


@pytest.mark.parametrize(("source", "expected"), [
    ("紅桶邀請你體驗令人心痛的恐怖，這一次是朋友。", "红桶邀请你体验令人心痛的恐怖，这一次是朋友。"),
    ("無論你單獨或團隊地經歷考驗", "无论你单独或团队地经历考验"),
    ("乾隆皇帝在乾清宮；乾燥的頭髮。", "乾隆皇帝在乾清宫；干燥的头发。"),
    ("理髮、頭髮、發展、發現", "理发、头发、发展、发现"),
    ("皇后、太后、後面、後來", "皇后、太后、后面、后来"),
    ("乾坤大挪移、乾坤一擲、乾坤、乾乾淨淨", "乾坤大挪移、乾坤一掷、乾坤、干干净净"),
    ("宮商角徵羽、變徵之音、徵收", "宫商角徵羽、变徵之音、征收"),
    ("藉此機會、憑藉着、狼藉、覆盆子、覆水難收", "借此机会、凭借着、狼藉、覆盆子、覆水难收"),
    ("於世成與於倫在這裡", "於世成与於伦在这里"),
    ("  紅桶\r\n\tInvite 2026 v0.1! ❤️\n漢字，標點。", "  红桶\r\n\tInvite 2026 v0.1! ❤️\n汉字，标点。"),
    ("Red Barrels / Murkoff: 體驗與發展", "Red Barrels / Murkoff: 体验与发展"),
    ("English stays: ABCxyz123 @Player_1 https://example.test/A?x=1", "English stays: ABCxyz123 @Player_1 https://example.test/A?x=1"),
    ("🌍🔥\t\r\n! ?. . 123", "🌍🔥\t\r\n! ?. . 123"),
    ("", ""),
    ("普通简体中文：开发商名称。", "普通简体中文：开发商名称。"),
    ("𠮷𫝈㑮㑯", "𠮷𫝈𫝈㑔"),
])
def test_script_examples_keep_phrases_and_non_han(source, expected):
    assert chinese_script.to_simplified(source) == expected


def test_all_official_character_rows_use_the_default_candidate():
    for source, expected in data.TS_CHARACTERS:
        assert chinese_script.to_simplified(source) == expected, source


def test_all_official_phrase_rows_remain_whole_not_recursively_converted():
    for source, expected in data.TS_PHRASES:
        assert chinese_script.to_simplified(source) == expected, source


def test_data_count_hash_and_cache_policy_are_pinned():
    assert len(data.TS_CHARACTERS) == 4113
    assert len(data.TS_PHRASES) == 278
    canonical = json.dumps([data.TS_CHARACTERS, data.TS_PHRASES], ensure_ascii=False,
                           separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    assert digest == data.CANONICAL_PAIRS_SHA256
    assert digest == "72f97b4327c93bdd767896bab5f3f78b380ab77d84ebf3112011e6bb29100d61"
    assert digest in chinese_script.SCRIPT_POLICY_ID
    assert "greedy-v1" in chinese_script.SCRIPT_POLICY_ID
    assert data.OPENCC_TAG == "ver.1.1.9"
    assert data.OPENCC_COMMIT == "556ed22496d650bd0b13b6c163be9814637970ae"


def test_latin_only_does_not_import_data_or_allocate_converter():
    # A fresh interpreter proves lazy import independently of test execution order.
    code = (
        "import sys; from screen_translator.core import chinese_script as c; "
        "assert 'screen_translator.core._opencc_t2s_data' not in sys.modules; "
        "assert c.to_simplified('Ctrl+Alt+R | ty np 2026') == 'Ctrl+Alt+R | ty np 2026'; "
        "assert c.to_simplified('') == ''; assert c._converter is None; "
        "assert 'screen_translator.core._opencc_t2s_data' not in sys.modules"
    )
    child_env = os.environ.copy()
    child_env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    completed = subprocess.run(
        [sys.executable, "-B", "-c", code], env=child_env,
        capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_concurrent_first_use_builds_one_immutable_converter(monkeypatch):
    monkeypatch.setattr(chinese_script, "_converter", None)
    with ThreadPoolExecutor(max_workers=12) as pool:
        converters = list(pool.map(lambda _: chinese_script._load_converter(), range(96)))
        outputs = list(pool.map(chinese_script.to_simplified, ["乾隆與頭髮發展"] * 96))
    assert len({id(converter) for converter in converters}) == 1
    assert set(outputs) == {"乾隆与头发发展"}
    with pytest.raises(TypeError):
        converters[0].characters["髮"] = "wrong"
    with pytest.raises(TypeError):
        converters[0].phrases_by_start["乾"] = ()


@pytest.mark.parametrize("field,value", [
    ("TS_CHARACTERS", ()),
    ("TS_PHRASES", ()),
    ("CANONICAL_PAIRS_SHA256", "0" * 64),
    ("OPENCC_TAG", "unfixed-version"),
    ("OPENCC_COMMIT", "0" * 40),
])
def test_corrupted_dictionary_fails_explicitly_without_caching(monkeypatch, field, value):
    monkeypatch.setattr(chinese_script, "_converter", None)
    monkeypatch.setattr(data, field, value)
    with pytest.raises(RuntimeError, match="完整性校验失败"):
        chinese_script.to_simplified("漢字")
    assert chinese_script._converter is None


def test_phrase_does_not_join_across_whitespace_or_lines():
    assert chinese_script.to_simplified("乾 隆\n乾\t隆\n乾隆") == "干 隆\n干\t隆\n乾隆"


def test_missing_dictionary_fails_explicitly_without_silent_fallback(monkeypatch):
    original_import = builtins.__import__

    def missing_data(name, globals=None, locals=None, fromlist=(), level=0):
        if "_opencc_t2s_data" in (fromlist or ()):
            raise ImportError("Synthetic missing bundled module")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(chinese_script, "_converter", None)
    monkeypatch.setattr(builtins, "__import__", missing_data)
    with pytest.raises(RuntimeError, match="词典缺失"):
        chinese_script.to_simplified("繁體中文")
    assert chinese_script._converter is None


def test_conversion_is_not_a_semantic_rewrite():
    assert chinese_script.to_simplified("保持腳趾；紅桶") == "保持脚趾；红桶"
    assert chinese_script.to_simplified("這一次是朋友") == "这一次是朋友"


def test_official_defaults_are_one_pass_not_an_idempotence_promise():
    # Keep official defaults exactly. In particular, do not add synthetic
    # phrases solely to make already converted cache values safe to reprocess.
    once = chinese_script.to_simplified("乾清宮")
    assert once == "乾清宫"
    assert chinese_script.to_simplified(once) == "干清宫"
