"""Build fail-closed Evidence Objects v2 drafts from collected documents.

Collection proves only that AION obtained some bytes from a network location.
It does not prove authorship, independence, semantic support, or truth.  This
module therefore emits structurally valid bundles whose evidence is explicitly
``context`` with unknown quality.  The v2 gate must keep every resulting claim
at ``DENIED`` until a separate verifier replaces those declarations with
independently justified evidence.
"""

from __future__ import annotations

import hashlib
import ctypes
import errno
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from itertools import islice
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

from evidence.collector import EvidenceDocument
from security.redaction import TextSafetyError, redact_sensitive, redact_structure
from trials.evidence_objects_v2.validator import (
    CONTRACT_VERSION,
    DENIED,
    MAX_ARTIFACT_BYTES,
    evaluate_bundle,
)


MAX_CANDIDATE_DOCUMENTS = 10
MAX_CLAIM_CHARS = 2_000
MAX_URL_CHARS = 4_096
MAX_TITLE_CHARS = 1_000
MAX_METADATA_CHARS = 300
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_PROHIBITED_OUTPUT_PARTS = (
    ("knowledge", "truth"),
    ("memory",),
    ("audit",),
)


class EvidenceCandidateError(ValueError):
    """A collected document cannot be persisted as a safe candidate."""


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
        raise EvidenceCandidateError("candidate_not_canonical") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _timestamp(value: str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).strftime(_TIMESTAMP_FORMAT)
    if not isinstance(value, str):
        raise EvidenceCandidateError("candidate_timestamp_invalid")
    try:
        parsed = datetime.strptime(value, _TIMESTAMP_FORMAT)
    except ValueError:
        raise EvidenceCandidateError("candidate_timestamp_invalid") from None
    if parsed.strftime(_TIMESTAMP_FORMAT) != value:
        raise EvidenceCandidateError("candidate_timestamp_invalid")
    return value


def _secret_free(value: Any, error_code: str) -> None:
    try:
        _, redactions = redact_structure(value)
    except (TypeError, TextSafetyError):
        raise EvidenceCandidateError("candidate_input_out_of_bounds") from None
    if redactions:
        raise EvidenceCandidateError(error_code)


def _safe_origin_locator(url: str) -> str:
    if not isinstance(url, str) or not 1 <= len(url) <= MAX_URL_CHARS:
        raise EvidenceCandidateError("candidate_url_invalid")
    if any(ord(character) < 32 or ord(character) == 127 for character in url):
        raise EvidenceCandidateError("candidate_url_invalid")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        raise EvidenceCandidateError("candidate_url_invalid") from None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise EvidenceCandidateError("candidate_url_invalid")
    expected_port = 443 if parsed.scheme == "https" else 80
    if port is not None and port != expected_port:
        raise EvidenceCandidateError("candidate_url_invalid")

    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    netloc = host if port is None else f"{host}:{port}"
    path = parsed.path or "/"
    locator = urlunsplit((parsed.scheme, netloc, path, "", ""))
    if len(locator) > 500:
        raise EvidenceCandidateError("candidate_url_invalid")
    return locator


def _normalise_claim(claim: str) -> str:
    if not isinstance(claim, str):
        raise EvidenceCandidateError("candidate_claim_invalid")
    claim = claim.strip()
    if not 1 <= len(claim) <= MAX_CLAIM_CHARS:
        raise EvidenceCandidateError("candidate_claim_invalid")
    _secret_free(claim, "candidate_sensitive_input")
    return claim


