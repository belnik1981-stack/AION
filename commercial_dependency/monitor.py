"""Crash-safe state for the parallel commercial-dependency layer.

The monitor records only analysis metadata. It has no authority to modify the
trusted claim pipeline, Truth or model parameters. State mutations use the
shared atomic JSON contract and audit events are recoverable after an
interruption between the state commit and the JSONL append.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from security.redaction import (
    SensitiveDataError,
    TextSafetyError,
    redact_sensitive,
    redact_structure,
)
from storage.atomic_json import (
    JsonStorageError,
    append_jsonl_record,
    load_json,
    update_json,
)

from .layer import CommercialAssessment, ParallelOutcomeComparison

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE = ROOT / "knowledge" / "adaptive" / "commercial_monitor.json"
DEFAULT_AUDIT = ROOT / "audit" / "commercial_dependency.jsonl"


class CommercialMonitorStateError(RuntimeError):
    """Commercial monitor input or persistent state is unsafe/unavailable."""


@dataclass(frozen=True)
class CommercialMonitorPolicy:
    """Hard storage limits; reaching a limit stops rather than evicts history."""

    max_cases: int = 1_000
    max_history_per_case: int = 100
    max_pending_audit: int = 1_000
    max_case_id_chars: int = 512
    max_state_bytes: int = 16 * 1024 * 1024


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_policy(policy: CommercialMonitorPolicy) -> CommercialMonitorPolicy:
    if not isinstance(policy, CommercialMonitorPolicy):
        raise TypeError("Commercial monitor policy has invalid type")
    for name, hard_maximum in (
        ("max_cases", 1_000_000),
        ("max_history_per_case", 100_000),
        ("max_pending_audit", 1_000_000),
        ("max_case_id_chars", 4_096),
        ("max_state_bytes", 1024 * 1024 * 1024),
    ):
        value = getattr(policy, name)
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"Commercial monitor policy {name} must be an integer")
        if value < 1 or value > hard_maximum:
            raise ValueError(f"Commercial monitor policy {name} is out of bounds")
    return policy


class CommercialDependencyMonitor:
    """Track predicted/actual effects without granting decision authority."""

    def __init__(
        self,
        state_path: str | Path = DEFAULT_STATE,
        audit_path: str | Path = DEFAULT_AUDIT,
        policy: CommercialMonitorPolicy | None = None,
    ) -> None:
        self.state_path = Path(state_path)
        self.audit_path = Path(audit_path)
        self.policy = _validate_policy(policy or CommercialMonitorPolicy())
        self.state = self._load()

    @staticmethod
    def _default_state() -> dict[str, Any]:
        return {
            "version": 2,
            "updated_at": _now(),
            "cases": {},
            "pending_audit": {},
            "truth_modified": False,
        }

    @staticmethod
    def _safe_payload(payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise TypeError("Commercial monitor payload must be an object")
        safe, redactions = redact_structure(payload)
        if redactions:
            raise SensitiveDataError("Commercial monitor rejected sensitive data")
        if not isinstance(safe, dict):
            raise TypeError("Commercial monitor payload must be an object")
        # JSON normally permits NaN/Infinity. Persistent risk data must not.
        encoded = json.dumps(
            safe,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )
        # redact_structure intentionally preserves mapping keys. Scanning the
        # bounded canonical representation also rejects credentials hidden in
        # an attacker-controlled key.
        if redact_sensitive(encoded).count:
            raise SensitiveDataError("Commercial monitor rejected sensitive data")
        return safe

    def _normalise_case_id(self, case_id: str) -> str:
        if not isinstance(case_id, str):
            raise TypeError("Commercial case id must be a string")
        normalised = case_id.strip()
        if not normalised or len(normalised) > self.policy.max_case_id_chars:
            raise ValueError("Commercial case id length is invalid")
        if any(ord(character) < 32 for character in normalised):
            raise ValueError("Commercial case id contains control characters")
        self._safe_payload({"case_id": normalised})
        return normalised

    def _normalise_state(self, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise CommercialMonitorStateError("Commercial monitor state must be an object")
        state = copy.deepcopy(value)
        allowed_root = {
            "version",
            "updated_at",
            "cases",
            "pending_audit",
            "truth_modified",
        }
        if set(state) - allowed_root:
            raise CommercialMonitorStateError("Commercial monitor state has unknown fields")
        version = state.get("version", 1)
        if isinstance(version, bool) or not isinstance(version, int) or version not in {1, 2}:
            raise CommercialMonitorStateError("Commercial monitor state version is invalid")
        if state.get("truth_modified", False) is not False:
            raise CommercialMonitorStateError(
                "Commercial monitor reports a forbidden Truth modification"
            )
        updated_at = state.setdefault("updated_at", _now())
        if not isinstance(updated_at, str) or not updated_at or len(updated_at) > 128:
            raise CommercialMonitorStateError("Commercial monitor timestamp is invalid")

        cases = state.setdefault("cases", {})
        pending = state.setdefault("pending_audit", {})
        if not isinstance(cases, dict) or not isinstance(pending, dict):
            raise CommercialMonitorStateError("Commercial monitor state fields are invalid")
        if len(cases) > self.policy.max_cases:
            raise CommercialMonitorStateError("Commercial monitor case capacity exceeded")
        if len(pending) > self.policy.max_pending_audit:
            raise CommercialMonitorStateError("Commercial pending audit capacity exceeded")

        allowed_case_fields = {
            "history",
            "assessment",
            "last_comparison",
            "rollback_required",
            "preferred_path",
            "updated_at",
        }
        for raw_case_id, case in cases.items():
            try:
                case_id = self._normalise_case_id(raw_case_id)
            except (SensitiveDataError, TextSafetyError, TypeError, ValueError) as exc:
                raise CommercialMonitorStateError(
                    "Commercial monitor contains an invalid case id"
                ) from exc
            if case_id != raw_case_id or not isinstance(case, dict):
                raise CommercialMonitorStateError("Commercial monitor case is invalid")
            if set(case) - allowed_case_fields:
                raise CommercialMonitorStateError("Commercial monitor case has unknown fields")
            history = case.setdefault("history", [])
            if not isinstance(history, list):
                raise CommercialMonitorStateError("Commercial monitor history is invalid")
            if len(history) > self.policy.max_history_per_case:
                raise CommercialMonitorStateError("Commercial monitor history capacity exceeded")
            if "updated_at" in case and (
                not isinstance(case["updated_at"], str)
                or not case["updated_at"]
                or len(case["updated_at"]) > 128
            ):
                raise CommercialMonitorStateError("Commercial case timestamp is invalid")
            if "assessment" in case and not isinstance(case["assessment"], dict):
                raise CommercialMonitorStateError("Commercial assessment state is invalid")
            if "last_comparison" in case and not isinstance(
                case["last_comparison"], dict
            ):
                raise CommercialMonitorStateError("Commercial comparison state is invalid")
            if "rollback_required" in case and not isinstance(
                case["rollback_required"], bool
            ):
                raise CommercialMonitorStateError("Commercial rollback state is invalid")
            if "preferred_path" in case and case["preferred_path"] not in {
                "without_commercial_adjustment",
                "with_commercial_adjustment",
                "no_clear_advantage",
            }:
                raise CommercialMonitorStateError("Commercial preferred path is invalid")
            for history_item in history:
                if not isinstance(history_item, dict) or set(history_item) - {
                    "event",
                    "event_id",
                    "data",
                    "time",
                }:
                    raise CommercialMonitorStateError("Commercial history item is invalid")
                if history_item.get("event") not in {"assessment", "comparison"}:
                    raise CommercialMonitorStateError("Commercial history event is invalid")
                if not isinstance(history_item.get("data"), dict):
                    raise CommercialMonitorStateError("Commercial history data is invalid")
                if not isinstance(history_item.get("time"), str):
                    raise CommercialMonitorStateError("Commercial history timestamp is invalid")
                if "event_id" in history_item and (
                    not isinstance(history_item["event_id"], str)
                    or not history_item["event_id"]
                ):
                    raise CommercialMonitorStateError("Commercial history event id is invalid")
            try:
                self._safe_payload(case)
            except (SensitiveDataError, TextSafetyError, TypeError, ValueError) as exc:
                raise CommercialMonitorStateError(
                    "Commercial monitor case payload is unsafe"
                ) from exc

        for event_id, record in pending.items():
            if (
                not isinstance(event_id, str)
                or not event_id
                or not isinstance(record, dict)
                or record.get("event_id") != event_id
            ):
                raise CommercialMonitorStateError(
                    "Commercial pending audit event is invalid"
                )
            try:
                self._safe_payload(record)
            except (SensitiveDataError, TextSafetyError, TypeError, ValueError) as exc:
                raise CommercialMonitorStateError(
                    "Commercial pending audit payload is unsafe"
                ) from exc

        try:
            encoded_state = json.dumps(
                state,
                ensure_ascii=False,
                sort_keys=True,
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise CommercialMonitorStateError(
                "Commercial monitor state is not valid JSON"
            ) from exc
        if len(encoded_state) > self.policy.max_state_bytes:
            raise CommercialMonitorStateError("Commercial monitor state size exceeded")

        state["version"] = 2
        state["truth_modified"] = False
        return state

    def _load(self) -> dict[str, Any]:
        try:
            value = load_json(
                self.state_path,
                default_factory=self._default_state,
                expected_type=dict,
            )
            return self._normalise_state(value)
        except CommercialMonitorStateError:
            raise
        except (JsonStorageError, OSError, TypeError, ValueError) as exc:
            raise CommercialMonitorStateError(
                "Commercial monitor state is invalid or unavailable"
            ) from exc

    def _transaction(
        self,
        updater: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        result_box: dict[str, Any] = {}

        def apply(state: dict[str, Any]) -> dict[str, Any]:
            state = self._normalise_state(state)
            result_box["result"] = updater(state)
            state["version"] = 2
            state["updated_at"] = _now()
            state["truth_modified"] = False
            return self._normalise_state(state)

        try:
            self.state = update_json(
                self.state_path,
                default_factory=self._default_state,
                expected_type=dict,
                updater=apply,
            )
        except CommercialMonitorStateError:
            raise
        except (JsonStorageError, OSError, TypeError, ValueError) as exc:
            raise CommercialMonitorStateError(
                "Commercial monitor transaction did not complete"
            ) from exc
        return copy.deepcopy(result_box["result"])

    @staticmethod
    def _new_event(record: dict[str, Any]) -> dict[str, Any]:
        return {
            **record,
            "event_id": record.get("event_id") or f"commercial-{uuid4().hex}",
            "timestamp": record.get("timestamp") or _now(),
            "truth_modified": False,
        }

    def _queue_event(self, state: dict[str, Any], record: dict[str, Any]) -> str:
        pending = state["pending_audit"]
        if len(pending) >= self.policy.max_pending_audit:
            raise CommercialMonitorStateError("Commercial pending audit capacity reached")
        try:
            payload = self._safe_payload(self._new_event(record))
        except (SensitiveDataError, TextSafetyError, TypeError, ValueError) as exc:
            raise CommercialMonitorStateError(
                "Commercial audit payload was rejected"
            ) from exc
        event_id = payload["event_id"]
        pending[event_id] = payload
        return event_id

    def recover_pending_audit(self) -> dict[str, Any]:
        """Idempotently flush state-committed audit events to JSONL."""

        snapshot = self._load()
        pending = copy.deepcopy(snapshot["pending_audit"])
        if not pending:
            self.state = snapshot
            return {"status": "ok", "recovered": 0, "pending": 0}

        completed: list[str] = []
        try:
            for event_id in sorted(pending):
                record = pending[event_id]
                if not isinstance(record, dict) or record.get("event_id") != event_id:
                    raise CommercialMonitorStateError(
                        "Commercial pending audit event is invalid"
                    )
                safe = self._safe_payload(record)
                append_jsonl_record(self.audit_path, safe, unique_field="event_id")
                completed.append(event_id)
        except CommercialMonitorStateError:
            raise
        except (JsonStorageError, OSError, TypeError, ValueError) as exc:
            raise CommercialMonitorStateError(
                "Commercial pending audit recovery did not complete"
            ) from exc

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
    def _last_event_matches(
        case: dict[str, Any],
        *,
        event: str,
        payload: dict[str, Any],
    ) -> bool:
        history = case.get("history", [])
        if not history:
            return False
        last = history[-1]
        return (
            isinstance(last, dict)
            and last.get("event") == event
            and last.get("data") == payload
        )

    def register_assessment(
        self,
        case_id: str,
        assessment: CommercialAssessment,
    ) -> dict[str, Any]:
        try:
            case_id = self._normalise_case_id(case_id)
            if not isinstance(assessment, CommercialAssessment):
                raise TypeError("assessment has invalid type")
            payload = self._safe_payload(assessment.to_dict())
        except (SensitiveDataError, TextSafetyError, TypeError, ValueError) as exc:
            raise CommercialMonitorStateError("Commercial assessment was rejected") from exc

        self.recover_pending_audit()

        def register(state: dict[str, Any]) -> dict[str, Any]:
            cases = state["cases"]
            if case_id not in cases:
                if len(cases) >= self.policy.max_cases:
                    raise CommercialMonitorStateError(
                        "Commercial monitor case capacity reached"
                    )
                cases[case_id] = {"history": []}
            case = cases[case_id]
            if self._last_event_matches(case, event="assessment", payload=payload):
                return {"case": copy.deepcopy(case), "updated": False}
            history = case["history"]
            if len(history) >= self.policy.max_history_per_case:
                raise CommercialMonitorStateError(
                    "Commercial monitor history capacity reached"
                )
            timestamp = _now()
            event_id = f"commercial-{uuid4().hex}"
            case["assessment"] = copy.deepcopy(payload)
            case["updated_at"] = timestamp
            history.append(
                {
                    "event": "assessment",
                    "event_id": event_id,
                    "data": copy.deepcopy(payload),
                    "time": timestamp,
                }
            )
            self._queue_event(
                state,
                {
                    "event": "commercial_assessment",
                    "event_id": event_id,
                    "timestamp": timestamp,
                    "case_id": case_id,
                    "assessment": copy.deepcopy(payload),
                },
            )
            return {"case": copy.deepcopy(case), "updated": True}

        result = self._transaction(register)
        return self._complete_mutation(result)["case"]

    def record_comparison(
        self,
        case_id: str,
        comparison: ParallelOutcomeComparison,
    ) -> dict[str, Any]:
        try:
            case_id = self._normalise_case_id(case_id)
            if not isinstance(comparison, ParallelOutcomeComparison):
                raise TypeError("comparison has invalid type")
            payload = self._safe_payload(comparison.to_dict())
        except (SensitiveDataError, TextSafetyError, TypeError, ValueError) as exc:
            raise CommercialMonitorStateError("Commercial comparison was rejected") from exc

        self.recover_pending_audit()

        def record(state: dict[str, Any]) -> dict[str, Any]:
            cases = state["cases"]
            if case_id not in cases:
                if len(cases) >= self.policy.max_cases:
                    raise CommercialMonitorStateError(
                        "Commercial monitor case capacity reached"
                    )
                cases[case_id] = {"history": []}
            case = cases[case_id]
            if self._last_event_matches(case, event="comparison", payload=payload):
                return {"case": copy.deepcopy(case), "updated": False}
            history = case["history"]
            if len(history) >= self.policy.max_history_per_case:
                raise CommercialMonitorStateError(
                    "Commercial monitor history capacity reached"
                )
            timestamp = _now()
            event_id = f"commercial-{uuid4().hex}"
            case["last_comparison"] = copy.deepcopy(payload)
            case["rollback_required"] = comparison.rollback_required
            case["preferred_path"] = comparison.preferred_path
            case["updated_at"] = timestamp
            history.append(
                {
                    "event": "comparison",
                    "event_id": event_id,
                    "data": copy.deepcopy(payload),
                    "time": timestamp,
                }
            )
            self._queue_event(
                state,
                {
                    "event": "commercial_parallel_comparison",
                    "event_id": event_id,
                    "timestamp": timestamp,
                    "case_id": case_id,
                    "comparison": copy.deepcopy(payload),
                },
            )
            return {"case": copy.deepcopy(case), "updated": True}

        result = self._transaction(record)
        return self._complete_mutation(result)["case"]

    def should_use_adjusted_path(self, case_id: str) -> bool:
        try:
            case_id = self._normalise_case_id(case_id)
        except (SensitiveDataError, TextSafetyError, TypeError, ValueError) as exc:
            raise CommercialMonitorStateError("Commercial case id was rejected") from exc
        self.state = self._load()
        case = self.state["cases"].get(case_id, {})
        if case.get("rollback_required"):
            return False
        return case.get("preferred_path") == "with_commercial_adjustment"

    def status(self) -> dict[str, Any]:
        self.state = self._load()
        return {
            "cases": copy.deepcopy(self.state["cases"]),
            "pending_audit_events": len(self.state["pending_audit"]),
            "truth_modified": False,
            "decision_authority": "none",
        }
