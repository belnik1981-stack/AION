"""Deterministic, fail-closed information-cleaning trial.

This package is deliberately isolated from AION runtime.  It never imports
core, providers, memory, networking libraries, or an LLM SDK.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import tempfile
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

CONTRACT_VERSION = "aion-information-cleaning-trial-v1"
ANALYSIS_ONLY = "ANALYSIS_ONLY"
DENIED = "DENIED"

MAX_SOURCES = 200
MAX_CLAIM_CHARS = 2_000
MAX_CONTENT_CHARS = 20_000
MIN_SUPPORT_QUALITY = 0.65
MATERIAL_CONTRADICTION_QUALITY = 0.65

RISK_MIN_VERIFIED_ROOTS = {
    "low": 1,
    "moderate": 2,
    "high": 2,
    "critical": 2,
}
ROOT_VERIFICATION = {"unverified", "partial", "verified"}
ROOT_VERIFICATION_RANK = {"unverified": 0, "partial": 1, "verified": 2}
STANCES = {"supports", "contradicts", "neutral"}
RELEVANCE = {"relevant", "noise"}
SAFE_IDENTIFIER = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")

_SENSITIVE_PATTERNS = (
    re.compile(r"\bsk-or-v1-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{16,}=*\b", re.IGNORECASE),
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
)


class TrialInputError(ValueError):
    """Raised when a trial input cannot be processed safely."""


def normalize_text(value: str) -> str:
    if not isinstance(value, str):
        raise TrialInputError("text fields must be strings")
    text = unicodedata.normalize("NFKC", value)
    text = "".join(
        char if char in "\n\t" or unicodedata.category(char) != "Cc" else " "
        for char in text
    )
    return re.sub(r"\s+", " ", text).strip()


def redact_sensitive(text: str) -> tuple[str, int]:
    redacted = text
    count = 0
    for pattern in _SENSITIVE_PATTERNS:
        redacted, matches = pattern.subn("[REDACTED_SENSITIVE]", redacted)
        count += matches
    return redacted, count


def fingerprint(text: str) -> str:
    try:
        canonical = normalize_text(text).casefold().encode("utf-8")
    except UnicodeEncodeError as exc:
        raise TrialInputError("text contains invalid Unicode") from exc
    return hashlib.sha256(canonical).hexdigest()


def _required_text(record: dict[str, Any], field: str, *, limit: int = 500) -> str:
    value = normalize_text(record.get(field, ""))
    if not value:
        raise TrialInputError(f"{field} is required")
    if len(value) > limit:
        raise TrialInputError(f"{field} exceeds {limit} characters")
    return value


def _identifier(record: dict[str, Any], field: str) -> str:
    value = _required_text(record, field, limit=128)
    if not SAFE_IDENTIFIER.fullmatch(value):
        raise TrialInputError(
            f"{field} must use only ASCII letters, digits, dot, underscore, colon, or hyphen"
        )
    return value


def _quality(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TrialInputError("quality must be a finite number between 0 and 1")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise TrialInputError("quality must be a finite number between 0 and 1")
    return result


def _clean_source(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise TrialInputError("each source must be an object")

    root_verification = _required_text(raw, "root_verification").lower()
    stance = _required_text(raw, "stance").lower()
    relevance = _required_text(raw, "relevance").lower()
    if root_verification not in ROOT_VERIFICATION:
        raise TrialInputError(f"invalid root_verification: {root_verification}")
    if stance not in STANCES:
        raise TrialInputError(f"invalid stance: {stance}")
    if relevance not in RELEVANCE:
        raise TrialInputError(f"invalid relevance: {relevance}")

    content = _required_text(raw, "content", limit=MAX_CONTENT_CHARS)
    content, redactions = redact_sensitive(content)
    return {
        "source_id": _identifier(raw, "source_id"),
        "source_type": _identifier(raw, "source_type").lower(),
        "dependency_root": _identifier(raw, "dependency_root"),
        "root_verification": root_verification,
        "stance": stance,
        "relevance": relevance,
        "quality": _quality(raw.get("quality")),
        "content": content,
        "content_fingerprint": fingerprint(content),
        "redactions": redactions,
    }


def _clean_sources(raw_sources: Any) -> dict[str, Any]:
    if not isinstance(raw_sources, list) or not raw_sources:
        raise TrialInputError("sources must be a non-empty list")
    if len(raw_sources) > MAX_SOURCES:
        raise TrialInputError(f"sources exceed safe limit of {MAX_SOURCES}")

    relevant: list[dict[str, Any]] = []
    quarantined_noise: list[dict[str, Any]] = []
    duplicate_source_ids: list[str] = []
    duplicate_conflicts: list[dict[str, Any]] = []
    seen_fingerprints: dict[str, dict[str, Any]] = {}
    seen_source_ids: set[str] = set()
    redactions = 0

    for raw in raw_sources:
        item = _clean_source(raw)
        if item["source_id"] in seen_source_ids:
            raise TrialInputError(f"duplicate source_id: {item['source_id']}")
        seen_source_ids.add(item["source_id"])
        redactions += item["redactions"]
        previous = seen_fingerprints.get(item["content_fingerprint"])
        if previous is not None:
            duplicate_source_ids.append(item["source_id"])
            compared_fields = (
                "source_type",
                "dependency_root",
                "root_verification",
                "stance",
                "relevance",
                "quality",
            )
            mismatches = [
                field for field in compared_fields if item[field] != previous[field]
            ]
            if mismatches:
                duplicate_conflicts.append({
                    "content_fingerprint": item["content_fingerprint"],
                    "first_source_id": previous["source_id"],
                    "duplicate_source_id": item["source_id"],
                    "conflicting_fields": mismatches,
                })
            if item["relevance"] == "noise":
                quarantined_noise.append({
                    "source_id": item["source_id"],
                    "content_fingerprint": item["content_fingerprint"],
                    "reason": "explicit_test_fixture_noise_label",
                })
            continue

        seen_fingerprints[item["content_fingerprint"]] = item
        if item["relevance"] == "noise":
            quarantined_noise.append({
                "source_id": item["source_id"],
                "content_fingerprint": item["content_fingerprint"],
                "reason": "explicit_test_fixture_noise_label",
            })
            continue
        relevant.append(item)

    return {
        "cleaned_sources": relevant,
        "quarantined_noise": quarantined_noise,
        "duplicate_source_ids": duplicate_source_ids,
        "duplicate_conflicts": duplicate_conflicts,
        "redactions": redactions,
        "relevant_sources_seen": len(raw_sources) - len(quarantined_noise),
    }


def _root_summaries(sources: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in sources:
        grouped[item["dependency_root"]].append(item)

    summaries: list[dict[str, Any]] = []
    for root_id in sorted(grouped):
        items = grouped[root_id]
        verification = min(
            (item["root_verification"] for item in items),
            key=lambda status: ROOT_VERIFICATION_RANK[status],
        )
        support = [item for item in items if item["stance"] == "supports"]
        contradictions = [item for item in items if item["stance"] == "contradicts"]
        summaries.append({
            "dependency_root": root_id,
            "root_verification": verification,
            "source_count": len(items),
            "support_count": len(support),
            "contradiction_count": len(contradictions),
            "max_support_quality": max((item["quality"] for item in support), default=0.0),
            "max_contradiction_quality": max(
                (item["quality"] for item in contradictions), default=0.0
            ),
        })
    return summaries


def evaluate_scenario(scenario: Any) -> dict[str, Any]:
    if not isinstance(scenario, dict):
        raise TrialInputError("scenario must be an object")

    scenario_id = _identifier(scenario, "scenario_id")
    claim = _required_text(scenario, "claim", limit=MAX_CLAIM_CHARS)
    claim, claim_redactions = redact_sensitive(claim)
    risk_class = _required_text(scenario, "risk_class").lower()
    if risk_class not in RISK_MIN_VERIFIED_ROOTS:
        raise TrialInputError(f"invalid risk_class: {risk_class}")

    cleaned = _clean_sources(scenario.get("sources"))
    sources = cleaned["cleaned_sources"]
    roots = _root_summaries(sources)
    required_roots = RISK_MIN_VERIFIED_ROOTS[risk_class]

    verified_support_roots = [
        root["dependency_root"]
        for root in roots
        if root["root_verification"] == "verified"
        and root["max_support_quality"] >= MIN_SUPPORT_QUALITY
    ]
    material_contradictions = [
        root["dependency_root"]
        for root in roots
        if root["root_verification"] == "verified"
        and root["max_contradiction_quality"] >= MATERIAL_CONTRADICTION_QUALITY
    ]

    reasons: list[str] = []
    if len(verified_support_roots) < required_roots:
        reasons.append("insufficient_verified_dependency_roots")
    if material_contradictions:
        reasons.append("material_verified_contradiction")
    if cleaned["duplicate_conflicts"]:
        reasons.append("conflicting_duplicate_metadata")

    admitted = not reasons
    admission_token = ANALYSIS_ONLY if admitted else DENIED
    cleaned_knowledge = None
    if admitted:
        cleaned_knowledge = {
            "claim_id": f"claim-{fingerprint(claim)[:20]}",
            "claim": claim,
            "status": "verified_for_analysis",
            "risk_class": risk_class,
            "supporting_dependency_roots": verified_support_roots,
            "evidence_fingerprints": sorted(
                item["content_fingerprint"]
                for item in sources
                if item["stance"] == "supports"
                and item["dependency_root"] in verified_support_roots
            ),
            "contract_version": CONTRACT_VERSION,
            "limitations": ["not_authorized_for_execution"],
        }

    return {
        "scenario_id": scenario_id,
        "contract_version": CONTRACT_VERSION,
        "claim": claim,
        "claim_fingerprint": fingerprint(claim),
        "risk_class": risk_class,
        "metrics": {
            "input_records": len(scenario["sources"]),
            "relevant_sources_seen": cleaned["relevant_sources_seen"],
            "cleaned_sources": len(sources),
            "quarantined_noise": len(cleaned["quarantined_noise"]),
            "duplicates_removed": len(cleaned["duplicate_source_ids"]),
            "sensitive_values_redacted": cleaned["redactions"] + claim_redactions,
            "dependency_roots": len(roots),
            "verified_support_roots": len(verified_support_roots),
            "required_verified_roots": required_roots,
            "material_contradiction_roots": len(material_contradictions),
        },
        "dependency_roots": roots,
        "quarantine": cleaned["quarantined_noise"],
        "duplicate_source_ids": cleaned["duplicate_source_ids"],
        "duplicate_conflicts": cleaned["duplicate_conflicts"],
        "cleaned_evidence": sources,
        "decision": "admitted_for_analysis" if admitted else "quarantined",
        "reasons": reasons,
        "admission_token": admission_token,
        "execution_authorized": False,
        "cleaned_knowledge": cleaned_knowledge,
        "truth_modified": False,
    }


def use_for_analysis(report: Any) -> dict[str, Any]:
    denied = {
        "status": "denied",
        "reason": "evidence_contract_not_satisfied",
        "execution_authorized": False,
    }
    if not isinstance(report, dict) or report.get("admission_token") != ANALYSIS_ONLY:
        return denied
    if (
        report.get("contract_version") != CONTRACT_VERSION
        or report.get("execution_authorized") is not False
        or report.get("truth_modified") is not False
        or report.get("decision") != "admitted_for_analysis"
        or report.get("reasons") != []
    ):
        return denied

    try:
        claim = _required_text(report, "claim", limit=MAX_CLAIM_CHARS)
        risk_class = _required_text(report, "risk_class").lower()
        if risk_class not in RISK_MIN_VERIFIED_ROOTS:
            return denied
        if report.get("claim_fingerprint") != fingerprint(claim):
            return denied
        cleaned = _clean_sources(report.get("cleaned_evidence"))
    except TrialInputError:
        return denied

    sources = cleaned["cleaned_sources"]
    if (
        cleaned["quarantined_noise"]
        or cleaned["duplicate_source_ids"]
        or cleaned["duplicate_conflicts"]
        or len(sources) != len(report["cleaned_evidence"])
    ):
        return denied

    roots = _root_summaries(sources)
    required_roots = RISK_MIN_VERIFIED_ROOTS[risk_class]
    verified_support_roots = [
        root["dependency_root"]
        for root in roots
        if root["root_verification"] == "verified"
        and root["max_support_quality"] >= MIN_SUPPORT_QUALITY
    ]
    material_contradictions = [
        root["dependency_root"]
        for root in roots
        if root["root_verification"] == "verified"
        and root["max_contradiction_quality"] >= MATERIAL_CONTRADICTION_QUALITY
    ]
    if len(verified_support_roots) < required_roots or material_contradictions:
        return denied

    expected_knowledge = {
        "claim_id": f"claim-{fingerprint(claim)[:20]}",
        "claim": claim,
        "status": "verified_for_analysis",
        "risk_class": risk_class,
        "supporting_dependency_roots": verified_support_roots,
        "evidence_fingerprints": sorted(
            item["content_fingerprint"]
            for item in sources
            if item["stance"] == "supports"
            and item["dependency_root"] in verified_support_roots
        ),
        "contract_version": CONTRACT_VERSION,
        "limitations": ["not_authorized_for_execution"],
    }
    knowledge = report.get("cleaned_knowledge")
    if knowledge != expected_knowledge:
        return denied

    return {
        "status": "available_for_analysis",
        "claim_id": knowledge["claim_id"],
        "claim": knowledge["claim"],
        "supporting_dependency_roots": knowledge["supporting_dependency_roots"],
        "execution_authorized": False,
    }


def write_report(report: dict[str, Any], output_path: str | Path) -> Path:
    path = Path(output_path).expanduser().resolve()
    truth_dir = (Path(__file__).resolve().parents[2] / "knowledge" / "truth").resolve()
    if path == truth_dir or truth_dir in path.parents:
        raise TrialInputError("trial output cannot be written into Truth")
    if path.suffix.lower() != ".json":
        raise TrialInputError("trial output must use a .json file")

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    temporary.replace(path)
    return path
