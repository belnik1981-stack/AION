"""Deterministic verification gates for AION candidate knowledge.

LLMs may assist with extraction/classification, but promotion decisions are made
by explicit policy over evidence records. Promotion always re-evaluates evidence
and verifies an integrity hash. Truth is never modified here.
"""
from __future__ import annotations

import hashlib
import json
import math
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
MODEL_SOURCE_TYPES = frozenset({"llm", "model", "model_output", "chat", "chat_export"})
MAX_CLAIM_CHARS = 100_000
MAX_EVIDENCE_ITEMS = 1_000
MAX_EVIDENCE_TOTAL_TEXT_CHARS = 1_000_000
MAX_SOURCE_ID_CHARS = 2_048
MAX_SOURCE_TYPE_CHARS = 128
MAX_DEPENDENCY_GROUP_CHARS = 2_048
MAX_EXCERPT_CHARS = 250_000


@dataclass(frozen=True)
class EvidenceItem:
    source_id: str
    source_type: str
    stance: str
    quality: float
    independent_group: str
    excerpt: str = ""

    def normalised(self) -> "EvidenceItem":
        for field_name, value in (
            ("source_id", self.source_id),
            ("source_type", self.source_type),
            ("stance", self.stance),
            ("independent_group", self.independent_group),
            ("excerpt", self.excerpt),
        ):
            if not isinstance(value, str):
                raise TypeError(f"Evidence {field_name} must be a string")
        stance = self.stance.strip().lower()
        if stance not in {"supports", "contradicts", "neutral"}:
            raise ValueError(f"Invalid stance: {self.stance}")
        if isinstance(self.quality, bool):
            raise TypeError("Evidence quality must be numeric")
        quality = float(self.quality)
        if not math.isfinite(quality):
            raise ValueError("Evidence quality must be finite")
        quality = max(0.0, min(1.0, quality))
        source_id = self.source_id.strip()
        if not source_id:
            raise ValueError("Evidence source_id is empty")
        if len(source_id) > MAX_SOURCE_ID_CHARS:
            raise ValueError("Evidence source_id is too long")
        source_type = self.source_type.strip().lower()
        if not source_type:
            raise ValueError("Evidence source_type is empty")
        if len(source_type) > MAX_SOURCE_TYPE_CHARS:
            raise ValueError("Evidence source_type is too long")
        independent_group = self.independent_group.strip() or source_id
        if len(independent_group) > MAX_DEPENDENCY_GROUP_CHARS:
            raise ValueError("Evidence independent_group is too long")
        excerpt = self.excerpt.strip()
        if len(excerpt) > MAX_EXCERPT_CHARS:
            raise ValueError("Evidence excerpt is too long")
        return EvidenceItem(
            source_id=source_id,
            source_type=source_type,
            stance=stance,
            quality=quality,
            independent_group=independent_group,
            excerpt=excerpt,
        )


@dataclass(frozen=True)
class VerificationPolicy:
    min_supporting_sources: int = 2
    min_independent_groups: int = 2
    min_weighted_support: float = 1.4
    max_weighted_contradiction: float = 0.35
    min_average_quality: float = 0.65
    require_non_llm_source: bool = True


MINIMUM_PROMOTION_POLICY = VerificationPolicy()


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


@dataclass(frozen=True)
class RevalidatedVerification:
    """A verification record reconstructed from its authoritative inputs."""

    candidate_id: Any
    claim_id: str
    claim: str
    policy: VerificationPolicy
    evaluation: ClaimEvaluation
    evidence: tuple[EvidenceItem, ...]
    verification_hash: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalise_claim(claim: str) -> str:
    if not isinstance(claim, str):
        raise TypeError("Claim must be a string")
    claim = claim.strip()
    if not claim:
        raise ValueError("Claim is empty")
    if len(claim) > MAX_CLAIM_CHARS:
        raise ValueError("Claim is too long")
    return claim


def _normalise_evidence(evidence: Iterable[EvidenceItem]) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    total_text_chars = 0
    for index, item in enumerate(evidence):
        if index >= MAX_EVIDENCE_ITEMS:
            raise ValueError("Verification evidence exceeds the item limit")
        if not isinstance(item, EvidenceItem):
            raise TypeError("Verification evidence item has invalid type")
        normalised = item.normalised()
        total_text_chars += sum((
            len(normalised.source_id),
            len(normalised.source_type),
            len(normalised.stance),
            len(normalised.independent_group),
            len(normalised.excerpt),
        ))
        if total_text_chars > MAX_EVIDENCE_TOTAL_TEXT_CHARS:
            raise ValueError("Verification evidence exceeds the text limit")
        items.append(normalised)
    return items


