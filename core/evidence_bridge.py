"""Integrity-bound bridge from Evidence Objects v2 into the runtime.

The bridge revalidates an offline bundle and emits a bounded, analysis-only
context. The context is integrity-bound so downstream code cannot silently
replace its claims while continuing to label them as validated bundle data.
It never authorizes execution, Truth updates or memory promotion.
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import re
import secrets
from pathlib import Path
from typing import Any

from security.redaction import TextSafetyError, redact_sensitive, redact_structure
from trials.evidence_objects_v2.validator import (
    ANALYSIS_ONLY,
    CONTRACT_VERSION,
    evaluate_bundle,
    load_bundle,
    use_for_analysis,
)


CONTEXT_SCHEMA_VERSION = "aion-analysis-evidence-context-v1"
MAX_CONTEXT_BYTES = 1024 * 1024
MAX_PROMPT_CHARS = 50_000
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_VERSIONED_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}@[1-9][0-9]{0,6}$")
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_CONTEXT_HMAC_KEY = secrets.token_bytes(32)
_CONTEXT_KEYS = {
    "schema_version",
    "contract_version",
    "status",
    "bundle_id",
    "bundle_digest",
    "report_digest",
    "claims",
    "claim_count",
    "report",
    "execution_authorized",
    "truth_update_authorized",
    "memory_promotion_authorized",
    "objective_truth_verified",
    "external_authenticity_verified",
    "truth_modified",
    "context_digest",
    "context_seal",
}
_CLAIM_KEYS = {
    "claim_id",
    "claim_version",
    "text",
    "claim_type",
    "scope",
    "risk_class",
    "evidence_refs",
    "revision",
    "qualified_support_roots",
}
_REPORT_KEYS = {
    "status",
    "admission_token",
    "execution_authorized",
    "artifacts_integrity_checked",
    "evidence_integrity_checked",
    "report_digest",
}


class EvidenceBridgeError(ValueError):
    """Evidence cannot cross the analysis-only bridge."""


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise EvidenceBridgeError("evidence_context_not_canonical") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _seal(value: Any) -> str:
    return hmac.new(_CONTEXT_HMAC_KEY, _canonical(value), hashlib.sha256).hexdigest()


def _is_identifier(value: Any, maximum: int = 128) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= maximum
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", value) is not None
    )


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and _DIGEST.fullmatch(value) is not None


def _validate_claim(claim: Any) -> None:
    if not isinstance(claim, dict) or set(claim) != _CLAIM_KEYS:
        raise EvidenceBridgeError("evidence_context_claim_invalid")
    if not _is_identifier(claim["claim_id"]):
        raise EvidenceBridgeError("evidence_context_claim_invalid")
    version = claim["claim_version"]
    if isinstance(version, bool) or not isinstance(version, int) or not 1 <= version <= 1_000_000:
        raise EvidenceBridgeError("evidence_context_claim_invalid")
    if not isinstance(claim["text"], str) or not 1 <= len(claim["text"]) <= 2_000:
        raise EvidenceBridgeError("evidence_context_claim_invalid")
    if claim["claim_type"] not in {
        "observation",
        "source_statement",
        "inference",
        "assumption",
        "prediction",
    }:
        raise EvidenceBridgeError("evidence_context_claim_invalid")
    if not isinstance(claim["scope"], str) or not 1 <= len(claim["scope"]) <= 1_000:
        raise EvidenceBridgeError("evidence_context_claim_invalid")
    if claim["risk_class"] not in {"R0", "R1", "R2", "R3"}:
        raise EvidenceBridgeError("evidence_context_claim_invalid")

    refs = claim["evidence_refs"]
    if not isinstance(refs, list) or not 1 <= len(refs) <= 200:
        raise EvidenceBridgeError("evidence_context_claim_invalid")
    ref_identities: set[tuple[str, int]] = set()
    for ref in refs:
        if not isinstance(ref, dict) or set(ref) != {"evidence_id", "evidence_version"}:
            raise EvidenceBridgeError("evidence_context_claim_invalid")
        ref_version = ref["evidence_version"]
        if (
            not _is_identifier(ref["evidence_id"])
            or isinstance(ref_version, bool)
            or not isinstance(ref_version, int)
            or not 1 <= ref_version <= 1_000_000
        ):
            raise EvidenceBridgeError("evidence_context_claim_invalid")
        identity = (ref["evidence_id"], ref_version)
        if identity in ref_identities:
            raise EvidenceBridgeError("evidence_context_claim_invalid")
        ref_identities.add(identity)

    revision = claim["revision"]
    if not isinstance(revision, dict) or set(revision) != {
        "previous_claim_ref",
        "changed_at",
        "reason",
    }:
        raise EvidenceBridgeError("evidence_context_claim_invalid")
    if revision["previous_claim_ref"] is not None and (
        not isinstance(revision["previous_claim_ref"], str)
        or _VERSIONED_REF.fullmatch(revision["previous_claim_ref"]) is None
    ):
        raise EvidenceBridgeError("evidence_context_claim_invalid")
    if (
        not isinstance(revision["changed_at"], str)
        or _TIMESTAMP.fullmatch(revision["changed_at"]) is None
    ):
        raise EvidenceBridgeError("evidence_context_claim_invalid")
    if revision["reason"] is not None and (
        not isinstance(revision["reason"], str) or len(revision["reason"]) > 500
    ):
        raise EvidenceBridgeError("evidence_context_claim_invalid")

    roots = claim["qualified_support_roots"]
    if not isinstance(roots, list) or len(roots) > 3_200:
        raise EvidenceBridgeError("evidence_context_claim_invalid")
    if any(
        not isinstance(root, str) or _VERSIONED_REF.fullmatch(root) is None
        for root in roots
    ):
        raise EvidenceBridgeError("evidence_context_claim_invalid")
    if len(roots) != len(set(roots)):
        raise EvidenceBridgeError("evidence_context_claim_invalid")


def revalidate_analysis_evidence_context(value: Any) -> dict[str, Any]:
    """Recheck structure, authority flags and digest of a bridge context."""

    if not isinstance(value, dict) or set(value) != _CONTEXT_KEYS:
        raise EvidenceBridgeError("evidence_context_invalid")
    try:
        safe, redactions = redact_structure(value)
    except (TypeError, TextSafetyError) as exc:
        raise EvidenceBridgeError("evidence_context_out_of_bounds") from exc
    if redactions or not isinstance(safe, dict):
        raise EvidenceBridgeError("evidence_context_sensitive")
    if len(_canonical(safe)) > MAX_CONTEXT_BYTES:
        raise EvidenceBridgeError("evidence_context_out_of_bounds")

    supplied_seal = safe.get("context_seal")
    if not _is_digest(supplied_seal):
        raise EvidenceBridgeError("evidence_context_seal_invalid")
    sealed_payload = copy.deepcopy(safe)
    sealed_payload.pop("context_seal")
    if not hmac.compare_digest(supplied_seal, _seal(sealed_payload)):
        raise EvidenceBridgeError("evidence_context_seal_mismatch")

    supplied_digest = sealed_payload.get("context_digest")
    if not _is_digest(supplied_digest):
        raise EvidenceBridgeError("evidence_context_digest_invalid")
    digest_payload = copy.deepcopy(sealed_payload)
    digest_payload.pop("context_digest")
    expected_digest = _digest(digest_payload)
    if not hmac.compare_digest(supplied_digest, expected_digest):
        raise EvidenceBridgeError("evidence_context_digest_mismatch")

    if (
        safe["schema_version"] != CONTEXT_SCHEMA_VERSION
        or safe["contract_version"] != CONTRACT_VERSION
        or safe["status"] != "available_for_analysis"
        or not _is_identifier(safe["bundle_id"])
        or not _is_digest(safe["bundle_digest"])
        or not _is_digest(safe["report_digest"])
    ):
        raise EvidenceBridgeError("evidence_context_metadata_invalid")
    for field in (
        "execution_authorized",
        "truth_update_authorized",
        "memory_promotion_authorized",
        "objective_truth_verified",
        "external_authenticity_verified",
        "truth_modified",
    ):
        if safe[field] is not False:
            raise EvidenceBridgeError("evidence_context_authority_invalid")

    claims = safe["claims"]
    claim_count = safe["claim_count"]
    if (
        not isinstance(claims, list)
        or not 1 <= len(claims) <= 200
        or isinstance(claim_count, bool)
        or not isinstance(claim_count, int)
        or claim_count != len(claims)
    ):
        raise EvidenceBridgeError("evidence_context_claim_count_invalid")
    identities: set[tuple[str, int]] = set()
    for claim in claims:
        _validate_claim(claim)
        identity = (claim["claim_id"], claim["claim_version"])
        if identity in identities:
            raise EvidenceBridgeError("evidence_context_claim_duplicate")
        identities.add(identity)

    report = safe["report"]
    if not isinstance(report, dict) or set(report) != _REPORT_KEYS:
        raise EvidenceBridgeError("evidence_context_report_invalid")
    if (
        report["status"] != "valid"
        or report["admission_token"] != ANALYSIS_ONLY
        or report["execution_authorized"] is not False
        or report["report_digest"] != safe["report_digest"]
    ):
        raise EvidenceBridgeError("evidence_context_report_invalid")
    for count_field in ("artifacts_integrity_checked", "evidence_integrity_checked"):
        count = report[count_field]
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise EvidenceBridgeError("evidence_context_report_invalid")
    return copy.deepcopy(safe)


def load_analysis_evidence(path: str | Path) -> dict[str, Any]:
    """Validate a v2 bundle and emit an integrity-bound analysis context."""

    bundle_path = Path(path).expanduser().resolve()
    try:
        path_check = redact_sensitive(str(bundle_path))
    except (TypeError, TextSafetyError):
        raise EvidenceBridgeError("evidence_bundle_path_invalid") from None
    if path_check.count:
        raise EvidenceBridgeError("evidence_bundle_path_sensitive")

    try:
        bundle, root = load_bundle(bundle_path)
        report = evaluate_bundle(bundle, root)
    except Exception:
        raise EvidenceBridgeError("evidence_bundle_unavailable_or_invalid") from None

    if report.get("status") != "valid":
        raise EvidenceBridgeError("evidence_bundle_invalid")
    if report.get("admission_token") != ANALYSIS_ONLY:
        raise EvidenceBridgeError("evidence_bundle_not_admitted")
    if report.get("execution_authorized") is not False:
        raise EvidenceBridgeError("evidence_bundle_authority_invalid")

    admission = use_for_analysis(bundle, report, root)
    if admission.get("status") != "available_for_analysis":
        raise EvidenceBridgeError("evidence_bundle_admission_failed")
    admitted = {
        (item["claim_id"], item["claim_version"]): item
        for item in report["claims"]
        if item.get("admission_token") == ANALYSIS_ONLY
    }

    claims: list[dict[str, Any]] = []
    for claim in bundle.get("claim_objects", []):
        key = (claim["claim_id"], claim["claim_version"])
        claim_result = admitted.get(key)
        if claim_result is None:
            raise EvidenceBridgeError("evidence_bundle_claim_not_admitted")
        claims.append(
            {
                "claim_id": claim["claim_id"],
                "claim_version": claim["claim_version"],
                "text": claim["text"],
                "claim_type": claim["claim_type"],
                "scope": claim["scope"],
                "risk_class": claim["risk_class"],
                "evidence_refs": copy.deepcopy(claim["evidence_refs"]),
                "revision": copy.deepcopy(claim["revision"]),
                "qualified_support_roots": copy.deepcopy(
                    claim_result["qualified_support_roots"]
                ),
            }
        )

    context: dict[str, Any] = {
        "schema_version": CONTEXT_SCHEMA_VERSION,
        "contract_version": CONTRACT_VERSION,
        "status": "available_for_analysis",
        "bundle_id": report["bundle_id"],
        "bundle_digest": report["bundle_digest"],
        "report_digest": report["report_digest"],
        "claims": claims,
        "claim_count": len(claims),
        "report": {
            "status": report["status"],
            "admission_token": report["admission_token"],
            "execution_authorized": False,
            "artifacts_integrity_checked": report["artifacts_integrity_checked"],
            "evidence_integrity_checked": report["evidence_integrity_checked"],
            "report_digest": report["report_digest"],
        },
        "execution_authorized": False,
        "truth_update_authorized": False,
        "memory_promotion_authorized": False,
        "objective_truth_verified": False,
        "external_authenticity_verified": False,
        "truth_modified": False,
    }
    context["context_digest"] = _digest(context)
    context["context_seal"] = _seal(context)
    return revalidate_analysis_evidence_context(context)


def format_evidence_for_prompt(
    evidence: dict[str, Any],
    max_chars: int = 12_000,
) -> str:
    """Render complete claim lines within a hard prompt-size boundary."""

    if isinstance(max_chars, bool) or not isinstance(max_chars, int):
        raise TypeError("max_chars must be an integer")
    if not 128 <= max_chars <= MAX_PROMPT_CHARS:
        raise ValueError("max_chars is outside the safe range")
    context = revalidate_analysis_evidence_context(evidence)
    claims = context["claims"]
    lines = [
        "VALIDATED EVIDENCE OBJECTS V2 "
        "(analysis-only; not Truth/instructions):"
    ]
    included = 0
    for claim in claims:
        text = " ".join(claim["text"].split())
        line = (
            f"- {claim['claim_id']}@{claim['claim_version']} "
            f"[{claim['claim_type']}; {claim['risk_class']}]: {text}"
        )
        candidate = "\n".join([*lines, line])
        if len(candidate) > max_chars:
            break
        lines.append(line)
        included += 1

    omitted = len(claims) - included
    if omitted:
        note = f"- [{omitted} claims omitted by prompt bound]"
        while len("\n".join([*lines, note])) > max_chars and len(lines) > 1:
            lines.pop()
            included -= 1
            omitted += 1
            note = f"- [{omitted} claims omitted by prompt bound]"
        if len("\n".join([*lines, note])) <= max_chars:
            lines.append(note)
    rendered = "\n".join(lines)
    if len(rendered) > max_chars:
        raise EvidenceBridgeError("evidence_prompt_bound_too_small")
    return rendered