def _normalise_documents(
    documents: Iterable[EvidenceDocument],
) -> list[tuple[str, bytes]]:
    if isinstance(documents, (str, bytes)):
        raise EvidenceCandidateError("candidate_documents_invalid")
    try:
        supplied = list(islice(iter(documents), MAX_CANDIDATE_DOCUMENTS + 1))
    except (TypeError, MemoryError):
        raise EvidenceCandidateError("candidate_documents_invalid") from None
    if not 1 <= len(supplied) <= MAX_CANDIDATE_DOCUMENTS:
        raise EvidenceCandidateError("candidate_document_count_invalid")

    unique: dict[tuple[str, str], tuple[str, bytes]] = {}
    for document in supplied:
        if not isinstance(document, EvidenceDocument):
            raise EvidenceCandidateError("candidate_document_invalid")
        fields = document.to_dict()
        _secret_free(fields, "candidate_sensitive_input")
        if (
            not isinstance(document.title, str)
            or len(document.title) > MAX_TITLE_CHARS
            or document.source_type != "web_document"
            or not isinstance(document.independent_group, str)
            or not 1 <= len(document.independent_group) <= MAX_METADATA_CHARS
            or not isinstance(document.fetched_via, str)
            or not 1 <= len(document.fetched_via) <= MAX_METADATA_CHARS
            or not isinstance(document.text, str)
        ):
            raise EvidenceCandidateError("candidate_document_invalid")

        locator = _safe_origin_locator(document.url)
        payload = document.text.encode("utf-8")
        if not 1 <= len(payload) <= MAX_ARTIFACT_BYTES:
            raise EvidenceCandidateError("candidate_document_size_invalid")
        content_sha256 = hashlib.sha256(payload).hexdigest()
        unique[(locator, content_sha256)] = (locator, payload)

    if not unique:
        raise EvidenceCandidateError("candidate_documents_invalid")
    return [unique[key] for key in sorted(unique)]


