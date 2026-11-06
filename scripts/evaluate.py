"""Print the score on the 10 sample packs.

Run from the project root: python -m scripts.evaluate [live|replay|offline]
"""

import json
import sys
from pathlib import Path

from core.graph import run_audit
from core.llm import LlmMode
from core.models import FieldStatus, Terms

ROOT = Path(__file__).parent.parent
PACKS = ROOT / "task1-procurement"
EXPECTED = json.loads((ROOT / "data" / "expected_verdicts.json").read_text(encoding="utf-8"))


def main() -> None:
    mode = LlmMode(sys.argv[1]) if len(sys.argv) > 1 else LlmMode.REPLAY
    correct = 0
    for file_name, expected in EXPECTED.items():
        report = run_audit((PACKS / file_name).read_bytes(), file_name, llm_mode=mode)
        verdict = report.system_verdict.value
        correct += verdict == expected

        mark = "OK " if verdict == expected else "BAD"
        print(f"{mark} {file_name}: {verdict} | {report.llm_note}")
        for name in Terms.model_fields:
            field = getattr(report.terms, name)
            if field.status == FieldStatus.UNCLEAR:
                print(f"      unclear {name}: {field.note}")

    print(f"\nScore: {correct}/{len(EXPECTED)} ({mode.value} mode)")


if __name__ == "__main__":
    main()