def _claim_id(claim: str) -> str:
    return hashlib.sha256(_normalise_claim(claim).encode("utf-8")).hexdigest()[:20]


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _normalise_policy(policy: VerificationPolicy) -> VerificationPolicy:
    if not isinstance(policy, VerificationPolicy):
        raise TypeError("Verification policy has invalid type")

    counts: dict[str, int] = {}
    for field_name in ("min_supporting_sources", "min_independent_groups"):
        value = getattr(policy, field_name)
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"Verification policy {field_name} must be an integer")
        if value < 1 or value > 10_000:
            raise ValueError(f"Verification policy {field_name} is out of bounds")
        counts[field_name] = value

    numbers: dict[str, float] = {}
    for field_name in (
        "min_weighted_support",
        "max_weighted_contradiction",
        "min_average_quality",
    ):
        value = getattr(policy, field_name)
        if isinstance(value, bool):
            raise TypeError(f"Verification policy {field_name} must be numeric")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise TypeError(f"Verification policy {field_name} must be numeric") from exc
        if not math.isfinite(number):
            raise ValueError(f"Verification policy {field_name} must be finite")
        numbers[field_name] = number

    if not 0.0 <= numbers["min_weighted_support"] <= 10_000.0:
        raise ValueError("Verification policy min_weighted_support is out of bounds")
    if not 0.0 <= numbers["max_weighted_contradiction"] <= 10_000.0:
        raise ValueError("Verification policy max_weighted_contradiction is out of bounds")
    if not 0.0 <= numbers["min_average_quality"] <= 1.0:
        raise ValueError("Verification policy min_average_quality is out of bounds")
    if not isinstance(policy.require_non_llm_source, bool):
        raise TypeError("Verification policy require_non_llm_source must be boolean")

    return VerificationPolicy(
        min_supporting_sources=counts["min_supporting_sources"],
        min_independent_groups=counts["min_independent_groups"],
        min_weighted_support=numbers["min_weighted_support"],
        max_weighted_contradiction=numbers["max_weighted_contradiction"],
        min_average_quality=numbers["min_average_quality"],
        require_non_llm_source=policy.require_non_llm_source,
    )


def _policy_is_at_least_as_strict(
    policy: VerificationPolicy,
    baseline: VerificationPolicy = MINIMUM_PROMOTION_POLICY,
) -> bool:
    policy = _normalise_policy(policy)
    baseline = _normalise_policy(baseline)
    return (
        policy.min_supporting_sources >= baseline.min_supporting_sources
        and policy.min_independent_groups >= baseline.min_independent_groups
        and policy.min_weighted_support >= baseline.min_weighted_support
        and policy.max_weighted_contradiction <= baseline.max_weighted_contradiction
        and policy.min_average_quality >= baseline.min_average_quality
        and (
            not baseline.require_non_llm_source
            or policy.require_non_llm_source
        )
    )


def verification_hash(*, candidate_id: Any, claim: str, evidence: Iterable[EvidenceItem], policy: VerificationPolicy) -> str:
    claim = _normalise_claim(claim)
    policy = _normalise_policy(policy)
    payload = {
        "candidate_id": candidate_id,
        "claim": claim,
        "evidence": [asdict(item) for item in _normalise_evidence(evidence)],
        "policy": asdict(policy),
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def evaluate_claim(claim: str, evidence: Iterable[EvidenceItem], policy: VerificationPolicy | None = None) -> ClaimEvaluation:
    policy = _normalise_policy(policy or VerificationPolicy())
    claim = _normalise_claim(claim)

    items = _normalise_evidence(evidence)
    support_items = [item for item in items if item.stance == "supports"]
    contradiction_items = [item for item in items if item.stance == "contradicts"]
    support_by_source: dict[str, list[EvidenceItem]] = {}
    contradictions_by_source: dict[str, list[EvidenceItem]] = {}
    for item in support_items:
        support_by_source.setdefault(item.source_id, []).append(item)
    for item in contradiction_items:
        contradictions_by_source.setdefault(item.source_id, []).append(item)

    support_quality = {
        source_id: max(item.quality for item in source_items)
        for source_id, source_items in support_by_source.items()
    }
    contradiction_quality = {
        source_id: max(item.quality for item in source_items)
        for source_id, source_items in contradictions_by_source.items()
    }
    weighted_support = round(sum(support_quality.values()), 4)
    weighted_contradiction = round(sum(contradiction_quality.values()), 4)

    support_groups: set[str] = set()
    for source_items in support_by_source.values():
        groups = {item.independent_group for item in source_items}
        if len(groups) == 1:
            group = next(iter(groups))
            if not group.startswith("unverified:"):
                support_groups.add(group)

    average_quality = (
        round(weighted_support / len(support_by_source), 4)
        if support_by_source
        else 0.0
    )
    has_non_llm_support = any(
        all(item.source_type not in MODEL_SOURCE_TYPES for item in source_items)
        for source_items in support_by_source.values()
    )

    reasons: list[str] = []
    if len(support_by_source) < policy.min_supporting_sources:
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

    if not support_by_source:
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
        supporting_sources=len(support_by_source),
        independent_support_groups=len(support_groups),
        average_support_quality=average_quality,
        has_non_llm_support=has_non_llm_support,
        reasons=reasons,
    )


