"""Fixed public-text quality probes; no desktop, user text or network access.

Required title/credit corrections, unchanged-model regressions and broader
semantic observations have separate totals. Keyword checks are deliberately
not a claim of general translation accuracy.
"""
from __future__ import annotations

from dataclasses import dataclass
import time

from ...core.game_terms import GAME_TERMS_VERSION, translate_known_game_line


@dataclass(frozen=True)
class QualityCase:
    name: str
    source: str
    scope: str
    exact: str | None = None
    # For each row, every group needs at least one acceptable word/phrase.
    row_groups: tuple[tuple[tuple[str, ...], ...], ...] = ()
    forbidden: tuple[str, ...] = ()
    direction: str = "en-zh"


QUALITY_CASES = (
    QualityCase("title-upper", "STARDEW VALLEY", "required", "星露谷物语"),
    QualityCase("title-case", "Stardew Valley", "required", "星露谷物语"),
    QualityCase("title-lower", "stardew valley", "required", "星露谷物语"),
    QualityCase("title-mixed", "StArDeW VaLlEy", "required", "星露谷物语"),
    QualityCase("title-spacing", "  Stardew   Valley  ", "required", "星露谷物语"),
    QualityCase("hollow-title", "HOLLOW KNIGHT", "required", "空洞骑士"),
    QualityCase("spire-title", "Slay the Spire", "required", "杀戮尖塔"),
    QualityCase("credits-header", "Stardew Valley created by:", "required", "《星露谷物语》制作："),
    QualityCase("credits-known-author", "Created by Eric Barone", "required", "制作者：Eric Barone"),
    QualityCase("credits-inline", 'Stardew Valley - developed by ConcernedApe.', "required",
                "《星露谷物语》由 ConcernedApe 制作"),
    QualityCase("credits-two-rows", 'Stardew Valley created by:\nEric Barone "ConcernedApe"',
                "required", '《星露谷物语》制作：\nEric Barone "ConcernedApe"'),
    QualityCase("title-menu-rows", "STARDEW VALLEY\nNEW\nLOAD\nEXIT", "layout",
                row_groups=((("星露谷物语",),), (), (), ())),
    QualityCase("plain-menu", "NEW\nLOAD\nEXIT", "expanded",
                row_groups=((("新",),), (("加载", "载入", "读取"),), (("退出", "离开"),))),
    QualityCase("place-welcome", "Welcome to Stardew Valley.", "expanded",
                row_groups=((("欢迎",), ("星露谷",)),), forbidden=("星露谷物语", "标准瓦利")),
    QualityCase("place-home", "I live in Stardew Valley.", "expanded",
                row_groups=((("住", "居住"), ("星露谷",)),), forbidden=("星露谷物语", "标准瓦利")),
    QualityCase("known-inline", "I am playing Hollow Knight tonight.", "expanded",
                row_groups=((("空洞骑士",), ("今晚", "今天晚上"), ("玩", "游玩")),)),
    QualityCase("ordinary-words", "The pipes release steam.\nThe iron gate is covered in rust.\nOpen the portal.",
                "expanded", row_groups=((("蒸汽", "蒸气"),), (("锈", "生锈"),),
                                        (("门户", "入口", "传送门", "通道"),))),
    QualityCase("two-row-dialogue", "The train leaves in 10 minutes.\nTake the blue door.", "expanded",
                row_groups=((("火车", "列车"), ("10", "十"), ("分钟",), ("离开", "出发", "开出")),
                            (("蓝",), ("门",), ("走", "通过", "从", "经过", "进入")))),
    QualityCase("offline-english", "The translation works offline.", "expanded",
                row_groups=((("翻译",), ("离线", "脱机")),)),
    QualityCase("offline-chinese", "屏幕翻译支持离线运行。", "expanded",
                row_groups=((("screen",), ("offline",)),), direction="zh-en"),
    QualityCase("unknown-names", "My name is Zorvella.\nMeet Qeltrix at the old bridge.", "observation"),
)


