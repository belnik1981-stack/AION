"""Rollback-safe adaptive learning for AION.

AION learns reliability weights for models/sources from verified outcomes.
It does NOT fine-tune or rewrite model parameters. Every update is journaled
and reversible. Repeated rollback loops automatically freeze learning.
Truth is never modified.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE = ROOT / "knowledge" / "adaptive" / "reliability.json"
DEFAULT_AUDIT = ROOT / "audit" / "learning.jsonl"


class LearningStateError(RuntimeError):
    pass


@dataclass(frozen=True)
class LearningPolicy:
    initial_reliability: float = 0.5
    min_reliability: float = 0.0
    max_reliability: float = 1.0
    reward_step: float = 0.06
    penalty_step: float = 0.12
    severe_penalty_step: float = 0.25
    min_verified_evidence_score: float = 1.4
    rollback_on_regression: bool = True
    max_consecutive_rollbacks: int = 3
    recovery_observations_required: int = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp(value: float, policy: LearningPolicy) -> float:
    return max(policy.min_reliability, min(policy.max_reliability, round(value, 4)))


class AdaptiveLearningController:
    def __init__(self, state_path: str | Path = DEFAULT_STATE, audit_path: str | Path = DEFAULT_AUDIT, policy: LearningPolicy | None = None) -> None:
        self.state_path = Path(state_path)
        self.audit_path = Path(audit_path)
        self.policy = policy or LearningPolicy()
        self.state = self._load()

    def _default_state(self) -> dict[str, Any]:
        return {
            "version": 2,
            "updated_at": _now(),
            "sources": {},
            "models": {},
            "history": [],
            "safety": {},
            "truth_modified": False,
        }

    def _load(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return self._default_state()
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise LearningStateError(f"Invalid learning state: {exc}") from exc
        if not isinstance(data, dict):
            raise LearningStateError("Learning state must be an object")
        data.setdefault("version", 2)
        data.setdefault("sources", {})
        data.setdefault("models", {})
        data.setdefault("history", [])
        data.setdefault("safety", {})
        data.setdefault("truth_modified", False)
        return data

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state["updated_at"] = _now()
        self.state["truth_modified"] = False
        self.state_path.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _audit(self, record: dict[str, Any]) -> None:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {**record, "timestamp": _now(), "truth_modified": False}
        with self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def checkpoint(self, reason: str) -> int:
        snapshot = copy.deepcopy({
            "sources": self.state.get("sources", {}),
            "models": self.state.get("models", {}),
        })
        history = self.state.setdefault("history", [])
        history.append({"reason": reason, "created_at": _now(), "snapshot": snapshot})
        if len(history) > 20:
            del history[:-20]
        self._save()
        self._audit({"event": "checkpoint", "reason": reason, "index": len(history) - 1})
        return len(history) - 1

    def rollback(self, checkpoint_index: int = -1, reason: str = "manual_or_regression") -> dict[str, Any]:
        history = self.state.get("history", [])
        if not history:
            raise LearningStateError("No checkpoint available")
        try:
            checkpoint = history[checkpoint_index]
        except IndexError as exc:
            raise LearningStateError("Checkpoint not found") from exc
        snapshot = checkpoint.get("snapshot", {})
        self.state["sources"] = copy.deepcopy(snapshot.get("sources", {}))
        self.state["models"] = copy.deepcopy(snapshot.get("models", {}))
        self._save()
        self._audit({"event": "rollback", "reason": reason, "checkpoint_created_at": checkpoint.get("created_at")})
        return self.status()

    def _bucket(self, kind: str) -> dict[str, Any]:
        if kind not in {"source", "model"}:
            raise ValueError("kind must be source or model")
        return self.state.setdefault("sources" if kind == "source" else "models", {})

    def _safety(self, kind: str, identity: str) -> dict[str, Any]:
        key = f"{kind}:{identity}"
        return self.state.setdefault("safety", {}).setdefault(key, {
            "rollback_streak": 0,
            "frozen": False,
            "recovery_observations": 0,
            "last_reason": None,
        })

    def reliability(self, kind: str, identity: str) -> float:
        item = self._bucket(kind).get(identity, {})
        return float(item.get("reliability", self.policy.initial_reliability))

    def influence(self, kind: str, identity: str) -> float:
        rel = self.reliability(kind, identity)
        return 0.0 if rel < 0.15 else rel

    def record_verified_outcome(self, *, kind: str, identity: str, supported: bool, evidence_score: float, contradicted: bool = False, cleanliness_passed: bool = True, regression_detected: bool = False) -> dict[str, Any]:
        if evidence_score < self.policy.min_verified_evidence_score:
            self._audit({"event": "learning_skipped", "kind": kind, "identity": identity, "reason": "insufficient_verified_evidence", "evidence_score": evidence_score})
            return {"updated": False, "reason": "insufficient_verified_evidence"}

        safety = self._safety(kind, identity)
        if safety.get("frozen"):
            stable = supported and not contradicted and cleanliness_passed and not regression_detected
            safety["recovery_observations"] = int(safety.get("recovery_observations", 0)) + 1 if stable else 0
            required = max(1, int(self.policy.recovery_observations_required))
            if safety["recovery_observations"] >= required:
                safety.update({"frozen": False, "rollback_streak": 0, "recovery_observations": 0, "last_reason": "stability_recovered"})
                self._save()
                self._audit({"event": "learning_freeze_recovered", "kind": kind, "identity": identity})
                return {"updated": False, "frozen": False, "recovered": True, "reason": "stability_recovered_next_outcome_may_learn"}
            self._save()
            self._audit({"event": "learning_blocked_by_freeze", "kind": kind, "identity": identity, "recovery_observations": safety["recovery_observations"], "required": required})
            return {"updated": False, "frozen": True, "reason": "anti_oscillation_learning_freeze", "recovery_observations": safety["recovery_observations"], "required": required}

        checkpoint_index = self.checkpoint(f"before:{kind}:{identity}")
        bucket = self._bucket(kind)
        item = bucket.setdefault(identity, {
            "reliability": self.policy.initial_reliability,
            "verified_successes": 0,
            "verified_failures": 0,
            "cleanliness_failures": 0,
        })
        before = float(item.get("reliability", self.policy.initial_reliability))

        if contradicted:
            delta = -self.policy.severe_penalty_step
            item["verified_failures"] = int(item.get("verified_failures", 0)) + 1
        elif not cleanliness_passed:
            delta = -self.policy.severe_penalty_step
            item["cleanliness_failures"] = int(item.get("cleanliness_failures", 0)) + 1
        elif supported:
            delta = self.policy.reward_step
            item["verified_successes"] = int(item.get("verified_successes", 0)) + 1
        else:
            delta = -self.policy.penalty_step
            item["verified_failures"] = int(item.get("verified_failures", 0)) + 1

        item["reliability"] = _clamp(before + delta, self.policy)
        item["last_evidence_score"] = float(evidence_score)
        item["updated_at"] = _now()
        self._save()

        if regression_detected and self.policy.rollback_on_regression:
            self.rollback(checkpoint_index, reason="automatic_regression_rollback")
            safety = self._safety(kind, identity)
            safety["rollback_streak"] = int(safety.get("rollback_streak", 0)) + 1
            safety["recovery_observations"] = 0
            safety["last_reason"] = "regression_detected"
            if safety["rollback_streak"] >= max(1, int(self.policy.max_consecutive_rollbacks)):
                safety["frozen"] = True
                safety["last_reason"] = "rollback_limit_reached"
                self._audit({"event": "learning_frozen_after_repeated_rollbacks", "kind": kind, "identity": identity, "rollback_streak": safety["rollback_streak"]})
            self._save()
            return {
                "updated": False,
                "rolled_back": True,
                "frozen": bool(safety.get("frozen")),
                "reason": "regression_detected",
                "rollback_streak": safety["rollback_streak"],
                "reliability": self.reliability(kind, identity),
            }

        safety.update({"rollback_streak": 0, "recovery_observations": 0, "last_reason": "stable_update"})
        self._save()
        self._audit({
            "event": "reliability_update",
            "kind": kind,
            "identity": identity,
            "before": before,
            "after": item["reliability"],
            "supported": supported,
            "contradicted": contradicted,
            "cleanliness_passed": cleanliness_passed,
            "evidence_score": evidence_score,
        })
        return {"updated": True, "rolled_back": False, "before": before, "after": item["reliability"], "influence": self.influence(kind, identity)}

    def status(self) -> dict[str, Any]:
        return {
            "sources": self.state.get("sources", {}),
            "models": self.state.get("models", {}),
            "safety": self.state.get("safety", {}),
            "checkpoints": len(self.state.get("history", [])),
            "truth_modified": False,
            "base_model_weights_modified": False,
        }
