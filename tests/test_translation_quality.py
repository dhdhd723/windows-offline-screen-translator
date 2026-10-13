"""Independent report-validation probes; no model or desktop is invoked."""
from __future__ import annotations

import pytest

from screen_translator.inference.translation import quality
from screen_translator.inference.translation.quality import QualityCase, check_case


def test_trusted_title_checks_reject_the_original_model_mistranslation():
    case = QualityCase("title", "STARDEW VALLEY", "required", exact="星露谷物语")
    assert check_case(case, "星露谷物语") == []
    assert "exact_trusted_output_mismatch" in check_case(case, "标准瓦利")


@pytest.mark.parametrize("translation", ["新建 加载 退出", "新建\n加载", "新建\n加载\n\n退出"])
def test_checks_reject_flattened_missing_and_extra_output_rows(translation):
    case = QualityCase("menu", "NEW\nLOAD\nEXIT", "layout")
    assert "row_count_mismatch" in check_case(case, translation)
    assert check_case(case, "新建\n加载\n退出") == []


def test_meaning_keywords_must_be_in_their_own_row():
    case = QualityCase("dialogue", "The train leaves.\nTake the blue door.", "expanded",
                       row_groups=((("火车", "列车"), ("离开", "出发")),
                                   (("蓝",), ("门",))))
    assert check_case(case, "列车出发了。\n走蓝色的门。") == []
    errors = check_case(case, "走蓝色的门。\n列车出发了。")
    assert "required_meaning_missing_in_row_1" in errors
    assert "required_meaning_missing_in_row_2" in errors
    assert "row_count_mismatch" not in errors


def test_forbidden_terms_are_rejected_even_when_required_keywords_are_present():
    case = QualityCase("place", "Welcome to Stardew Valley.", "expanded",
                       row_groups=((("欢迎",), ("星露谷",)),),
                       forbidden=("星露谷物语", "STANDARD VALLEY"))
    assert check_case(case, "欢迎来到星露谷。") == []
    assert "forbidden_word_present" in check_case(case, "欢迎来到星露谷物语。")
    assert "forbidden_word_present" in check_case(case, "欢迎来到星露谷 standard valley。")


def _case(name):
    return next(case for case in quality.QUALITY_CASES if case.name == name)


def _wrong_rows(case):
    return "\n".join("WRONG OUTPUT" for _ in case.source.strip().splitlines())


class FakeTranslator:
    """Pass only trusted outputs/layout; deliberately fail broader meaning."""

    def __init__(self, overrides=None):
        self.overrides = overrides or {}
        self.calls = []

    def translate(self, source, direction):
        self.calls.append((source, direction))
        case = next(case for case in quality.QUALITY_CASES
                    if case.source == source and case.direction == direction)
        if case.name in self.overrides:
            return self.overrides[case.name]
        if case.exact is not None:
            return case.exact
        if case.scope == "layout":
            return "星露谷物语\n" + "\n".join(
                "WRONG OUTPUT" for _ in case.source.strip().splitlines()[1:])
        return _wrong_rows(case)

    def model_id(self, direction):
        return "quality-fake-" + direction


def _baseline(translator, case):
    if case.scope == "layout":
        return "标准瓦利\n" + "\n".join(
            "WRONG OUTPUT" for _ in case.source.strip().splitlines()[1:])
    return _wrong_rows(case)


def test_evaluator_separates_trusted_scope_from_broader_meaning_and_observations(monkeypatch):
    monkeypatch.setattr(quality, "_raw_model_translation", _baseline)
    translator = FakeTranslator()
    report = quality.evaluate_translation_quality(translator)
    required_count = sum(case.scope == "required" for case in quality.QUALITY_CASES)
    layout_count = sum(case.scope == "layout" for case in quality.QUALITY_CASES)
    expanded_count = sum(case.scope == "expanded" for case in quality.QUALITY_CASES)
    observation_count = sum(case.scope == "observation" for case in quality.QUALITY_CASES)

    assert report["passed_required_scope"] is True
    assert report["required"] == {"passed": required_count, "total": required_count}
    assert report["layout"] == {"passed": layout_count, "total": layout_count}
    assert expanded_count > 0
    assert report["expanded_keyword_checks"] == {"passed": 0, "total": expanded_count}
    assert report["observation_count"] == observation_count > 0
    observations = [case for case in report["cases"] if case["scope"] == "observation"]
    assert all(case["checks_passed"] is None for case in observations)
    expanded = [case for case in report["cases"] if case["scope"] == "expanded"]
    assert all(case["checks_passed"] is False and case["errors"] for case in expanded)
    assert all(case["unmatched_model_output_unchanged"] is True for case in expanded)
    assert report["unmatched_regression"]["passed"] == report["unmatched_regression"]["total"]
    assert report["actual_games_tested"] is report["desktop_captured"] is False
    assert len(translator.calls) == len(quality.QUALITY_CASES)


def test_evaluator_required_scope_fails_when_a_trusted_title_is_wrong(monkeypatch):
    monkeypatch.setattr(quality, "_raw_model_translation", _baseline)
    report = quality.evaluate_translation_quality(FakeTranslator({"title-upper": "标准瓦利"}))
    failed = next(case for case in report["cases"] if case["name"] == "title-upper")
    assert failed["checks_passed"] is False
    assert "exact_trusted_output_mismatch" in failed["errors"]
    assert report["required"]["passed"] == report["required"]["total"] - 1
    assert report["passed_required_scope"] is False


def test_evaluator_detects_changed_unmatched_model_output_even_if_meaning_improves(monkeypatch):
    monkeypatch.setattr(quality, "_raw_model_translation", _baseline)
    report = quality.evaluate_translation_quality(FakeTranslator({
        "offline-english": "翻译支持离线运行。"}))
    changed = next(case for case in report["cases"] if case["name"] == "offline-english")
    assert check_case(_case("offline-english"), changed["translation"]) == []
    assert changed["unmatched_model_output_unchanged"] is False
    assert "unmatched_model_output_changed" in changed["errors"]
    assert report["unmatched_regression"]["passed"] == report["unmatched_regression"]["total"] - 1
    assert report["passed_required_scope"] is False


def test_evaluator_detects_changed_ordinary_rows_beneath_a_correct_title(monkeypatch):
    monkeypatch.setattr(quality, "_raw_model_translation", _baseline)
    report = quality.evaluate_translation_quality(FakeTranslator({
        "title-menu-rows": "星露谷物语\n新建\n加载\n退出"}))
    menu = next(case for case in report["cases"] if case["name"] == "title-menu-rows")
    assert "ordinary_menu_rows_changed" in menu["errors"]
    assert report["layout"]["passed"] == report["layout"]["total"] - 1
    assert report["passed_required_scope"] is False