def build_collected_candidate_bundle(
    claim: str,
    documents: Iterable[EvidenceDocument],
    *,
    acquired_at: str | None = None,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Create a deterministic, non-admissible Evidence Objects v2 draft.

    The returned payload mapping is keyed by the relative paths declared in the
    bundle.  No filesystem or network access occurs here.
    """

    safe_claim = _normalise_claim(claim)
    timestamp = _timestamp(acquired_at)
    normalised = _normalise_documents(documents)
    identity = {
        "claim": safe_claim,
        "acquired_at": timestamp,
        "documents": [
            {
                "origin_locator": locator,
                "content_sha256": hashlib.sha256(payload).hexdigest(),
            }
            for locator, payload in normalised
        ],
    }
    identity_digest = _digest(identity)
    bundle_id = f"candidate-{identity_digest[:24]}"
    claim_id = f"candidate-claim-{identity_digest[:24]}"

    raw_artifacts: list[dict[str, Any]] = []
    evidence_objects: list[dict[str, Any]] = []
    evidence_refs: list[dict[str, Any]] = []
    payloads: dict[str, bytes] = {}

    for index, (locator, payload) in enumerate(normalised, start=1):
        content_sha256 = hashlib.sha256(payload).hexdigest()
        object_digest = hashlib.sha256(
            _canonical(
                {
                    "bundle_id": bundle_id,
                    "origin_locator": locator,
                    "content_sha256": content_sha256,
                    "ordinal": index,
                }
            )
        ).hexdigest()
        artifact_id = f"candidate-raw-{object_digest[:24]}"
        evidence_id = f"candidate-evidence-{object_digest[:24]}"
        payload_path = f"raw/{artifact_id}.txt"
        raw_artifacts.append(
            {
                "object_type": "raw_artifact",
                "schema_version": "2.0",
                "artifact_id": artifact_id,
                "artifact_version": 1,
                "media_type": "text/plain",
                "byte_length": len(payload),
                "content_sha256": content_sha256,
                "payload_path": payload_path,
                "privacy_class": "private",
                "access_policy": "restricted_analysis",
                "provenance": {
                    "origin_locator": locator,
                    "acquired_at": timestamp,
                    "observed_at": None,
                    "acquisition_method": "api_capture",
                    "derived_from": [],
                    "transformations": [],
                },
            }
        )
        evidence_objects.append(
            {
                "object_type": "evidence_object",
                "schema_version": "2.0",
                "evidence_id": evidence_id,
                "evidence_version": 1,
                "raw_artifact_ref": {
                    "artifact_id": artifact_id,
                    "artifact_version": 1,
                    "content_sha256": content_sha256,
                },
                "claim_ref": {"claim_id": claim_id, "claim_version": 1},
                "extraction": {
                    "method": "utf8_byte_span",
                    "method_version": "1.0",
                    "start_byte": 0,
                    "end_byte": len(payload),
                    "fragment_sha256": content_sha256,
                },
                "relation": "context",
                "declared_dependency_roots": [f"{artifact_id}@1"],
                "quality": {
                    "methodology": "hidden",
                    "primary_data": "unavailable",
                    "reproducibility": "unknown",
                },
            }
        )
        evidence_refs.append({"evidence_id": evidence_id, "evidence_version": 1})
        payloads[payload_path] = payload

    bundle = {
        "contract_version": CONTRACT_VERSION,
        "bundle_id": bundle_id,
        "evaluation_time": timestamp,
        "raw_artifacts": raw_artifacts,
        "evidence_objects": evidence_objects,
        "claim_objects": [
            {
                "object_type": "claim_object",
                "schema_version": "2.0",
                "claim_id": claim_id,
                "claim_version": 1,
                "text": safe_claim,
                "claim_type": "assumption",
                "scope": (
                    "Quarantined collection draft only; semantic relation, "
                    "source independence, authenticity and truth are unverified."
                ),
                "risk_class": "R2",
                "evidence_refs": evidence_refs,
                "evidence_policy": {"max_age_days": 0},
                "valid_for": ["analysis"],
                "prohibited_for": [
                    "execution",
                    "memory_promotion",
                    "truth_update",
                    "network_action",
                ],
                "revision": {
                    "previous_claim_ref": None,
                    "changed_at": timestamp,
                    "reason": None,
                },
            }
        ],
    }
    if not _SAFE_IDENTIFIER.fullmatch(bundle_id) or not _SAFE_IDENTIFIER.fullmatch(claim_id):
        raise EvidenceCandidateError("candidate_identifier_invalid")
    _canonical(bundle)
    return bundle, payloads


def _is_within(path: Path, directory: Path) -> bool:
    return path == directory or directory in path.parents


def _validate_destination(destination: str | Path) -> Path:
    if not isinstance(destination, (str, os.PathLike)):
        raise EvidenceCandidateError("candidate_destination_invalid")
    try:
        path_check = redact_sensitive(os.fspath(destination))
    except (TypeError, TextSafetyError):
        raise EvidenceCandidateError("candidate_destination_invalid") from None
    if path_check.count:
        raise EvidenceCandidateError("candidate_destination_sensitive")
    destination_path = Path(destination).expanduser().resolve(strict=False)
    if not destination_path.name or os.path.lexists(destination_path):
        raise EvidenceCandidateError("candidate_destination_exists")

    repository_root = Path(__file__).resolve().parents[1]
    for parts in _PROHIBITED_OUTPUT_PARTS:
        restricted = repository_root.joinpath(*parts).resolve()
        if _is_within(destination_path, restricted):
            raise EvidenceCandidateError("candidate_destination_forbidden")
    return destination_path


def _write_new_file(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _publish_directory_noreplace(staging: Path, target: Path) -> None:
    """Publish a directory without replacing an object at the destination."""

    # Linux and Android/Termux expose renameat2 with RENAME_NOREPLACE.  It gives
    # us one atomic operation with an enforced no-clobber guarantee.
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = libc.renameat2
    except (AttributeError, OSError):
        renameat2 = None
    if renameat2 is not None:
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        result = renameat2(
            -100,
            os.fsencode(staging),
            -100,
            os.fsencode(target),
            1,
        )
        if result == 0:
            return
        error_number = ctypes.get_errno()
        if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
            raise EvidenceCandidateError("candidate_destination_exists")
        if error_number not in {errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP}:
            raise EvidenceCandidateError("candidate_publish_failed")

    # Portable fail-closed fallback.  The exclusive mkdir reserves the name,
    # so no pre-existing file or directory is overwritten.  A crash can leave
    # an explicitly incomplete directory, which the next run will refuse to
    # replace and a validator will reject because bundle.json is moved last.
    try:
        target.mkdir(mode=0o700)
    except FileExistsError:
        raise EvidenceCandidateError("candidate_destination_exists") from None
    except OSError:
        raise EvidenceCandidateError("candidate_publish_failed") from None

    marker = target / ".incomplete"
    try:
        _write_new_file(marker, b"AION candidate publication incomplete\n")
        for name in ("raw", "validation-report.json", "bundle.json"):
            os.rename(staging / name, target / name)
        staging.rmdir()
        marker.unlink()
        _fsync_directory(target)
    except OSError:
        raise EvidenceCandidateError("candidate_publish_incomplete") from None


def write_collected_candidate_bundle(
    claim: str,
    documents: Iterable[EvidenceDocument],
    destination: str | Path,
    *,
    acquired_at: str | None = None,
) -> dict[str, Any]:
    """Validate and publish a quarantined bundle without overwriting output."""

    target = _validate_destination(destination)
    bundle, payloads = build_collected_candidate_bundle(
        claim,
        documents,
        acquired_at=acquired_at,
    )
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise EvidenceCandidateError("candidate_destination_unavailable") from None
    if os.path.lexists(target):
        raise EvidenceCandidateError("candidate_destination_exists")

    try:
        staging = Path(
            tempfile.mkdtemp(prefix=".aion-evidence-candidate-", dir=target.parent)
        )
        os.chmod(staging, 0o700)
    except OSError:
        raise EvidenceCandidateError("candidate_staging_failed") from None

    published = False
    try:
        raw_directory = staging / "raw"
        raw_directory.mkdir(mode=0o700)
        for relative_path, payload in sorted(payloads.items()):
            path = staging / relative_path
            if path.parent != raw_directory:
                raise EvidenceCandidateError("candidate_payload_path_invalid")
            _write_new_file(path, payload)
        _fsync_directory(raw_directory)

        bundle_payload = (
            json.dumps(
                bundle,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        _write_new_file(staging / "bundle.json", bundle_payload)

        report = evaluate_bundle(bundle, staging)
        claims = report.get("claims", []) if isinstance(report, dict) else []
        if (
            report.get("status") != "valid"
            or report.get("admission_token") != DENIED
            or report.get("execution_authorized") is not False
            or report.get("truth_modified") is not False
            or not claims
            or any(item.get("qualified_support_roots") for item in claims)
        ):
            raise EvidenceCandidateError("candidate_fail_closed_check_failed")
        report_payload = (
            json.dumps(
                report,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        _write_new_file(staging / "validation-report.json", report_payload)
        _fsync_directory(staging)

        # Recheck immediately before publication, then use an operating-system
        # no-replace primitive (or a fail-closed portable fallback).
        if os.path.lexists(target):
            raise EvidenceCandidateError("candidate_destination_exists")
        _publish_directory_noreplace(staging, target)
        published = True
        _fsync_directory(target.parent)
        return {
            "status": "quarantined_candidate",
            "destination": str(target),
            "bundle_id": bundle["bundle_id"],
            "bundle_digest": report["bundle_digest"],
            "report_digest": report["report_digest"],
            "admission_token": DENIED,
            "execution_authorized": False,
            "truth_modified": False,
        }
    except EvidenceCandidateError:
        raise
    except (OSError, TypeError, ValueError):
        raise EvidenceCandidateError("candidate_write_failed") from None
    finally:
        if not published and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)

