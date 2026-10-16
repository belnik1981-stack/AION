"""Run the deterministic Evidence Object / Claim Object v2 trial."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from .validator import ANALYSIS_ONLY, DENIED, evaluate_bundle, load_bundle, write_report


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
VALID_BUNDLE = FIXTURE_DIR / "valid_bundle.json"
ADVERSARIAL_CASES = FIXTURE_DIR / "adversarial_cases.json"


def _parent_and_key(document: Any, path: list[Any]) -> tuple[Any, Any]:
    if not path:
        raise ValueError("mutation path cannot be empty")
    current = document
    for component in path[:-1]:
        if isinstance(component, int):
            if not isinstance(current, list) or not 0 <= component < len(current):
                raise ValueError("invalid mutation list path")
        elif not isinstance(component, str) or not isinstance(current, dict) or component not in current:
            raise ValueError("invalid mutation object path")
        current = current[component]
    return current, path[-1]


def apply_mutations(document: dict[str, Any], mutations: list[dict[str, Any]]) -> dict[str, Any]:
    result = copy.deepcopy(document)
    for mutation in mutations:
        if set(mutation) not in ({"op", "path"}, {"op", "path", "value"}):
            raise ValueError("unknown mutation fields")
        operation = mutation["op"]
        path = mutation["path"]
        if operation not in {"add", "remove", "replace"} or not isinstance(path, list):
            raise ValueError("invalid mutation")
        parent, key = _parent_and_key(result, path)
        if isinstance(parent, list):
            if type(key) is not int or not 0 <= key < len(parent):
                raise ValueError("invalid mutation list target")
        elif isinstance(parent, dict):
            if not isinstance(key, str):
                raise ValueError("invalid mutation object target")
        else:
            raise ValueError("invalid mutation parent")

        if operation == "remove":
            if isinstance(parent, dict):
                if key not in parent:
                    raise ValueError("cannot remove missing field")
                del parent[key]
            else:
                parent.pop(key)
        elif operation == "replace":
            if isinstance(parent, dict) and key not in parent:
                raise ValueError("cannot replace missing field")
            parent[key] = copy.deepcopy(mutation["value"])
        else:
            if isinstance(parent, dict) and key in parent:
                raise ValueError("cannot add existing field")
            parent[key] = copy.deepcopy(mutation["value"])
    return result


def run_trial() -> dict[str, Any]:
    valid_bundle, base_dir = load_bundle(VALID_BUNDLE)
    valid_first = evaluate_bundle(valid_bundle, base_dir)
    valid_second = evaluate_bundle(valid_bundle, base_dir)
    valid_passed = (
        valid_first == valid_second
        and valid_first["status"] == "valid"
        and valid_first["admission_token"] == ANALYSIS_ONLY
        and valid_first["execution_authorized"] is False
    )

    cases_payload = json.loads(ADVERSARIAL_CASES.read_text(encoding="utf-8"))
    case_results = []
    for case in cases_payload["cases"]:
        mutated = apply_mutations(valid_bundle, case["mutations"])
        report = evaluate_bundle(mutated, base_dir)
        error_codes = sorted({item["code"] for item in report["errors"]})
        claim_reasons = sorted(
            {
                reason
                for claim in report["claims"]
                for reason in claim.get("reasons", [])
            }
        )
        if "expected_error" in case:
            passed = (
                report["status"] == "invalid"
                and report["admission_token"] == DENIED
                and report["execution_authorized"] is False
                and case["expected_error"] in error_codes
            )
        else:
            passed = (
                report["status"] == "valid"
                and report["admission_token"] == DENIED
                and report["execution_authorized"] is False
                and case["expected_claim_reason"] in claim_reasons
            )
        case_results.append(
            {
                "case_id": case["case_id"],
                "expected_error": case.get("expected_error"),
                "expected_claim_reason": case.get("expected_claim_reason"),
                "observed_errors": error_codes,
                "observed_claim_reasons": claim_reasons,
                "admission_token": report["admission_token"],
                "passed": passed,
            }
        )

    result = {
        "trial": "evidence_objects_v2",
        "contract_version": "aion-evidence-objects-v2",
        "valid_control": {
            "passed": valid_passed,
            "admission_token": valid_first["admission_token"],
            "execution_authorized": False,
            "report_digest": valid_first["report_digest"],
        },
        "adversarial_cases": case_results,
        "truth_modified": False,
    }
    result["passed"] = valid_passed and all(item["passed"] for item in case_results)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    result = run_trial()
    if args.output:
        write_report(result, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
