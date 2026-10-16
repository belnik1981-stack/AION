"""Stateful monitoring for the parallel commercial-dependency layer."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .layer import CommercialAssessment, ParallelOutcomeComparison

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE = ROOT / "knowledge" / "adaptive" / "commercial_monitor.json"
DEFAULT_AUDIT = ROOT / "audit" / "commercial_dependency.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CommercialDependencyMonitor:
    """Track predicted vs actual effects and automatic rollback signals."""

    def __init__(self, state_path: str | Path = DEFAULT_STATE, audit_path: str | Path = DEFAULT_AUDIT) -> None:
        self.state_path = Path(state_path)
        self.audit_path = Path(audit_path)
        self.state = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {
                "version": 1,
                "cases": {},
                "truth_modified": False,
            }
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state["truth_modified"] = False
        self.state_path.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _audit(self, payload: dict[str, Any]) -> None:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({**payload, "timestamp": _now(), "truth_modified": False}, ensure_ascii=False) + "\n")

    def register_assessment(self, case_id: str, assessment: CommercialAssessment) -> dict[str, Any]:
        cases = self.state.setdefault("cases", {})
        case = cases.setdefault(case_id, {"history": []})
        case["assessment"] = assessment.to_dict()
        case["updated_at"] = _now()
        case["history"].append({"event": "assessment", "data": assessment.to_dict(), "time": _now()})
        self._save()
        self._audit({"event": "commercial_assessment", "case_id": case_id, "assessment": assessment.to_dict()})
        return case

    def record_comparison(self, case_id: str, comparison: ParallelOutcomeComparison) -> dict[str, Any]:
        cases = self.state.setdefault("cases", {})
        case = cases.setdefault(case_id, {"history": []})
        case["last_comparison"] = comparison.to_dict()
        case["rollback_required"] = comparison.rollback_required
        case["preferred_path"] = comparison.preferred_path
        case["updated_at"] = _now()
        case["history"].append({"event": "comparison", "data": comparison.to_dict(), "time": _now()})
        self._save()
        self._audit({"event": "commercial_parallel_comparison", "case_id": case_id, "comparison": comparison.to_dict()})
        return case

    def should_use_adjusted_path(self, case_id: str) -> bool:
        case = self.state.get("cases", {}).get(case_id, {})
        if case.get("rollback_required"):
            return False
        return case.get("preferred_path") == "with_commercial_adjustment"

    def status(self) -> dict[str, Any]:
        return {
            "cases": self.state.get("cases", {}),
            "truth_modified": False,
        }
