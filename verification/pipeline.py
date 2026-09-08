"""Deterministic verification gates for AION candidate knowledge.

LLMs may assist with extraction/classification, but promotion decisions are made
by explicit policy over evidence records. Truth is never modified here.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from memory.store import add_long_term_lesson

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_AUDIT_FILE = ROOT / "audit" / "verification.jsonl"


@dataclass(frozen=True)
class EvidenceItem:
    source_id: str
    source_type: str
    stance: str  # supports | contradicts | neutral
    quality: float
    independent_group: str
    excerpt: str = ""

    def normalised(self) -> "EvidenceItem":
        stance = self.stance.strip().lower()
        if stance not in {"supports", "contradicts", "neutral"}:
            raise ValueError(f"Invalid stance: {self.stance}")
        quality = max(0.0, min(1.0, float(self.quality)))
        return EvidenceItem(
            source_id=self.source_id.strip(),
            source_type=self.source_type.strip().lower(),
            stance=stance,
            quality=quality,
            independent_group=self.independent_group.strip() or self.source_id.strip(),
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


def evaluate_claim(
    claim: str,
    evidence: Iterable[EvidenceItem],
    policy: VerificationPolicy | None = None,
) -> ClaimEvaluation:
    policy = policy or VerificationPolicy()
    claim = claim.strip()
    if not claim:
        raise ValueError("Claim is empty")

    items = [item.normalised() for item in evidence]
    support = [item for item in items if item.stance == "supports"]
    contradictions = [item for item in items if item.stance == "contradicts"]

    weighted_support = round(sum(item.quality for item in support), 4)
    weighted_contradiction = round(sum(item.quality for item in contradictions), 4)
    support_groups = {item.independent_group for item in support}
    average_quality = round(
        sum(item.quality for item in support) / len(support), 4
        if support else 0.0,
        4,
    )
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


def verify_candidate_record(
    candidate: dict[str, Any],
    claim: str,
    evidence: Iterable[EvidenceItem],
    policy: VerificationPolicy | None = None,
) -> dict[str, Any]:
    evaluation = evaluate_claim(claim, evidence, policy)
    result = {
        "candidate_id": candidate.get("candidate_id"),
        "claim_id": _claim_id(claim),
        "claim": claim.strip(),
        "evaluation": evaluation.to_dict(),
        "evidence": [asdict(item.normalised()) for item in evidence],
        "verified_at": _utc_now(),
        "truth_modified": False,
    }
    return result


def append_audit_record(
    record: dict[str, Any],
    audit_file: str | Path = DEFAULT_AUDIT_FILE,
) -> None:
    path = Path(audit_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def promote_verified_claim(
    verification_record: dict[str, Any],
    *,
    audit_file: str | Path = DEFAULT_AUDIT_FILE,
) -> dict[str, Any]:
    evaluation = verification_record.get("evaluation", {})
    if evaluation.get("decision") != "verified":
        raise ValueError("Only verified claims may be promoted")

    claim = str(verification_record.get("claim", "")).strip()
    if not claim:
        raise ValueError("Verified claim is empty")

    add_long_term_lesson(claim)
    audit_record = {
        "event": "promote_to_long_term",
        "claim_id": verification_record.get("claim_id") or _claim_id(claim),
        "candidate_id": verification_record.get("candidate_id"),
        "claim": claim,
        "evaluation": evaluation,
        "promoted_at": _utc_now(),
        "destination": "knowledge/long_term/knowledge.json",
        "truth_modified": False,
    }
    append_audit_record(audit_record, audit_file)
    return audit_record
