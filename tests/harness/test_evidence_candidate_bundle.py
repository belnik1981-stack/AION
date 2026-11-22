"""Collected web documents become quarantined Evidence Objects drafts only."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from core.evidence_bridge import EvidenceBridgeError, load_analysis_evidence
from evidence.candidate_bundle import (
    EvidenceCandidateError,
    build_collected_candidate_bundle,
    write_collected_candidate_bundle,
)
from evidence.collector import EvidenceDocument
from trials.evidence_objects_v2.validator import DENIED, evaluate_bundle


ACQUIRED_AT = "2026-10-20T00:00:00Z"
CLAIM = "The collected documents may contain information relevant to this claim."
DOCUMENTS = [
    EvidenceDocument(
        url="https://source-a.example/report?tracking=public-value",
        title="Source A",
        text="Source A provides a statement that still requires independent review.",
        source_type="web_document",
        independent_group="unverified:domain:source-a.example",
        fetched_via="direct_url",
    ),
    EvidenceDocument(
        url="https://source-b.example/report",
        title="Source B",
        text="Source B provides separate context, not automatic proof of the claim.",
        source_type="web_document",
        independent_group="unverified:domain:source-b.example",
        fetched_via="direct_url",
    ),
]


def expect_rejected(action) -> None:
    try:
        action()
    except EvidenceCandidateError:
        return
    raise AssertionError("Unsafe candidate bundle input was accepted")


# Pure construction is deterministic for a fixed acquisition time and does
# not depend on collector result order.
first_bundle, first_payloads = build_collected_candidate_bundle(
    CLAIM,
    DOCUMENTS,
    acquired_at=ACQUIRED_AT,
)
second_bundle, second_payloads = build_collected_candidate_bundle(
    CLAIM,
    list(reversed(DOCUMENTS)),
    acquired_at=ACQUIRED_AT,
)
assert first_bundle == second_bundle
assert first_payloads == second_payloads
assert len(first_bundle["raw_artifacts"]) == 2
assert all(item["privacy_class"] == "private" for item in first_bundle["raw_artifacts"])
assert all(
    item["access_policy"] == "restricted_analysis"
    for item in first_bundle["raw_artifacts"]
)
assert all(
    "?" not in item["provenance"]["origin_locator"]
    for item in first_bundle["raw_artifacts"]
)
assert "tracking=public-value" not in json.dumps(first_bundle, ensure_ascii=False)
assert all(item["relation"] == "context" for item in first_bundle["evidence_objects"])
assert all(
    item["quality"]
    == {
        "methodology": "hidden",
        "primary_data": "unavailable",
        "reproducibility": "unknown",
    }
    for item in first_bundle["evidence_objects"]
)

with TemporaryDirectory() as temp_dir:
    root = Path(temp_dir)
    destination = root / "candidate"
    result = write_collected_candidate_bundle(
        CLAIM,
        DOCUMENTS,
        destination,
        acquired_at=ACQUIRED_AT,
    )
    assert result["status"] == "quarantined_candidate"
    assert result["admission_token"] == DENIED
    assert result["execution_authorized"] is False
    assert result["truth_modified"] is False
    assert destination.is_dir()

    bundle_path = destination / "bundle.json"
    assert (destination / "validation-report.json").is_file()
    saved = json.loads(bundle_path.read_text(encoding="utf-8"))
    report = evaluate_bundle(saved, destination)
    assert report["status"] == "valid", report
    assert report["admission_token"] == DENIED, report
    assert report["execution_authorized"] is False
    assert report["claims"][0]["qualified_support_roots"] == []
    assert "insufficient_qualified_dependency_roots" in report["claims"][0]["reasons"]

    # The normal runtime bridge must reject this draft, so it cannot enter the
    # claim registry under a validated analysis-only label.
    try:
        load_analysis_evidence(bundle_path)
    except EvidenceBridgeError:
        pass
    else:
        raise AssertionError("Quarantined candidate entered the runtime bridge")

    # Existing output is never overwritten.
    sentinel = destination / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")
    expect_rejected(
        lambda: write_collected_candidate_bundle(
            CLAIM,
            DOCUMENTS,
            destination,
            acquired_at=ACQUIRED_AT,
        )
    )
    assert sentinel.read_text(encoding="utf-8") == "keep"


# Candidate material must never be mixed into authoritative or mutable stores.
repository_root = Path(__file__).resolve().parents[2]
for protected in (
    repository_root / "knowledge" / "truth" / "candidate-test-do-not-write",
    repository_root / "memory" / "candidate-test-do-not-write",
    repository_root / "audit" / "candidate-test-do-not-write",
):
    expect_rejected(
        lambda protected=protected: write_collected_candidate_bundle(
            CLAIM,
            DOCUMENTS,
            protected,
            acquired_at=ACQUIRED_AT,
        )
    )
    assert not protected.exists()


# Iterables are consumed only to the hard limit plus one and fail closed.
expect_rejected(
    lambda: build_collected_candidate_bundle(
        CLAIM,
        (DOCUMENTS[0] for _ in range(11)),
        acquired_at=ACQUIRED_AT,
    )
)


# Sensitive material is rejected before output creation, including callers
# that bypass EvidenceCollector and construct EvidenceDocument directly.
secret = "sk-proj-" + "D" * 24
with TemporaryDirectory() as temp_dir:
    root = Path(temp_dir)
    secret_document = EvidenceDocument(
        url="https://source.example/report",
        title="Secret",
        text=f"unsafe {secret}",
        source_type="web_document",
        independent_group="unverified:domain:source.example",
        fetched_via="direct_url",
    )
    expect_rejected(
        lambda: write_collected_candidate_bundle(
            f"claim {secret}",
            DOCUMENTS,
            root / "secret-claim",
            acquired_at=ACQUIRED_AT,
        )
    )
    expect_rejected(
        lambda: write_collected_candidate_bundle(
            CLAIM,
            [secret_document],
            root / "secret-document",
            acquired_at=ACQUIRED_AT,
        )
    )
    assert list(root.iterdir()) == []


print("QUARANTINED EVIDENCE CANDIDATE BUNDLE: PASS")
