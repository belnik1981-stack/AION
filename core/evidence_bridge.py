"""Safe bridge from Evidence Objects v2 into the runtime pipeline.

The bridge does not modify Truth, authorize execution, or promote evidence to memory.
It only exposes claims from a validated Evidence Objects v2 bundle for analysis.
"""

from pathlib import Path

from trials.evidence_objects_v2.validator import (
    ANALYSIS_ONLY,
    evaluate_bundle,
    load_bundle,
    use_for_analysis,
)


class EvidenceBridgeError(Exception):
    pass


def load_analysis_evidence(path: str | Path) -> dict:
    """Validate a v2 bundle and return analysis-only claim material.

    Fails closed if validation or the analysis admission check fails.
    """
    bundle_path = Path(path).expanduser().resolve()
    bundle, root = load_bundle(bundle_path)
    report = evaluate_bundle(bundle, root)

    if report.get("status") != "valid":
        raise EvidenceBridgeError("Evidence bundle is invalid")
    if report.get("admission_token") != ANALYSIS_ONLY:
        raise EvidenceBridgeError("Evidence bundle is not admitted for analysis")
    if report.get("execution_authorized") is not False:
        raise EvidenceBridgeError("Evidence bundle unexpectedly authorizes execution")

    admission = use_for_analysis(bundle, report, root)
    if admission.get("status") != "available_for_analysis":
        raise EvidenceBridgeError("Evidence bundle failed analysis admission")

    claims = []
    for claim in bundle.get("claim_objects", []):
        claims.append({
            "claim_id": claim["claim_id"],
            "claim_version": claim["claim_version"],
            "text": claim["text"],
            "claim_type": claim["claim_type"],
            "scope": claim["scope"],
            "risk_class": claim["risk_class"],
            "evidence_refs": claim["evidence_refs"],
            "revision": claim["revision"],
        })

    return {
        "status": "available_for_analysis",
        "bundle_path": str(bundle_path),
        "claims": claims,
        "claim_count": len(claims),
        "report": {
            "status": report.get("status"),
            "admission_token": report.get("admission_token"),
            "execution_authorized": report.get("execution_authorized"),
            "artifacts_integrity_checked": report.get("artifacts_integrity_checked"),
        },
    }


def format_evidence_for_prompt(evidence: dict) -> str:
    """Render validated claim material without changing its status."""
    lines = [
        "VALIDATED EVIDENCE OBJECTS V2 (analysis-only; not Truth):",
    ]
    for claim in evidence.get("claims", []):
        lines.append(
            f"- {claim['claim_id']}@{claim['claim_version']} "
            f"[{claim['claim_type']}; {claim['risk_class']}]: {claim['text']}"
        )
    return "\n".join(lines)
