"""Run all deterministic information-cleaning trial fixtures."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .pipeline import evaluate_scenario, use_for_analysis, write_report

FIXTURE_FILE = Path(__file__).resolve().parent / "fixtures" / "scenarios.json"


def _expectation_errors(report: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if report["admission_token"] != expected.get("admission_token"):
        errors.append("admission_token")
    for field, value in expected.get("metrics", {}).items():
        if report["metrics"].get(field) != value:
            errors.append(f"metrics.{field}")
    return errors


def run_fixture_file(path: str | Path = FIXTURE_FILE) -> dict[str, Any]:
    fixture_path = Path(path)
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("fixture must contain a non-empty scenarios list")

    results = []
    for scenario in scenarios:
        report = evaluate_scenario(scenario)
        errors = _expectation_errors(report, scenario.get("expected", {}))
        results.append({
            "scenario_id": report["scenario_id"],
            "passed": not errors,
            "expectation_errors": errors,
            "report": report,
            "downstream": use_for_analysis(report),
        })

    return {
        "trial": "information_cleaning_v1",
        "fixture": fixture_path.name,
        "passed": all(item["passed"] for item in results),
        "scenarios": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the offline AION cleaning trial")
    parser.add_argument("--fixture", default=str(FIXTURE_FILE))
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    result = run_fixture_file(args.fixture)
    if args.output:
        write_report(result, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
