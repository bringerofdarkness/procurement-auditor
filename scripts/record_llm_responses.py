"""Call Gemini for sample packs with no saved response, for use in replay mode.

Safe to run again: packs already saved are skipped.
Run from the project root: python -m scripts.record_llm_responses
"""

import time
from pathlib import Path

from core.llm import call_gemini, has_saved_response, save_response
from core.pdf_reader import read_pdf_text

PACKS = Path(__file__).parent.parent / "task1-procurement"
PAUSE_SECONDS = 5  # Stay inside free-tier rate limits.


def main() -> None:
    for path in sorted(PACKS.glob("supplier-pack-*.pdf")):
        text, error = read_pdf_text(path.read_bytes())
        if error:
            print(f"{path.name}: skipped, {error}")
        elif has_saved_response(text):
            print(f"{path.name}: already saved")
        else:
            try:
                save_response(text, call_gemini(text))
                print(f"{path.name}: saved")
            except Exception as error:  # Keep going, so a rerun only retries what failed.
                print(f"{path.name}: failed, {type(error).__name__}")
            time.sleep(PAUSE_SECONDS)


if __name__ == "__main__":
    main()
