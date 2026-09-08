"""Explicit file-based CLI for one bounded cloud trial."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from core.engine import run_cycle
from core.pipeline import run_pipeline


def main() -> int:
    parser = argparse.ArgumentParser(description="AION bounded trial CLI")
    parser.add_argument("mode", choices=("single", "pipeline"))
    parser.add_argument(
        "--prompt-file",
        required=True,
        help="UTF-8 file containing the test task",
    )
    args = parser.parse_args()

    task = Path(args.prompt_file).read_text(encoding="utf-8")
    if args.mode == "single":
        state = run_cycle(task)
        result = {
            "status": state.get("status"),
            "answer": state.get("last_answer"),
            "execution": state.get("execution"),
        }
    else:
        result = run_pipeline(task)

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("status") in {"ok", "idle"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
