"""Parallel, non-authoritative commercial-dependency view for AION claims."""

from __future__ import annotations

from dataclasses import fields
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from commercial_dependency.layer import CommercialFactors, assess_commercial_dependency


MAX_CONFIG_BYTES = 64 * 1024
MAX_TARGETS = 4
_FACTOR_NAMES = {field.name for field in fields(CommercialFactors)}


class CommercialBridgeError(ValueError):
    """Commercial factor configuration is invalid or outside safe bounds."""


def _canonical_digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_config(path: str | Path, allowed_targets: set[str]) -> dict[str, Any]:
    target = Path(path).expanduser()
    if target.is_symlink():
        raise CommercialBridgeError("commercial_config_symlink_blocked")
    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise CommercialBridgeError("commercial_config_unavailable") from exc
    if len(raw) > MAX_CONFIG_BYTES:
        raise CommercialBridgeError("commercial_config_too_large")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CommercialBridgeError("commercial_config_invalid_json") from exc
    if not isinstance(payload, dict) or set(payload) - {"version", "targets"}:
        raise CommercialBridgeError("commercial_config_invalid_root")
    if payload.get("version") != 1 or not isinstance(payload.get("targets"), dict):
        raise CommercialBridgeError("commercial_config_invalid_schema")
    targets = payload["targets"]
    if not 1 <= len(targets) <= MAX_TARGETS:
        raise CommercialBridgeError("commercial_config_invalid_target_count")
    if set(targets) - allowed_targets:
        raise CommercialBridgeError("commercial_config_foreign_target")

    normalised: dict[str, Any] = {}
    for target_id, specification in targets.items():
        if not isinstance(specification, dict) or set(specification) - {"factors", "basis"}:
            raise CommercialBridgeError("commercial_target_invalid_schema")
        factors = specification.get("factors")
        if not isinstance(factors, dict) or set(factors) - _FACTOR_NAMES:
            raise CommercialBridgeError("commercial_factors_invalid_schema")
        values = {}
        for name in _FACTOR_NAMES:
            value = factors.get(name, getattr(CommercialFactors(), name))
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise CommercialBridgeError("commercial_factor_not_numeric")
            number = float(value)
            if not 0.0 <= number <= 1.0:
                raise CommercialBridgeError("commercial_factor_out_of_range")
            values[name] = number
        basis = specification.get("basis", [])
        if (not isinstance(basis, list) or len(basis) > 8
                or any(not isinstance(item, str) or not item.strip() or len(item) > 300 for item in basis)):
            raise CommercialBridgeError("commercial_basis_invalid")
        normalised[target_id] = {
            "factors": values,
            "basis_count": len(basis),
            "basis_digest": _canonical_digest(basis),
        }
    return {"version": 1, "targets": normalised}


def parallel_commercial_view(
    claim_registry: dict[str, Any],
    model_ids: list[str],
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    """Compare claim influence with and without a non-authoritative risk layer."""

    path = str(config_path or os.getenv("AION_COMMERCIAL_FACTORS_FILE", "")).strip()
    base_digest = _canonical_digest(claim_registry)
    if not path:
        return {
            "enabled": False,
            "status": "not_configured",
            "trusted_pipeline_modified": False,
            "commercial_causality_verified": False,
            "baseline_registry_digest": base_digest,
        }
    try:
        config = _load_config(path, set(model_ids))
    except CommercialBridgeError as exc:
        return {
            "enabled": True,
            "status": "rejected",
            "reason": str(exc),
            "trusted_pipeline_modified": False,
            "commercial_causality_verified": False,
            "baseline_registry_digest": base_digest,
        }

    assessments: dict[str, Any] = {}
    for target_id, specification in config["targets"].items():
        assessment = assess_commercial_dependency(
            CommercialFactors(**specification["factors"])
        ).to_dict()
        # User-supplied factor scores may inform a parallel analysis, but they
        # do not authorize learning or prove a causal commercial dependency.
        assessment["auto_learning_applied"] = False
        assessment["commercial_causality_verified"] = False
        assessment["input_status"] = "user_supplied_unverified"
        assessment["basis_count"] = specification["basis_count"]
        assessment["basis_digest"] = specification["basis_digest"]
        assessments[target_id] = assessment

    comparison = []
    for observation in claim_registry.get("observations", []):
        model_id = observation.get("model_id")
        quarantine = observation.get("quarantine", {})
        baseline = float(quarantine.get("influence_multiplier", 0.0))
        assessment = assessments.get(model_id)
        multiplier = float(assessment["influence_multiplier"]) if assessment else 1.0
        adjusted = round(baseline * multiplier, 4)
        comparison.append({
            "claim_id": observation.get("claim_id"),
            "model_id": model_id,
            "without_commercial_layer": round(baseline, 4),
            "with_commercial_layer": adjusted,
            "delta": round(adjusted - baseline, 4),
            "base_claim_status_unchanged": True,
        })

    return {
        "enabled": True,
        "status": "parallel_analysis_only",
        "input_status": "user_supplied_unverified",
        "assessments": assessments,
        "influence_comparison": comparison,
        "changed_claims": sum(1 for item in comparison if item["delta"] != 0),
        "trusted_pipeline_modified": False,
        "decision_authority": "none",
        "commercial_causality_verified": False,
        "execution_authorized": False,
        "truth_modified": False,
        "baseline_registry_digest": base_digest,
        "note": "Commercial risk is a parallel hypothesis layer, never proof of falsehood.",
    }
