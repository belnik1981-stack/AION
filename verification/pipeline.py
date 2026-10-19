"""Deterministic verification gates for AION candidate knowledge.

LLMs may assist with extraction/classification, but promotion decisions are made
by explicit policy over evidence records. Promotion always re-evaluates evidence
and verifies an integrity hash. Truth is never modified here.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from memory.store import (
    commit_staged_long_term_lesson,
    stage_long_term_lesson,
)
from security.redaction import SensitiveDataError, redact_structure
from storage.atomic_json import append_jsonl_record, load_json, update_json

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_AUDIT_FILE = ROOT / "audit" / "verification.jsonl"
DEFAULT_PROMOTION_JOURNAL = ROOT / "knowledge" / "adaptive" / "promotion_transactions.json"


@dataclass(frozen=True)
class EvidenceItem:
    source_id: str
    source_type: str
    stance: str
    quality: float
    independent_group: str
    excerpt: str = ""

    def normalised(self) -> "EvidenceItem":
        stance = self.stance.strip().lower()
        if stance not in {"supports", "contradicts", "neutral"}:
            raise ValueError(f"Invalid stance: {self.stance}")
        quality = max(0.0, min(1.0, float(self.quality)))
        source_id = self.source_id.strip()
        if not source_id:
            raise ValueError("Evidence source_id is empty")
        return EvidenceItem(
            source_id=source_id,
            source_type=self.source_type.strip().lower(),
            stance=stance,
            quality=quality,
            independent_group=self.independent_group.strip() or source_id,
            excerpt=self.excerpt.strip(),
        )


@dataclass(frozen=True)
class VerificationPolicy:
    min_supporting_sources: int = 2
    min_independent_groups: int = 2
    min_weighted_support: float = 1.4
    max_weighted_contradiction: float = 0.35
    min_average_quality: float = 0.65
    require_non_llm_source: bool = True


@dataclass(frozen=True)
class ClaimEvaluation:
    claim: str
    decision: str
    weighted_support: float
    weighted_contradiction: float
    supporting_sources: int
    independent_support_groups: int
    average_support_quality: float
    has_non_llm_support: bool
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _claim_id(claim: str) -> str:
    return hashlib.sha256(claim.strip().encode("utf-8")).hexdigest()[:20]


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def verification_hash(*, candidate_id: Any, claim: str, evidence: Iterable[EvidenceItem], policy: VerificationPolicy) -> str:
    payload = {
        "candidate_id": candidate_id,
        "claim": claim.strip(),
        "evidence": [asdict(item.normalised()) for item in evidence],
        "policy": asdict(policy),
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def evaluate_claim(claim: str, evidence: Iterable[EvidenceItem], policy: VerificationPolicy | None = None) -> ClaimEvaluation:
    policy = policy or VerificationPolicy()
    claim = claim.strip()
    if not claim:
        raise ValueError("Claim is empty")

    items = [item.normalised() for item in evidence]
    support = [item for item in items if item.stance == "supports"]
    contradictions = [item for item in items if item.stance == "contradicts"]

    weighted_support = round(sum(item.quality for item in support), 4)
    weighted_contradiction = round(sum(item.quality for item in contradictions), 4)
    support_groups = {
        item.independent_group
        for item in support
        if not item.independent_group.startswith("unverified:")
    }
    average_quality = round(sum(item.quality for item in support) / len(support), 4) if support else 0.0
    has_non_llm_support = any(
        item.source_type not in {"llm", "model_output", "chat", "chat_export"}
        for item in support
    )

    reasons: list[str] = []
    if len(support) < policy.min_supporting_sources:
        reasons.append("insufficient_supporting_sources")
    if len(support_groups) < policy.min_independent_groups:
        reasons.append("insufficient_independent_sources")
    if weighted_support < policy.min_weighted_support:
        reasons.append("support_weight_below_threshold")
    if weighted_contradiction > policy.max_weighted_contradiction:
        reasons.append("material_contradiction_present")
    if average_quality < policy.min_average_quality:
        reasons.append("support_quality_below_threshold")
    if policy.require_non_llm_source and not has_non_llm_support:
        reasons.append("no_non_llm_support")

    if not support:
        decision = "unverified"
    elif "material_contradiction_present" in reasons:
        decision = "conflicted"
    elif reasons:
        decision = "needs_more_evidence"
    else:
        decision = "verified"

    return ClaimEvaluation(
        claim=claim,
        decision=decision,
        weighted_support=weighted_support,
        weighted_contradiction=weighted_contradiction,
        supporting_sources=len(support),
        independent_support_groups=len(support_groups),
        average_support_quality=average_quality,
        has_non_llm_support=has_non_llm_support,
        reasons=reasons,
    )


def verify_candidate_record(candidate: dict[str, Any], claim: str, evidence: Iterable[EvidenceItem], policy: VerificationPolicy | None = None) -> dict[str, Any]:
    policy = policy or VerificationPolicy()
    items = [item.normalised() for item in evidence]
    evaluation = evaluate_claim(claim, items, policy)
    candidate_id = candidate.get("candidate_id")
    integrity = verification_hash(candidate_id=candidate_id, claim=claim, evidence=items, policy=policy)
    return {
        "candidate_id": candidate_id,
        "claim_id": _claim_id(claim),
        "claim": claim.strip(),
        "policy": asdict(policy),
        "evaluation": evaluation.to_dict(),
        "evidence": [asdict(item) for item in items],
        "verification_hash": integrity,
        "verified_at": _utc_now(),
        "truth_modified": False,
    }


def append_audit_record(record: dict[str, Any], audit_file: str | Path = DEFAULT_AUDIT_FILE) -> None:
    safe_record, redactions = redact_structure(record)
    if redactions:
        raise SensitiveDataError("Audit append заблокирован: обнаружены чувствительные данные")
    unique_field = "event_id" if safe_record.get("event_id") else None
    append_jsonl_record(audit_file, safe_record, unique_field=unique_field)


def _reconstruct_record(verification_record: dict[str, Any]) -> tuple[str, list[EvidenceItem], VerificationPolicy]:
    claim = str(verification_record.get("claim", "")).strip()
    if not claim:
        raise ValueError("Verified claim is empty")
    raw_policy = verification_record.get("policy")
    if not isinstance(raw_policy, dict):
        raise ValueError("Verification policy missing")
    policy = VerificationPolicy(**raw_policy)
    raw_evidence = verification_record.get("evidence")
    if not isinstance(raw_evidence, list) or not raw_evidence:
        raise ValueError("Verification evidence missing")
    evidence = [EvidenceItem(**item).normalised() for item in raw_evidence]
    return claim, evidence, policy


def _promotion_id(verification_hash_value: str, reviewer: str) -> str:
    payload = f"{verification_hash_value}\n{reviewer}".encode("utf-8")
    return "promotion-" + hashlib.sha256(payload).hexdigest()[:24]


def _journal(path: str | Path) -> dict[str, Any]:
    journal = load_json(path, default_factory=dict, expected_type=dict)
    journal.setdefault("version", 1)
    journal.setdefault("transactions", {})
    if not isinstance(journal["transactions"], dict):
        raise ValueError("Promotion journal transactions must be an object")
    return journal


def _transaction_digest(audit_record: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(audit_record).encode("utf-8")).hexdigest()


def _store_transaction(path: str | Path, transaction: dict[str, Any]) -> dict[str, Any]:
    promotion_id = transaction["promotion_id"]

    def store(journal: dict[str, Any]) -> dict[str, Any]:
        journal.setdefault("version", 1)
        transactions = journal.setdefault("transactions", {})
        if not isinstance(transactions, dict):
            raise ValueError("Promotion journal transactions must be an object")
        existing = transactions.get(promotion_id)
        if existing is not None:
            if (existing.get("transaction_digest") != transaction.get("transaction_digest")
                    or existing.get("claim") != transaction.get("claim")):
                raise ValueError("Promotion transaction identity collision")
            return journal
        transactions[promotion_id] = transaction
        journal["truth_modified"] = False
        return journal

    return update_json(
        path,
        default_factory=dict,
        expected_type=dict,
        updater=store,
    )


def _set_transaction_state(path: str | Path, promotion_id: str, state: str) -> dict[str, Any]:
    def update(journal: dict[str, Any]) -> dict[str, Any]:
        transactions = journal.get("transactions")
        if not isinstance(transactions, dict) or promotion_id not in transactions:
            raise ValueError("Promotion transaction not found")
        transactions[promotion_id]["state"] = state
        transactions[promotion_id]["updated_at"] = _utc_now()
        journal["truth_modified"] = False
        return journal

    journal = update_json(
        path,
        default_factory=dict,
        expected_type=dict,
        updater=update,
    )
    return journal["transactions"][promotion_id]


def _advance_promotion(
    transaction: dict[str, Any],
    *,
    journal_file: str | Path,
    audit_file: str | Path,
) -> dict[str, Any]:
    promotion_id = transaction["promotion_id"]
    claim = transaction["claim"]
    audit_record = transaction["audit_record"]
    if transaction.get("transaction_digest") != _transaction_digest(audit_record):
        raise ValueError("Promotion transaction integrity mismatch")

    states = {
        "prepared": 0,
        "audit_prepared": 1,
        "memory_staged": 2,
        "audit_committed": 3,
        "committed": 4,
    }
    state = transaction.get("state")
    if state not in states:
        raise ValueError("Unknown promotion transaction state")
    rank = states[state]

    if rank < 1:
        append_audit_record({
            "event": "promotion_prepared",
            "event_id": f"{promotion_id}:prepared",
            "promotion_id": promotion_id,
            "claim_id": audit_record["claim_id"],
            "verification_hash": audit_record["verification_hash"],
            "reviewed_by": audit_record["reviewed_by"],
            "timestamp": _utc_now(),
            "truth_modified": False,
        }, audit_file)
        transaction = _set_transaction_state(journal_file, promotion_id, "audit_prepared")
        rank = 1

    if rank < 2:
        stage_long_term_lesson(claim, promotion_id)
        transaction = _set_transaction_state(journal_file, promotion_id, "memory_staged")
        rank = 2

    if rank < 3:
        append_audit_record(audit_record, audit_file)
        transaction = _set_transaction_state(journal_file, promotion_id, "audit_committed")
        rank = 3

    if rank < 4:
        commit_staged_long_term_lesson(claim, promotion_id)
        _set_transaction_state(journal_file, promotion_id, "committed")

    return audit_record


def recover_pending_promotions(
    *,
    journal_file: str | Path = DEFAULT_PROMOTION_JOURNAL,
    audit_file: str | Path = DEFAULT_AUDIT_FILE,
) -> dict[str, Any]:
    journal = _journal(journal_file)
    recovered = 0
    already_committed = 0
    for promotion_id in sorted(journal["transactions"]):
        transaction = journal["transactions"][promotion_id]
        if transaction.get("state") == "committed":
            already_committed += 1
            continue
        _advance_promotion(
            transaction,
            journal_file=journal_file,
            audit_file=audit_file,
        )
        recovered += 1
    return {
        "status": "ok",
        "recovered": recovered,
        "already_committed": already_committed,
        "truth_modified": False,
    }


def promote_verified_claim(
    verification_record: dict[str, Any],
    *,
    reviewed_by: str,
    audit_file: str | Path = DEFAULT_AUDIT_FILE,
    journal_file: str | Path = DEFAULT_PROMOTION_JOURNAL,
) -> dict[str, Any]:
    reviewer = reviewed_by.strip()
    if not reviewer:
        raise ValueError("Explicit reviewer identity is required")

    claim, evidence, policy = _reconstruct_record(verification_record)
    expected_hash = verification_hash(
        candidate_id=verification_record.get("candidate_id"),
        claim=claim,
        evidence=evidence,
        policy=policy,
    )
    supplied_hash = str(verification_record.get("verification_hash", ""))
    if not supplied_hash or supplied_hash != expected_hash:
        raise ValueError("Verification integrity hash mismatch")

    fresh_evaluation = evaluate_claim(claim, evidence, policy)
    if fresh_evaluation.decision != "verified":
        raise ValueError("Fresh verification does not permit promotion")

    supplied_evaluation = verification_record.get("evaluation", {})
    if supplied_evaluation.get("decision") != fresh_evaluation.decision:
        raise ValueError("Stored evaluation does not match fresh verification")

    safe_payload, redactions = redact_structure({
        "claim": claim,
        "evidence": [asdict(item) for item in evidence],
        "reviewed_by": reviewer,
    })
    if redactions:
        raise SensitiveDataError(
            "Promotion заблокирован: claim, evidence или reviewer содержит чувствительные данные"
        )
    claim = safe_payload["claim"]
    reviewer = safe_payload["reviewed_by"]
    promotion_id = _promotion_id(expected_hash, reviewer)

    existing_journal = _journal(journal_file)
    existing = existing_journal["transactions"].get(promotion_id)
    if existing is not None:
        if (existing.get("claim") != claim
                or existing.get("verification_hash") != expected_hash
                or existing.get("reviewed_by") != reviewer):
            raise ValueError("Existing promotion transaction does not match request")
        return _advance_promotion(
            existing,
            journal_file=journal_file,
            audit_file=audit_file,
        )

    audit_record = {
        "event": "promote_to_long_term",
        "event_id": f"{promotion_id}:committed",
        "promotion_id": promotion_id,
        "claim_id": verification_record.get("claim_id") or _claim_id(claim),
        "candidate_id": verification_record.get("candidate_id"),
        "claim": claim,
        "policy": asdict(policy),
        "evaluation": fresh_evaluation.to_dict(),
        "evidence": [asdict(item) for item in evidence],
        "verification_hash": expected_hash,
        "reviewed_by": reviewer,
        "promoted_at": _utc_now(),
        "destination": "knowledge/long_term/knowledge.json",
        "truth_modified": False,
    }
    transaction = {
        "promotion_id": promotion_id,
        "state": "prepared",
        "claim": claim,
        "claim_id": audit_record["claim_id"],
        "verification_hash": expected_hash,
        "reviewed_by": reviewer,
        "audit_record": audit_record,
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "truth_modified": False,
    }
    transaction["transaction_digest"] = _transaction_digest(audit_record)
    _store_transaction(journal_file, transaction)
    return _advance_promotion(
        transaction,
        journal_file=journal_file,
        audit_file=audit_file,
    )