def check_case(case: QualityCase, translation: str) -> list[str]:
    errors = []
    if not translation.strip():
        errors.append("empty_translation")
    if case.exact is not None and translation != case.exact:
        errors.append("exact_trusted_output_mismatch")
    rows = translation.splitlines()
    if len(rows) != len(case.source.strip().splitlines()):
        errors.append("row_count_mismatch")
    folded = translation.casefold()
    if any(token.casefold() in folded for token in case.forbidden):
        errors.append("forbidden_word_present")
    if case.row_groups:
        if len(rows) != len(case.row_groups):
            errors.append("meaning_rows_mismatch")
        else:
            for index, (row, groups) in enumerate(zip(rows, case.row_groups), 1):
                if not all(any(word.casefold() in row.casefold() for word in alternatives)
                           for alternatives in groups):
                    errors.append(f"required_meaning_missing_in_row_{index}")
    return errors


def _raw_model_translation(translator, case: QualityCase) -> str:
    """Reference the unchanged model on these short fixed rows only.

    This is intentionally a diagnostic, not a second runtime translation path.
    Each fixture row fits the existing model token budget; fail rather than
    introduce a subtly different truncation or long-input policy here.
    """
    translator._initialize(case.direction)
    tokenizer = translator._tokenizers[case.direction]
    rows = []
    for row in case.source.strip().splitlines():
        if not row.strip():
            rows.append("")
            continue
        if len(tokenizer.encode(row)) > 192:
            raise ValueError("Quality fixture exceeds the native input budget")
        rows.append(translator._translate_chunk(row, case.direction))
    return "\n".join(rows).strip()


def evaluate_translation_quality(translator) -> dict:
    results = []
    output_policy = getattr(translator, "quality_policy_id", "")
    for case in QUALITY_CASES:
        baseline = _raw_model_translation(translator, case)
        started = time.perf_counter()
        translation = translator.translate(case.source, case.direction)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        errors = check_case(case, translation)
        source_rows = case.source.strip().splitlines()
        # Ordinary rows must retain their whole input context and raw output.
        no_override = all(translate_known_game_line(row, case.direction) is None for row in source_rows)
        unchanged = translation == baseline if no_override else None
        # Raw outputs remain visible as an observation. The v1 quality tests
        # required exact raw equality because only whole-line titles changed.
        # A declared, independently tested script/segmentation/term policy now
        # intentionally changes ordinary outputs; do not call that a failure
        # solely because it differs. Row/meaning/title checks still apply.
        if unchanged is False and not output_policy:
            errors.append("unmatched_model_output_changed")
        if case.scope == "layout":
            ordinary_rows_equal = translation.splitlines()[1:] == baseline.splitlines()[1:]
            if not ordinary_rows_equal and not output_policy:
                errors.append("ordinary_menu_rows_changed")
        results.append({"name": case.name, "source": case.source, "direction": case.direction,
                        "scope": case.scope, "model_id": translator.model_id(case.direction),
                        "baseline_without_terms": baseline, "translation": translation,
                        "translation_ms_warm": elapsed_ms, "errors": errors,
                        "checks_passed": not errors if case.scope != "observation" else None,
                        "unmatched_model_output_unchanged": unchanged})
    def totals(scope):
        selected = [item for item in results if item["scope"] == scope]
        return {"passed": sum(item["checks_passed"] is True for item in selected), "total": len(selected)}
    required, layout, expanded = (totals(scope) for scope in ("required", "layout", "expanded"))
    unaffected = [item for item in results if item["unmatched_model_output_unchanged"] is not None]
    regression_passed = bool(output_policy) or all(item["unmatched_model_output_unchanged"] for item in unaffected)
    return {"passed_required_scope": required["passed"] == required["total"]
            and layout["passed"] == layout["total"] and regression_passed,
            "game_terms_version": GAME_TERMS_VERSION, "required": required, "layout": layout,
            "output_policy_id": output_policy,
            "raw_output_comparison_observational": bool(output_policy),
            "expanded_keyword_checks": expanded,
            "unmatched_regression": {"passed": sum(item["unmatched_model_output_unchanged"] for item in unaffected),
                                     "total": len(unaffected)},
            "observation_count": sum(item["scope"] == "observation" for item in results),
            "cases": results, "actual_games_tested": False, "desktop_captured": False,
            "limits": "Fixed plain-text fixtures; keyword/row checks are not general semantic accuracy. "
            "Unknown names and inline/place terms have no blanket protection."}
