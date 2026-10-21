"""Rollback-safe, evidence-gated adaptive learning for AION.

AION learns bounded reliability weights for models and sources. A caller
cannot provide a bare score or verdict: every update is derived from a strict,
freshly recomputed verification record and corroborating non-model evidence.
Updates are atomic, replay protected, recoverably audited and never modify
Truth or base-model parameters.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from security.redaction import SensitiveDataError, TextSafetyError, redact_structure
from storage.atomic_json import (
    JsonStorageError,
    append_jsonl_record,
    load_json,
    update_json,
)
from verification.pipeline import (
    EvidenceItem,
    MODEL_SOURCE_TYPES,
    VerificationPolicy,
    evaluate_claim,
    revalidate_verification_record,
)

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
    min_verified_sources: int = 2
    min_verified_independent_groups: int = 2
    min_verified_average_quality: float = 0.65
    max_verified_contradiction: float = 0.35
    rollback_on_regression: bool = True
    max_consecutive_rollbacks: int = 3
    recovery_observations_required: int = 3
    max_processed_observations: int = 10_000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp(value: float, policy: LearningPolicy) -> float:
    return max(policy.min_reliability, min(policy.max_reliability, round(value, 4)))


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _validate_learning_policy(policy: LearningPolicy) -> LearningPolicy:
    if not isinstance(policy, LearningPolicy):
        raise TypeError("Learning policy has invalid type")
    numeric_fields = (
        "initial_reliability",
        "min_reliability",
        "max_reliability",
        "reward_step",
        "penalty_step",
        "severe_penalty_step",
        "min_verified_evidence_score",
        "min_verified_average_quality",
        "max_verified_contradiction",
    )
    for field_name in numeric_fields:
        value = getattr(policy, field_name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"Learning policy {field_name} must be numeric")
        if not math.isfinite(float(value)):
            raise ValueError(f"Learning policy {field_name} must be finite")

    if not (
        0.0 <= policy.min_reliability
        <= policy.initial_reliability
        <= policy.max_reliability
        <= 1.0
    ):
        raise ValueError("Learning reliability bounds are invalid")
    if not 0.0 < policy.reward_step <= 1.0:
        raise ValueError("Learning reward_step is out of bounds")
    if not 0.0 < policy.penalty_step <= 1.0:
        raise ValueError("Learning penalty_step is out of bounds")
    if not 0.0 < policy.severe_penalty_step <= 1.0:
        raise ValueError("Learning severe_penalty_step is out of bounds")
    if policy.min_verified_evidence_score < 0.0:
        raise ValueError("Learning evidence threshold is out of bounds")
    if not 0.0 <= policy.min_verified_average_quality <= 1.0:
        raise ValueError("Learning average quality threshold is out of bounds")
    if not 0.0 <= policy.max_verified_contradiction <= 1.0:
        raise ValueError("Learning contradiction threshold is out of bounds")
    if not isinstance(policy.rollback_on_regression, bool):
        raise TypeError("Learning rollback_on_regression must be boolean")

    for field_name, maximum in (
        ("min_verified_sources", 10_000),
        ("min_verified_independent_groups", 10_000),
        ("max_consecutive_rollbacks", 10_000),
        ("recovery_observations_required", 10_000),
        ("max_processed_observations", 1_000_000),
    ):
        value = getattr(policy, field_name)
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"Learning policy {field_name} must be an integer")
        if value < 1 or value > maximum:
            raise ValueError(f"Learning policy {field_name} is out of bounds")
    return policy


class AdaptiveLearningController:
    def __init__(
        self,
        state_path: str | Path = DEFAULT_STATE,
        audit_path: str | Path = DEFAULT_AUDIT,
        policy: LearningPolicy | None = None,
    ) -> None:
        self.state_path = Path(state_path)
        self.audit_path = Path(audit_path)
        self.policy = _validate_learning_policy(policy or LearningPolicy())
        self.state = self._load()

    def _default_state(self) -> dict[str, Any]:
        return {
            "version": 3,
            "updated_at": _now(),
            "sources": {},
            "models": {},
            "history": [],
            "safety": {},
            "observations": {},
            "pending_audit": {},
            "truth_modified": False,
        }

    def _normalise_state(self, data: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise LearningStateError("Learning state must be an object")
        if data.get("truth_modified", False) is not False:
            raise LearningStateError("Learning state reports a forbidden Truth modification")

        expected = {
            "sources": dict,
            "models": dict,
            "history": list,
            "safety": dict,
            "observations": dict,
            "pending_audit": dict,
        }
        defaults = self._default_state()
        for field, expected_type in expected.items():
            data.setdefault(field, copy.deepcopy(defaults[field]))
            if not isinstance(data[field], expected_type):
                raise LearningStateError(f"Learning state field has invalid type: {field}")
        data["version"] = 3
        data["truth_modified"] = False
        return data

    def _load(self) -> dict[str, Any]:
        try:
            data = load_json(
                self.state_path,
                default_factory=self._default_state,
                expected_type=dict,
            )
            return self._normalise_state(data)
        except LearningStateError:
            raise
        except (JsonStorageError, OSError, TypeError, ValueError) as exc:
            raise LearningStateError("Learning state is invalid or unavailable") from exc

    def _transaction(
        self,
        updater: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        result_box: dict[str, Any] = {}

        def apply(state: dict[str, Any]) -> dict[str, Any]:
            state = self._normalise_state(state)
            result_box["result"] = updater(state)
            state["updated_at"] = _now()
            state["truth_modified"] = False
            return state

        try:
            self.state = update_json(
                self.state_path,
                default_factory=self._default_state,
                expected_type=dict,
                updater=apply,
            )
        except LearningStateError:
            raise
        except (JsonStorageError, OSError, TypeError, ValueError) as exc:
            raise LearningStateError("Learning state transaction did not complete") from exc
        return copy.deepcopy(result_box["result"])

    @staticmethod
    def _new_event(record: dict[str, Any]) -> dict[str, Any]:
        return {
            **record,
            "event_id": record.get("event_id") or f"learning-{uuid4().hex}",
            "timestamp": record.get("timestamp") or _now(),
            "truth_modified": False,
        }

    @staticmethod
    def _safe_payload(payload: dict[str, Any]) -> dict[str, Any]:
        safe, redactions = redact_structure(payload)
        if redactions:
            raise SensitiveDataError("Learning boundary rejected sensitive data")
        if not isinstance(safe, dict):
            raise TypeError("Learning payload must be an object")
        return safe

    def _append_event(self, record: dict[str, Any]) -> None:
        payload = self._safe_payload(self._new_event(record))
        try:
            append_jsonl_record(self.audit_path, payload, unique_field="event_id")
        except (JsonStorageError, OSError, TypeError, ValueError) as exc:
            raise LearningStateError("Learning audit append did not complete") from exc

    def _queue_event(self, state: dict[str, Any], record: dict[str, Any]) -> str:
        payload = self._safe_payload(self._new_event(record))
        event_id = payload["event_id"]
        state["pending_audit"][event_id] = payload
        return event_id

    def recover_pending_audit(self) -> dict[str, Any]:
        """Idempotently copy state-committed audit events into JSONL."""

        snapshot = self._load()
        pending = copy.deepcopy(snapshot.get("pending_audit", {}))
        if not pending:
            self.state = snapshot
            return {"status": "ok", "recovered": 0, "pending": 0}

        completed: list[str] = []
        try:
            for event_id in sorted(pending):
                record = pending[event_id]
                if not isinstance(record, dict) or record.get("event_id") != event_id:
                    raise LearningStateError("Pending learning audit event is invalid")
                safe = self._safe_payload(record)
                append_jsonl_record(self.audit_path, safe, unique_field="event_id")
                completed.append(event_id)
        except LearningStateError:
            raise
        except (JsonStorageError, OSError, TypeError, ValueError) as exc:
            raise LearningStateError("Pending learning audit recovery did not complete") from exc

        def clear_emitted(state: dict[str, Any]) -> dict[str, Any]:
            current = state["pending_audit"]
            for event_id in completed:
                if current.get(event_id) == pending[event_id]:
                    current.pop(event_id, None)
            return {
                "status": "ok",
                "recovered": len(completed),
                "pending": len(current),
            }

        return self._transaction(clear_emitted)

    def _complete_mutation(self, result: dict[str, Any]) -> dict[str, Any]:
        self.recover_pending_audit()
        return result

    @staticmethod
    def _identity_digest(identity: Any) -> str:
        return hashlib.sha256(str(identity).encode("utf-8", errors="replace")).hexdigest()[:20]

    def _normalise_identity(self, kind: str, identity: str) -> str:
        if kind not in {"source", "model"}:
            raise ValueError("kind must be source or model")
        if not isinstance(identity, str):
            raise TypeError("identity must be a string")
        identity = identity.strip()
        if not identity or len(identity) > 512:
            raise ValueError("identity length is invalid")
        if any(ord(character) < 32 for character in identity):
            raise ValueError("identity contains control characters")
        self._safe_payload({"identity": identity})
        return identity

    @staticmethod
    def _safe_reason(reason: str) -> str:
        if not isinstance(reason, str):
            raise TypeError("reason must be a string")
        reason = reason.strip()
        if not reason or len(reason) > 512:
            raise ValueError("reason length is invalid")
        safe, redactions = redact_structure(reason)
        if redactions:
            raise SensitiveDataError("Learning reason contains sensitive data")
        return str(safe)

    @staticmethod
    def _bucket(state: dict[str, Any], kind: str) -> dict[str, Any]:
        if kind not in {"source", "model"}:
            raise ValueError("kind must be source or model")
        return state["sources" if kind == "source" else "models"]

    @staticmethod
    def _safety(state: dict[str, Any], kind: str, identity: str) -> dict[str, Any]:
        key = f"{kind}:{identity}"
        return state["safety"].setdefault(key, {
            "rollback_streak": 0,
            "frozen": False,
            "recovery_observations": 0,
            "last_reason": None,
        })

    @staticmethod
    def _add_checkpoint(state: dict[str, Any], reason: str) -> int:
        snapshot = copy.deepcopy({
            "sources": state["sources"],
            "models": state["models"],
        })
        history = state["history"]
        history.append({"reason": reason, "created_at": _now(), "snapshot": snapshot})
        if len(history) > 20:
            del history[:-20]
        return len(history) - 1

    def checkpoint(self, reason: str) -> int:
        reason = self._safe_reason(reason)
        self.recover_pending_audit()

        def create(state: dict[str, Any]) -> dict[str, Any]:
            index = self._add_checkpoint(state, reason)
            self._queue_event(state, {
                "event": "checkpoint",
                "reason": reason,
                "index": index,
            })
            return {"index": index}

        result = self._transaction(create)
        self._complete_mutation(result)
        return int(result["index"])

    def rollback(
        self,
        checkpoint_index: int = -1,
        reason: str = "manual_or_regression",
    ) -> dict[str, Any]:
        reason = self._safe_reason(reason)
        self.recover_pending_audit()

        def restore(state: dict[str, Any]) -> dict[str, Any]:
            history = state["history"]
            if not history:
                raise LearningStateError("No checkpoint available")
            try:
                checkpoint = history[checkpoint_index]
            except IndexError as exc:
                raise LearningStateError("Checkpoint not found") from exc
            snapshot = checkpoint.get("snapshot")
            if not isinstance(snapshot, dict):
                raise LearningStateError("Checkpoint snapshot is invalid")
            sources = snapshot.get("sources")
            models = snapshot.get("models")
            if not isinstance(sources, dict) or not isinstance(models, dict):
                raise LearningStateError("Checkpoint snapshot is invalid")
            state["sources"] = copy.deepcopy(sources)
            state["models"] = copy.deepcopy(models)
            self._queue_event(state, {
                "event": "rollback",
                "reason": reason,
                "checkpoint_created_at": checkpoint.get("created_at"),
            })
            return {
                "sources": copy.deepcopy(state["sources"]),
                "models": copy.deepcopy(state["models"]),
                "safety": copy.deepcopy(state["safety"]),
                "checkpoints": len(history),
                "truth_modified": False,
                "base_model_weights_modified": False,
            }

        return self._complete_mutation(self._transaction(restore))

    def reliability(self, kind: str, identity: str) -> float:
        identity = self._normalise_identity(kind, identity)
        self.state = self._load()
        item = self._bucket(self.state, kind).get(identity, {})
        return float(item.get("reliability", self.policy.initial_reliability))

    def influence(self, kind: str, identity: str) -> float:
        reliability = self.reliability(kind, identity)
        return 0.0 if reliability < 0.15 else reliability

    def _learning_verification_policy(self) -> VerificationPolicy:
        return VerificationPolicy(
            min_supporting_sources=max(2, int(self.policy.min_verified_sources)),
            min_independent_groups=max(2, int(self.policy.min_verified_independent_groups)),
            min_weighted_support=max(
                1.4, float(self.policy.min_verified_evidence_score)
            ),
            max_weighted_contradiction=min(
                0.35,
                max(0.0, float(self.policy.max_verified_contradiction)),
            ),
            min_average_quality=max(
                0.65,
                min(1.0, float(self.policy.min_verified_average_quality)),
            ),
            require_non_llm_source=True,
        )

    @staticmethod
    def _observation_id(
        *,
        kind: str,
        identity: str,
        claim: str,
        evidence: tuple[EvidenceItem, ...],
        policy: VerificationPolicy,
    ) -> str:
        evidence_records = [asdict(item) for item in evidence]
        evidence_records.sort(key=_canonical_json)
        payload = {
            "kind": kind,
            "identity": identity,
            "claim": claim,
            "evidence": evidence_records,
            "learning_policy": asdict(policy),
        }
        return "observation-" + hashlib.sha256(
            _canonical_json(payload).encode("utf-8")
        ).hexdigest()

    def _reject(
        self,
        *,
        reason: str,
        kind: Any,
        identity: Any,
        identity_is_safe: bool,
    ) -> dict[str, Any]:
        event: dict[str, Any] = {
            "event": "learning_rejected",
            "reason": reason,
            "identity_digest": self._identity_digest(identity),
        }
        if isinstance(kind, str) and kind in {"source", "model"}:
            event["kind"] = kind
        if identity_is_safe:
            event["identity"] = identity
        self._append_event(event)
        return {"updated": False, "reason": reason}

    def record_verified_outcome(
        self,
        *,
        kind: str,
        identity: str,
        verification_record: dict[str, Any] | None = None,
        cleanliness_passed: bool = True,
        regression_detected: bool = False,
        # Legacy fields remain accepted only so older callers fail closed with
        # a stable result instead of silently learning from them.
        supported: bool | None = None,
        evidence_score: float | None = None,
        contradicted: bool | None = None,
    ) -> dict[str, Any]:
        del supported, evidence_score, contradicted
        try:
            identity = self._normalise_identity(kind, identity)
        except (SensitiveDataError, TextSafetyError):
            return self._reject(
                reason="sensitive_identity_rejected",
                kind=kind,
                identity=identity,
                identity_is_safe=False,
            )
        except (TypeError, ValueError):
            return self._reject(
                reason="invalid_learning_identity",
                kind=kind,
                identity=identity,
                identity_is_safe=False,
            )

        if not isinstance(cleanliness_passed, bool) or not isinstance(
            regression_detected, bool
        ):
            return self._reject(
                reason="invalid_learning_control_flags",
                kind=kind,
                identity=identity,
                identity_is_safe=True,
            )

        if not isinstance(verification_record, dict):
            return self._reject(
                reason="structured_verification_required",
                kind=kind,
                identity=identity,
                identity_is_safe=True,
            )

        try:
            _, redactions = redact_structure(verification_record)
        except TextSafetyError:
            return self._reject(
                reason="verification_record_out_of_bounds",
                kind=kind,
                identity=identity,
                identity_is_safe=True,
            )
        if redactions:
            return self._reject(
                reason="sensitive_verification_rejected",
                kind=kind,
                identity=identity,
                identity_is_safe=True,
            )

        try:
            validated = revalidate_verification_record(verification_record)
        except (TypeError, ValueError):
            return self._reject(
                reason="verification_record_invalid",
                kind=kind,
                identity=identity,
                identity_is_safe=True,
            )

        matching = [item for item in validated.evidence if item.source_id == identity]
        if len(matching) != 1:
            return self._reject(
                reason=(
                    "identity_not_bound_to_evidence"
                    if not matching
                    else "identity_evidence_ambiguous"
                ),
                kind=kind,
                identity=identity,
                identity_is_safe=True,
            )
        target = matching[0]
        target_is_model = target.source_type in MODEL_SOURCE_TYPES
        if (kind == "model") != target_is_model:
            return self._reject(
                reason="identity_kind_evidence_mismatch",
                kind=kind,
                identity=identity,
                identity_is_safe=True,
            )
        if target.stance == "neutral":
            self._append_event({
                "event": "learning_skipped",
                "kind": kind,
                "identity": identity,
                "reason": "neutral_target_evidence",
                "verification_hash": validated.verification_hash,
            })
            return {"updated": False, "reason": "neutral_target_evidence"}

        # The subject being scored and all other model outputs are excluded
        # from the reference set. A model therefore cannot corroborate itself,
        # and model agreement alone cannot alter reliability.
        corroborating = tuple(
            item
            for item in validated.evidence
            if item.source_id != identity and item.source_type not in MODEL_SOURCE_TYPES
        )
        learning_policy = self._learning_verification_policy()
        independent_evaluation = evaluate_claim(
            validated.claim,
            corroborating,
            learning_policy,
        )
        if independent_evaluation.decision != "verified":
            self._append_event({
                "event": "learning_skipped",
                "kind": kind,
                "identity": identity,
                "reason": "independent_corroboration_insufficient",
                "verification_hash": validated.verification_hash,
                "independent_decision": independent_evaluation.decision,
                "independent_reasons": independent_evaluation.reasons,
                "independent_evidence_score": independent_evaluation.weighted_support,
                "independent_support_groups": (
                    independent_evaluation.independent_support_groups
                ),
            })
            return {
                "updated": False,
                "reason": "independent_corroboration_insufficient",
                "independent_evaluation": independent_evaluation.to_dict(),
            }

        observation_id = self._observation_id(
            kind=kind,
            identity=identity,
            claim=validated.claim,
            evidence=validated.evidence,
            policy=learning_policy,
        )
        self.recover_pending_audit()

        def learn(state: dict[str, Any]) -> dict[str, Any]:
            observations = state["observations"]
            if observation_id in observations:
                return {
                    "updated": False,
                    "reason": "duplicate_verified_outcome",
                    "observation_id": observation_id,
                }
            limit = max(1, int(self.policy.max_processed_observations))
            if len(observations) >= limit:
                self._queue_event(state, {
                    "event": "learning_blocked",
                    "kind": kind,
                    "identity": identity,
                    "reason": "observation_capacity_reached",
                    "capacity": limit,
                })
                return {"updated": False, "reason": "observation_capacity_reached"}

            observation = {
                "kind": kind,
                "identity": identity,
                "claim_id": validated.claim_id,
                "verification_hash": validated.verification_hash,
                "target_stance": target.stance,
                "processed_at": _now(),
            }
            safety = self._safety(state, kind, identity)
            supported_by_target = target.stance == "supports"
            contradicted_by_target = target.stance == "contradicts"

            if safety.get("frozen"):
                stable = (
                    supported_by_target
                    and cleanliness_passed
                    and not regression_detected
                )
                safety["recovery_observations"] = (
                    int(safety.get("recovery_observations", 0)) + 1 if stable else 0
                )
                observations[observation_id] = observation
                required = max(1, int(self.policy.recovery_observations_required))
                if safety["recovery_observations"] >= required:
                    safety.update({
                        "frozen": False,
                        "rollback_streak": 0,
                        "recovery_observations": 0,
                        "last_reason": "stability_recovered",
                    })
                    self._queue_event(state, {
                        "event": "learning_freeze_recovered",
                        "kind": kind,
                        "identity": identity,
                        "observation_id": observation_id,
                    })
                    return {
                        "updated": False,
                        "frozen": False,
                        "recovered": True,
                        "reason": "stability_recovered_next_outcome_may_learn",
                    }
                self._queue_event(state, {
                    "event": "learning_blocked_by_freeze",
                    "kind": kind,
                    "identity": identity,
                    "observation_id": observation_id,
                    "recovery_observations": safety["recovery_observations"],
                    "required": required,
                })
                return {
                    "updated": False,
                    "frozen": True,
                    "reason": "anti_oscillation_learning_freeze",
                    "recovery_observations": safety["recovery_observations"],
                    "required": required,
                }

            checkpoint_index = self._add_checkpoint(state, f"before:{kind}:{identity}")
            observations[observation_id] = observation
            if regression_detected and self.policy.rollback_on_regression:
                safety["rollback_streak"] = int(safety.get("rollback_streak", 0)) + 1
                safety["recovery_observations"] = 0
                safety["last_reason"] = "regression_detected"
                if safety["rollback_streak"] >= max(
                    1, int(self.policy.max_consecutive_rollbacks)
                ):
                    safety["frozen"] = True
                    safety["last_reason"] = "rollback_limit_reached"
                current_reliability = float(
                    self._bucket(state, kind).get(identity, {}).get(
                        "reliability", self.policy.initial_reliability
                    )
                )
                self._queue_event(state, {
                    "event": "learning_regression_rollback",
                    "kind": kind,
                    "identity": identity,
                    "observation_id": observation_id,
                    "checkpoint_index": checkpoint_index,
                    "rollback_streak": safety["rollback_streak"],
                    "frozen": bool(safety.get("frozen")),
                })
                return {
                    "updated": False,
                    "rolled_back": True,
                    "frozen": bool(safety.get("frozen")),
                    "reason": "regression_detected",
                    "rollback_streak": safety["rollback_streak"],
                    "reliability": current_reliability,
                }

            bucket = self._bucket(state, kind)
            item = bucket.setdefault(identity, {
                "reliability": self.policy.initial_reliability,
                "verified_successes": 0,
                "verified_failures": 0,
                "cleanliness_failures": 0,
            })
            before = float(item.get("reliability", self.policy.initial_reliability))

            if contradicted_by_target:
                delta = -self.policy.severe_penalty_step
                item["verified_failures"] = int(item.get("verified_failures", 0)) + 1
            elif not cleanliness_passed:
                delta = -self.policy.severe_penalty_step
                item["cleanliness_failures"] = int(item.get("cleanliness_failures", 0)) + 1
            else:
                delta = self.policy.reward_step
                item["verified_successes"] = int(item.get("verified_successes", 0)) + 1

            item["reliability"] = _clamp(before + delta, self.policy)
            item["last_evidence_score"] = independent_evaluation.weighted_support
            item["last_verification_hash"] = validated.verification_hash
            item["last_claim_id"] = validated.claim_id
            item["last_observation_id"] = observation_id
            item["updated_at"] = _now()
            safety.update({
                "rollback_streak": 0,
                "recovery_observations": 0,
                "last_reason": "stable_update",
            })
            self._queue_event(state, {
                "event": "reliability_update",
                "kind": kind,
                "identity": identity,
                "before": before,
                "after": item["reliability"],
                "target_stance": target.stance,
                "cleanliness_passed": bool(cleanliness_passed),
                "independent_evidence_score": independent_evaluation.weighted_support,
                "independent_support_groups": (
                    independent_evaluation.independent_support_groups
                ),
                "verification_hash": validated.verification_hash,
                "claim_id": validated.claim_id,
                "observation_id": observation_id,
            })
            influence = 0.0 if item["reliability"] < 0.15 else item["reliability"]
            return {
                "updated": True,
                "rolled_back": False,
                "before": before,
                "after": item["reliability"],
                "influence": influence,
                "observation_id": observation_id,
                "verification_hash": validated.verification_hash,
            }

        return self._complete_mutation(self._transaction(learn))

    def status(self) -> dict[str, Any]:
        self.state = self._load()
        return {
            "sources": copy.deepcopy(self.state["sources"]),
            "models": copy.deepcopy(self.state["models"]),
            "safety": copy.deepcopy(self.state["safety"]),
            "checkpoints": len(self.state["history"]),
            "processed_observations": len(self.state["observations"]),
            "pending_audit_events": len(self.state["pending_audit"]),
            "truth_modified": False,
            "base_model_weights_modified": False,
        }