def verify_candidate_record(candidate: dict[str, Any], claim: str, evidence: Iterable[EvidenceItem], policy: VerificationPolicy | None = None) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        raise TypeError("Candidate must be an object")
    policy = _normalise_policy(policy or VerificationPolicy())
    claim = _normalise_claim(claim)
    items = _normalise_evidence(evidence)
    evaluation = evaluate_claim(claim, items, policy)
    candidate_id = candidate.get("candidate_id")
    integrity = verification_hash(candidate_id=candidate_id, claim=claim, evidence=items, policy=policy)
    return {
        "candidate_id": candidate_id,
        "claim_id": _claim_id(claim),
        "claim": claim,
        "policy": asdict(policy),
        "evaluation": evaluation.to_dict(),
        "evidence": [asdict(item) for item in items],
        "verification_hash": integrity,
        "verified_at": _utc_now(),
        "truth_modified": False,
    }


def revalidate_verification_record(
    verification_record: dict[str, Any],
) -> RevalidatedVerification:
    """Recompute and strictly compare a stored verification record.

    The integrity hash deliberately covers the candidate identity, claim,
    evidence and policy.  The derived claim id and every evaluation field are
    compared separately so callers cannot replace derived metadata while
    retaining a valid input hash.
    """

    if not isinstance(verification_record, dict):
        raise TypeError("Verification record must be an object")
    if verification_record.get("truth_modified") is not False:
        raise ValueError("Verification record does not preserve Truth")

    claim, evidence, policy = _reconstruct_record(verification_record)
    candidate_id = verification_record.get("candidate_id")
    expected_hash = verification_hash(
        candidate_id=candidate_id,
        claim=claim,
        evidence=evidence,
        policy=policy,
    )
    supplied_hash = verification_record.get("verification_hash")
    if not isinstance(supplied_hash, str) or supplied_hash != expected_hash:
        raise ValueError("Verification integrity hash mismatch")

    expected_claim_id = _claim_id(claim)
    if verification_record.get("claim_id") != expected_claim_id:
        raise ValueError("Verification claim id mismatch")

    fresh_evaluation = evaluate_claim(claim, evidence, policy)
    if verification_record.get("evaluation") != fresh_evaluation.to_dict():
        raise ValueError("Stored evaluation does not match fresh verification")

    return RevalidatedVerification(
        candidate_id=candidate_id,
        claim_id=expected_claim_id,
        claim=claim,
        policy=policy,
        evaluation=fresh_evaluation,
        evidence=tuple(evidence),
        verification_hash=expected_hash,
    )


def append_audit_record(record: dict[str, Any], audit_file: str | Path = DEFAULT_AUDIT_FILE) -> None:
    safe_record, redactions = redact_structure(record)
    if redactions:
        raise SensitiveDataError("Audit append заблокирован: обнаружены чувствительные данные")
    unique_field = "event_id" if safe_record.get("event_id") else None
    append_jsonl_record(audit_file, safe_record, unique_field=unique_field)


def _reconstruct_record(verification_record: dict[str, Any]) -> tuple[str, list[EvidenceItem], VerificationPolicy]:
    claim = _normalise_claim(verification_record.get("claim"))
    raw_policy = verification_record.get("policy")
    if not isinstance(raw_policy, dict):
        raise ValueError("Verification policy missing")
    policy = _normalise_policy(VerificationPolicy(**raw_policy))
    raw_evidence = verification_record.get("evidence")
    if not isinstance(raw_evidence, list) or not raw_evidence:
        raise ValueError("Verification evidence missing")
    if len(raw_evidence) > MAX_EVIDENCE_ITEMS:
        raise ValueError("Verification evidence exceeds the item limit")
    evidence = _normalise_evidence([EvidenceItem(**item) for item in raw_evidence])
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
    if not isinstance(reviewed_by, str):
        raise TypeError("Explicit reviewer identity must be a string")
    reviewer = reviewed_by.strip()
    if not reviewer:
        raise ValueError("Explicit reviewer identity is required")

    validated = revalidate_verification_record(verification_record)
    claim = validated.claim
    evidence = validated.evidence
    policy = validated.policy
    expected_hash = validated.verification_hash
    fresh_evaluation = validated.evaluation
    if not _policy_is_at_least_as_strict(policy):
        raise ValueError("Verification policy is weaker than the promotion minimum")
    if fresh_evaluation.decision != "verified":
        raise ValueError("Fresh verification does not permit promotion")

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
        "claim_id": validated.claim_id,
        "candidate_id": validated.candidate_id,
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
