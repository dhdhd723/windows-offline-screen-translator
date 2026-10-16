"""Fixed Japanese fixtures, not game or general quality certification."""
from __future__ import annotations

import time

from ...core.text import choose_direction


# Kept independent of any output dictionary; these are observations of NMT.
CASES = (
    ("greeting", "こんにちは。", (("你好", "您好"),)),
    ("thanks", "ありがとう。", (("谢",),)),
    ("open-door", "ドアを開けてください。", (("开",), ("门",))),
    ("do-not-open", "このドアを開けないでください。", (("门",), ("不要", "别", "勿", "不得", "不能"))),
    ("found-key", "鍵を見つけました。", (("钥匙",), ("找", "发现"))),
    ("not-enough-medicine", "薬が足りません。", (("药",), ("不够", "不足", "不多"))),
    ("ten-minutes", "残り時間は10分です。", (("10", "十"), ("分钟",))),
    ("wait-here", "ここで待ってください。", (("等",), ("这里", "此", "这儿"))),
    ("quit-game", "ゲームを終了しますか？", (("游戏",), ("结束", "退出", "关闭", "终止"))),
    ("collect-three", "アイテムを3個集めてください。", (("3", "三"), ("收集", "搜集", "集齐"))),
    ("enemy-right", "敵は右側にいます。", (("敌",), ("右",))),
    ("enemy-left", "敵は左側にいます。", (("敌",), ("左",))),
    ("cannot-save", "今はセーブできません。", (("不能", "无法", "不可", "没法"), ("保存", "存档", "储存"))),
    ("ready-notify", "準備ができたら教えてください。", (("准备",), ("告诉", "通知", "告知"))),
    ("no-enemies", "敵はいません。", (("敌",), ("没有", "无", "不在"))),
    ("weapon-positive", "武器を持っています。", (("武器",), ("有", "拿", "携带", "持"))),
    ("weapon-negative", "武器を持っていません。", (("武器",), ("没有", "没带", "不持", "未携带"))),
)
OCR_CASES = ("こんにちは。", "ありがとう。", "このドアを開けないでください。", "残り時間は10分です。",
             "敵は右側にいます。", "ゲームを終了しますか？")


def evaluate_japanese(ocr, translator, text_fixture) -> dict:
    cases = []
    for name, source, groups in CASES:
        started = time.perf_counter()
        translation = translator.translate(source, "ja-zh")
        cases.append({"name": name, "source": source, "translation": translation,
                      "translation_ms_cold_or_warm": round((time.perf_counter() - started) * 1000, 2),
                      "functional_passed": bool(translation.strip()),
                      "keyword_passed": all(any(word in translation for word in group) for group in groups)})
    images = []
    for source in OCR_CASES:
        started = time.perf_counter()
        recognized = ocr.recognize(text_fixture(source))
        ocr_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        translation = translator.translate(recognized.text, "ja-zh")
        images.append({"source": source, "ocr": recognized.text, "translation": translation,
                       "ocr_ms": round(ocr_ms, 2),
                       "translation_ms": round((time.perf_counter() - started) * 1000, 2),
                       "exact_ocr": recognized.text.replace(" ", "") == source,
                       "functional_passed": bool(translation.strip())
                           and choose_direction(recognized.text, "ja-zh") == "ja-zh"})
    passed = all(case["functional_passed"] for case in cases + images)
    return {"passed": passed, "model_id": translator.model_id("ja-zh"), "cases": cases,
            "ocr_pipeline_cases": images, "fixed_keyword_checks": {
                "passed": sum(case["keyword_passed"] for case in cases), "total": len(cases)},
            "exact_ocr_checks": {"passed": sum(case["exact_ocr"] for case in images), "total": len(images)},
            "functional_checks_only": True, "actual_game_tested": False,
            "boundary": "Fixed text and synthetic horizontal images. Functional pass is not semantic accuracy; "
                        "keyword failures remain visible. No user screen or user settings were accessed."}
