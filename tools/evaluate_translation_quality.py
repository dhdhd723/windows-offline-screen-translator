"""Developer-only offline quality report from fixed public text, without UI."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models-dir", type=Path, default=PROJECT_ROOT / "models")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    from screen_translator.diagnostics import no_network
    from screen_translator.inference.translation.ctranslate2_engine import CTranslate2Engine
    from screen_translator.inference.translation.quality import evaluate_translation_quality
    with no_network() as attempts:
        report = evaluate_translation_quality(CTranslate2Engine(args.models_dir, cpu_threads=2))
    report["network_attempt_count"] = len(attempts)
    if attempts:
        report["passed_required_scope"] = False
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({key: value for key, value in report.items() if key != "cases"}, ensure_ascii=True))
    return 0 if report["passed_required_scope"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
