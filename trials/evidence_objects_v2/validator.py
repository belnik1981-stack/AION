"""Deterministic, offline validator and evidence gate for AION trial v2.

The module validates structure, local payload integrity, provenance graph
consistency, exact artifact/evidence versions, dependency-root collapse and
claim admission. It never imports AION runtime, providers, memory, networking
libraries or an LLM SDK.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CONTRACT_VERSION = "aion-evidence-objects-v2"
ANALYSIS_ONLY = "ANALYSIS_ONLY"
DENIED = "DENIED"
MAX_BUNDLE_BYTES = 2 * 1024 * 1024
MAX_ARTIFACT_BYTES = 1024 * 1024
SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
RISK_MIN_QUALIFIED_ROOTS = {"R0": 1, "R1": 1, "R2": 2, "R3": 3}

_SENSITIVE_PATTERNS = (
    re.compile(r"\bsk-or-v1-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{16,}=*\b", re.IGNORECASE),
    re.compile(r"-----BEGIN\s+(?:RSA\s+|EC\s+|OPENSSH\s+)?PRIVATE KEY-----"),
)


class EvidenceValidationError(ValueError):
    """Raised when a bundle cannot be loaded safely."""


def _issue(code: str, path: str) -> dict[str, str]:
    return {"code": code, "path": path}


def _canonical(value: Any) -> bytes:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise EvidenceValidationError("value is not canonical JSON") from exc
    return text.encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _json_type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return type(value) is int
    if expected == "number":
        return (
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(float(value))
        )
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return False


def validate_schema(value: Any, schema: dict[str, Any], path: str = "$") -> list[dict[str, str]]:
    """Validate the strict JSON-Schema subset used by the v2 contracts."""
    errors: list[dict[str, str]] = []
    expected = schema.get("type")
    if expected is not None:
        accepted = expected if isinstance(expected, list) else [expected]
        if not any(_json_type_matches(value, item) for item in accepted):
            return [_issue("schema_type", path)]

    if "const" in schema and value != schema["const"]:
        errors.append(_issue("schema_const", path))
    if "enum" in schema and value not in schema["enum"]:
        errors.append(_issue("schema_enum", path))

    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(_issue("schema_min_length", path))
        maximum = schema.get("maxLength")
        if maximum is not None and len(value) > maximum:
            errors.append(_issue("schema_max_length", path))
        pattern = schema.get("pattern")
        if pattern is not None and re.search(pattern, value) is None:
            errors.append(_issue("schema_pattern", path))

    if type(value) is int or (
        not isinstance(value, bool) and isinstance(value, float) and math.isfinite(value)
    ):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and value < minimum:
            errors.append(_issue("schema_minimum", path))
        if maximum is not None and value > maximum:
            errors.append(_issue("schema_maximum", path))

    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(_issue("schema_min_items", path))
        maximum = schema.get("maxItems")
        if maximum is not None and len(value) > maximum:
            errors.append(_issue("schema_max_items", path))
        if schema.get("uniqueItems"):
            try:
                encoded = [_canonical(item) for item in value]
            except EvidenceValidationError:
                encoded = []
            if len(encoded) != len(set(encoded)):
                errors.append(_issue("schema_unique_items", path))
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                errors.extend(validate_schema(item, item_schema, f"{path}[{index}]"))

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                errors.append(_issue("schema_required", f"{path}.{name}"))
        if schema.get("additionalProperties") is False:
            for name in sorted(set(value) - set(properties)):
                errors.append(_issue("schema_additional_property", f"{path}.{name}"))
        for name, child_schema in properties.items():
            if name in value:
                errors.extend(validate_schema(value[name], child_schema, f"{path}.{name}"))

    return errors


def _load_schema(name: str) -> dict[str, Any]:
    path = SCHEMA_DIR / f"{name}.schema.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise EvidenceValidationError(f"schema is not an object: {name}")
    return data


SCHEMAS = {
    "bundle": _load_schema("trial_bundle"),
    "raw": _load_schema("raw_artifact"),
    "evidence": _load_schema("evidence_object"),
    "claim": _load_schema("claim_object"),
}


def load_bundle(path: str | Path) -> tuple[dict[str, Any], Path]:
    bundle_path = Path(path).expanduser().resolve()
    if not bundle_path.is_file():
        raise EvidenceValidationError("bundle file does not exist")
    if bundle_path.stat().st_size > MAX_BUNDLE_BYTES:
        raise EvidenceValidationError("bundle exceeds safe size")
    try:
        value = json.loads(bundle_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise EvidenceValidationError("bundle is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise EvidenceValidationError("bundle must be a JSON object")
    return value, bundle_path.parent


def _key(item: dict[str, Any], prefix: str) -> tuple[str, int]:
    return item[f"{prefix}_id"], item[f"{prefix}_version"]


def _ref_key(item: dict[str, Any], prefix: str) -> tuple[str, int]:
    return item[f"{prefix}_id"], item[f"{prefix}_version"]


def _safe_errors(errors: list[dict[str, str]]) -> list[dict[str, str]]:
    unique = {(item["code"], item["path"]) for item in errors}
    return [{"code": code, "path": path} for code, path in sorted(unique)]


def _invalid_report(bundle: Any, errors: list[dict[str, str]]) -> dict[str, Any]:
    safe_id = bundle.get("bundle_id") if isinstance(bundle, dict) else None
    report = {
        "contract_version": CONTRACT_VERSION,
        "bundle_id": safe_id if isinstance(safe_id, str) and len(safe_id) <= 128 else None,
        "status": "invalid",
        "admission_token": DENIED,
        "execution_authorized": False,
        "truth_modified": False,
        "errors": _safe_errors(errors),
        "claims": [],
    }
    report["report_digest"] = _digest(report)
    return report


def _contains_sensitive_value(data: bytes) -> bool:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return any(pattern.search(text) for pattern in _SENSITIVE_PATTERNS)


def _contains_sensitive_metadata(value: Any) -> bool:
    if isinstance(value, str):
        return any(pattern.search(value) for pattern in _SENSITIVE_PATTERNS)
    if isinstance(value, list):
        return any(_contains_sensitive_metadata(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_sensitive_metadata(item) for item in value.values())
    return False


def _parse_timestamp(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def evaluate_bundle(bundle: Any, base_dir: str | Path) -> dict[str, Any]:
    """Validate a bundle and issue ANALYSIS_ONLY or DENIED per claim."""
    base = Path(base_dir).expanduser().resolve()
    errors = validate_schema(bundle, SCHEMAS["bundle"])
    if isinstance(bundle, dict):
        raw_candidates = bundle.get("raw_artifacts")
        if isinstance(raw_candidates, list):
            for index, item in enumerate(raw_candidates):
                errors.extend(
                    validate_schema(item, SCHEMAS["raw"], f"$.raw_artifacts[{index}]")
                )
        evidence_candidates = bundle.get("evidence_objects")
        if isinstance(evidence_candidates, list):
            for index, item in enumerate(evidence_candidates):
                errors.extend(
                    validate_schema(
                        item,
                        SCHEMAS["evidence"],
                        f"$.evidence_objects[{index}]",
                    )
                )
        claim_candidates = bundle.get("claim_objects")
        if isinstance(claim_candidates, list):
            for index, item in enumerate(claim_candidates):
                errors.extend(
                    validate_schema(item, SCHEMAS["claim"], f"$.claim_objects[{index}]")
                )
    if errors:
        return _invalid_report(bundle, errors)
    if _contains_sensitive_metadata(bundle):
        return _invalid_report(bundle, [_issue("sensitive_metadata_detected", "$")])

    evaluation_time = _parse_timestamp(bundle["evaluation_time"])
    if evaluation_time is None:
        return _invalid_report(bundle, [_issue("invalid_timestamp", "$.evaluation_time")])

    raw_items = bundle["raw_artifacts"]
    evidence_items = bundle["evidence_objects"]
    claim_items = bundle["claim_objects"]
    raw_index: dict[tuple[str, int], dict[str, Any]] = {}
    evidence_index: dict[tuple[str, int], dict[str, Any]] = {}
    claim_index: dict[tuple[str, int], dict[str, Any]] = {}

    for item in raw_items:
        key = _key(item, "artifact")
        if key in raw_index:
            errors.append(_issue("duplicate_raw_artifact", f"raw:{key[0]}@{key[1]}"))
        raw_index[key] = item
    for item in evidence_items:
        key = _key(item, "evidence")
        if key in evidence_index:
            errors.append(_issue("duplicate_evidence_object", f"evidence:{key[0]}@{key[1]}"))
        evidence_index[key] = item
    for item in claim_items:
        key = _key(item, "claim")
        if key in claim_index:
            errors.append(_issue("duplicate_claim_object", f"claim:{key[0]}@{key[1]}"))
        claim_index[key] = item
    if errors:
        return _invalid_report(bundle, errors)

    raw_bytes: dict[tuple[str, int], bytes] = {}
    raw_acquired_at: dict[tuple[str, int], datetime | None] = {}
    raw_observed_at: dict[tuple[str, int], datetime | None] = {}
    for key, item in raw_index.items():
        unresolved = base / item["payload_path"]
        cursor = base
        symlink_found = False
        for component in Path(item["payload_path"]).parts:
            cursor = cursor / component
            if cursor.is_symlink():
                symlink_found = True
                break
        if symlink_found:
            errors.append(_issue("raw_artifact_symlink_forbidden", f"raw:{key[0]}@{key[1]}"))
            continue
        try:
            payload = unresolved.resolve(strict=True)
        except (OSError, RuntimeError):
            errors.append(_issue("raw_artifact_payload_not_found", f"raw:{key[0]}@{key[1]}"))
            continue
        if payload == base or base not in payload.parents or not payload.is_file():
            errors.append(_issue("raw_artifact_path_outside_bundle", f"raw:{key[0]}@{key[1]}"))
            continue
        try:
            data = payload.read_bytes()
        except OSError:
            errors.append(_issue("raw_artifact_payload_unreadable", f"raw:{key[0]}@{key[1]}"))
            continue
        if len(data) > MAX_ARTIFACT_BYTES:
            errors.append(_issue("raw_artifact_too_large", f"raw:{key[0]}@{key[1]}"))
            continue
        if len(data) != item["byte_length"]:
            errors.append(_issue("raw_artifact_length_mismatch", f"raw:{key[0]}@{key[1]}"))
        actual_hash = hashlib.sha256(data).hexdigest()
        if not hmac.compare_digest(actual_hash, item["content_sha256"]):
            errors.append(_issue("raw_artifact_hash_mismatch", f"raw:{key[0]}@{key[1]}"))
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            errors.append(_issue("raw_artifact_not_utf8", f"raw:{key[0]}@{key[1]}"))
        if _contains_sensitive_value(data):
            errors.append(_issue("sensitive_content_detected", f"raw:{key[0]}@{key[1]}"))
        raw_bytes[key] = data

        provenance = item["provenance"]
        acquired_at = _parse_timestamp(provenance["acquired_at"])
        observed_value = provenance["observed_at"]
        observed_at = None if observed_value is None else _parse_timestamp(observed_value)
        raw_acquired_at[key] = acquired_at
        raw_observed_at[key] = observed_at
        if acquired_at is None or (observed_value is not None and observed_at is None):
            errors.append(_issue("invalid_timestamp", f"raw:{key[0]}@{key[1]}"))
            continue
        if acquired_at > evaluation_time or (
            observed_at is not None and observed_at > evaluation_time
        ):
            errors.append(_issue("timestamp_after_evaluation", f"raw:{key[0]}@{key[1]}"))
        if observed_at is not None and observed_at > acquired_at:
            errors.append(_issue("observed_after_acquired", f"raw:{key[0]}@{key[1]}"))

    parent_map: dict[tuple[str, int], list[tuple[str, int]]] = {}
    for key, item in raw_index.items():
        provenance = item["provenance"]
        parents = [_ref_key(ref, "artifact") for ref in provenance["derived_from"]]
        parent_map[key] = parents
        for parent in parents:
            if parent not in raw_index:
                errors.append(_issue("derived_artifact_ref_not_found", f"raw:{key[0]}@{key[1]}"))
                continue
            child_acquired_at = raw_acquired_at[key]
            parent_acquired_at = raw_acquired_at[parent]
            if (
                child_acquired_at is not None
                and parent_acquired_at is not None
                and child_acquired_at < parent_acquired_at
            ):
                errors.append(
                    _issue(
                        "derived_artifact_acquired_before_parent",
                        f"raw:{key[0]}@{key[1]}",
                    )
                )

        transformations = provenance["transformations"]
        if parents and len(transformations) != 1:
            errors.append(
                _issue("derived_artifact_transformation_required", f"raw:{key[0]}@{key[1]}")
            )
        if not parents and transformations:
            errors.append(
                _issue("primary_artifact_has_transformation", f"raw:{key[0]}@{key[1]}")
            )
        if parents and len(transformations) == 1:
            transformation = transformations[0]
            inputs = [_ref_key(ref, "artifact") for ref in transformation["input_artifact_refs"]]
            if sorted(inputs) != sorted(parents):
                errors.append(
                    _issue("transformation_inputs_mismatch", f"raw:{key[0]}@{key[1]}")
                )
            if not hmac.compare_digest(
                transformation["output_sha256"], item["content_sha256"]
            ):
                errors.append(
                    _issue("transformation_output_hash_mismatch", f"raw:{key[0]}@{key[1]}")
                )

    root_cache: dict[tuple[str, int], set[tuple[str, int]]] = {}
    visiting: set[tuple[str, int]] = set()

    def roots_for(key: tuple[str, int]) -> set[tuple[str, int]]:
        if key in root_cache:
            return root_cache[key]
        if key in visiting:
            errors.append(_issue("provenance_cycle", f"raw:{key[0]}@{key[1]}"))
            return set()
        visiting.add(key)
        parents = parent_map.get(key, [])
        roots = {key} if not parents else set()
        for parent in parents:
            if parent in raw_index:
                roots.update(roots_for(parent))
        visiting.remove(key)
        root_cache[key] = roots
        return roots

    for key in raw_index:
        roots_for(key)
    if errors:
        return _invalid_report(bundle, errors)

    primary_roots = sorted(key for key, parents in parent_map.items() if not parents)
    alias_parent = {key: key for key in primary_roots}

    def find_alias(key: tuple[str, int]) -> tuple[str, int]:
        parent = alias_parent[key]
        if parent != key:
            alias_parent[key] = find_alias(parent)
        return alias_parent[key]

    def union_aliases(left: tuple[str, int], right: tuple[str, int]) -> None:
        left_root = find_alias(left)
        right_root = find_alias(right)
        if left_root == right_root:
            return
        canonical, alias = sorted((left_root, right_root))
        alias_parent[alias] = canonical

    seen_identity: dict[tuple[str, str], tuple[str, int]] = {}
    for key in primary_roots:
        item = raw_index[key]
        identities = (
            ("artifact_id", item["artifact_id"]),
            ("content_sha256", item["content_sha256"]),
            ("origin_locator", item["provenance"]["origin_locator"]),
        )
        for identity in identities:
            previous = seen_identity.get(identity)
            if previous is None:
                seen_identity[identity] = key
            else:
                union_aliases(previous, key)

    canonical_root = {key: find_alias(key) for key in primary_roots}

    evidence_roots: dict[tuple[str, int], set[tuple[str, int]]] = {}
    for key, item in evidence_index.items():
        raw_ref = item["raw_artifact_ref"]
        raw_key = _ref_key(raw_ref, "artifact")
        claim_key = _ref_key(item["claim_ref"], "claim")
        if raw_key not in raw_index:
            errors.append(_issue("raw_artifact_ref_not_found", f"evidence:{key[0]}@{key[1]}"))
            continue
        if claim_key not in claim_index:
            errors.append(_issue("claim_ref_not_found", f"evidence:{key[0]}@{key[1]}"))
        raw_item = raw_index[raw_key]
        if not hmac.compare_digest(raw_ref["content_sha256"], raw_item["content_sha256"]):
            errors.append(_issue("raw_artifact_ref_hash_mismatch", f"evidence:{key[0]}@{key[1]}"))

        data = raw_bytes.get(raw_key)
        if data is None:
            continue
        extraction = item["extraction"]
        start, end = extraction["start_byte"], extraction["end_byte"]
        if not (0 <= start < end <= len(data)):
            errors.append(_issue("invalid_extraction_span", f"evidence:{key[0]}@{key[1]}"))
            continue
        fragment = data[start:end]
        try:
            fragment.decode("utf-8")
        except UnicodeDecodeError:
            errors.append(_issue("evidence_fragment_not_utf8", f"evidence:{key[0]}@{key[1]}"))
        fragment_hash = hashlib.sha256(fragment).hexdigest()
        if not hmac.compare_digest(fragment_hash, extraction["fragment_sha256"]):
            errors.append(_issue("evidence_fragment_hash_mismatch", f"evidence:{key[0]}@{key[1]}"))

        roots = root_cache[raw_key]
        evidence_roots[key] = roots
        expected = sorted(f"{root[0]}@{root[1]}" for root in roots)
        if item["declared_dependency_roots"] != expected:
            errors.append(
                _issue("declared_dependency_roots_mismatch", f"evidence:{key[0]}@{key[1]}")
            )

    for key, item in claim_index.items():
        changed_at = _parse_timestamp(item["revision"]["changed_at"])
        if changed_at is None:
            errors.append(_issue("invalid_timestamp", f"claim:{key[0]}@{key[1]}"))
        elif changed_at > evaluation_time:
            errors.append(_issue("timestamp_after_evaluation", f"claim:{key[0]}@{key[1]}"))
        previous = item["revision"]["previous_claim_ref"]
        if key[1] == 1 and previous is not None:
            errors.append(_issue("claim_revision_parent_forbidden", f"claim:{key[0]}@{key[1]}"))
        if key[1] > 1:
            if previous is None:
                errors.append(_issue("claim_revision_parent_required", f"claim:{key[0]}@{key[1]}"))
            else:
                previous_id, version_text = previous.rsplit("@", 1)
                previous_key = (previous_id, int(version_text))
                if (
                    previous_key not in claim_index
                    or previous_id != key[0]
                    or previous_key[1] != key[1] - 1
                ):
                    errors.append(_issue("claim_revision_parent_invalid", f"claim:{key[0]}@{key[1]}"))
                elif changed_at is not None:
                    previous_changed_at = _parse_timestamp(
                        claim_index[previous_key]["revision"]["changed_at"]
                    )
                    if (
                        previous_changed_at is not None
                        and changed_at <= previous_changed_at
                    ):
                        errors.append(
                            _issue(
                                "claim_revision_time_not_after_parent",
                                f"claim:{key[0]}@{key[1]}",
                            )
                        )
                if not item["revision"]["reason"]:
                    errors.append(_issue("claim_revision_reason_required", f"claim:{key[0]}@{key[1]}"))
        for ref in item["evidence_refs"]:
            evidence_key = _ref_key(ref, "evidence")
            if evidence_key not in evidence_index:
                errors.append(_issue("evidence_ref_not_found", f"claim:{key[0]}@{key[1]}"))
                continue
            linked_claim = _ref_key(evidence_index[evidence_key]["claim_ref"], "claim")
            if linked_claim != key:
                errors.append(_issue("evidence_claim_backref_mismatch", f"claim:{key[0]}@{key[1]}"))
    if errors:
        return _invalid_report(bundle, errors)

    claim_results: list[dict[str, Any]] = []
    for key in sorted(claim_index):
        item = claim_index[key]
        support_roots: set[tuple[str, int]] = set()
        contradiction_roots: set[tuple[str, int]] = set()
        stale_or_unknown_roots: set[tuple[str, int]] = set()
        max_age_seconds = item["evidence_policy"]["max_age_days"] * 24 * 60 * 60
        for ref in item["evidence_refs"]:
            evidence_key = _ref_key(ref, "evidence")
            evidence = evidence_index[evidence_key]
            roots = evidence_roots[evidence_key]
            quality = evidence["quality"]
            quality_sufficient = (
                quality["methodology"] == "described"
                and quality["primary_data"] == "available"
                and quality["reproducibility"] == "reproduced"
            )
            raw_key = _ref_key(evidence["raw_artifact_ref"], "artifact")
            observed_at = raw_observed_at[raw_key]
            carrier_fresh = (
                observed_at is not None
                and 0 <= (evaluation_time - observed_at).total_seconds() <= max_age_seconds
            )
            if evidence["relation"] == "supports" and quality_sufficient:
                for root in roots:
                    root_observed_at = raw_observed_at[root]
                    root_fresh = (
                        root_observed_at is not None
                        and 0
                        <= (evaluation_time - root_observed_at).total_seconds()
                        <= max_age_seconds
                    )
                    root_group = canonical_root[root]
                    if carrier_fresh and root_fresh:
                        support_roots.add(root_group)
                    else:
                        stale_or_unknown_roots.add(root_group)
            if evidence["relation"] == "contradicts":
                contradiction_roots.update(canonical_root[root] for root in roots)

        required = RISK_MIN_QUALIFIED_ROOTS[item["risk_class"]]
        reasons: list[str] = []
        if len(support_roots) < required:
            reasons.append("insufficient_qualified_dependency_roots")
            if stale_or_unknown_roots:
                reasons.append("stale_or_unknown_evidence")
        if contradiction_roots:
            reasons.append("material_contradiction_present")
        admitted = not reasons
        claim_results.append(
            {
                "claim_id": key[0],
                "claim_version": key[1],
                "risk_class": item["risk_class"],
                "decision": "admitted_for_analysis" if admitted else "denied",
                "admission_token": ANALYSIS_ONLY if admitted else DENIED,
                "qualified_support_roots": sorted(
                    f"{root[0]}@{root[1]}" for root in support_roots
                ),
                "required_qualified_roots": required,
                "contradiction_roots": sorted(
                    f"{root[0]}@{root[1]}" for root in contradiction_roots
                ),
                "reasons": reasons,
                "valid_for": ["analysis"] if admitted else [],
                "execution_authorized": False,
            }
        )

    overall_token = (
        ANALYSIS_ONLY
        if claim_results and all(item["admission_token"] == ANALYSIS_ONLY for item in claim_results)
        else DENIED
    )
    report = {
        "contract_version": CONTRACT_VERSION,
        "bundle_id": bundle["bundle_id"],
        "bundle_digest": _digest(bundle),
        "status": "valid",
        "admission_token": overall_token,
        "execution_authorized": False,
        "truth_modified": False,
        "artifacts_integrity_checked": len(raw_index),
        "evidence_integrity_checked": len(evidence_index),
        "errors": [],
        "claims": claim_results,
    }
    report["report_digest"] = _digest(report)
    return report


def use_for_analysis(bundle: Any, report: Any, base_dir: str | Path) -> dict[str, Any]:
    denied = {
        "status": "denied",
        "reason": "evidence_contract_not_satisfied",
        "execution_authorized": False,
    }
    if not isinstance(report, dict):
        return denied
    recomputed = evaluate_bundle(bundle, base_dir)
    if recomputed["status"] != "valid" or recomputed["admission_token"] != ANALYSIS_ONLY:
        return denied
    supplied_digest = report.get("report_digest")
    if not isinstance(supplied_digest, str):
        return denied
    if not hmac.compare_digest(supplied_digest, recomputed["report_digest"]):
        return denied
    if report != recomputed:
        return denied
    return {
        "status": "available_for_analysis",
        "claims": [
            {
                "claim_id": item["claim_id"],
                "claim_version": item["claim_version"],
                "qualified_support_roots": item["qualified_support_roots"],
            }
            for item in recomputed["claims"]
            if item["admission_token"] == ANALYSIS_ONLY
        ],
        "execution_authorized": False,
    }


def write_report(report: dict[str, Any], output_path: str | Path) -> Path:
    path = Path(output_path).expanduser().resolve()
    truth_dir = (Path(__file__).resolve().parents[2] / "knowledge" / "truth").resolve()
    if path == truth_dir or truth_dir in path.parents:
        raise EvidenceValidationError("trial output cannot be written into Truth")
    if path.suffix.lower() != ".json":
        raise EvidenceValidationError("trial output must use a .json file")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    temporary.replace(path)
    return path
