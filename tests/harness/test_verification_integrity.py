import copy
import tempfile
from pathlib import Path

from verification.pipeline import EvidenceItem, VerificationPolicy, promote_verified_claim, verify_candidate_record


candidate = {"candidate_id": "candidate-test"}
policy = VerificationPolicy()
evidence = [
    EvidenceItem("src-a", "reference", "supports", 0.9, "group-a"),
    EvidenceItem("src-b", "reference", "supports", 0.8, "group-b"),
]
record = verify_candidate_record(candidate, "A verified test claim.", evidence, policy)
assert record["evaluation"]["decision"] == "verified"
assert record.get("verification_hash")

# A forged decision cannot compensate for insufficient evidence.
forged = copy.deepcopy(record)
forged["evidence"] = [
    {
        "source_id": "only-one",
        "source_type": "reference",
        "stance": "supports",
        "quality": 0.9,
        "independent_group": "one",
        "excerpt": "",
    }
]
forged["evaluation"]["decision"] = "verified"
try:
    promote_verified_claim(forged, reviewed_by="test-reviewer")
except ValueError as exc:
    assert "hash" in str(exc).lower() or "verification" in str(exc).lower()
else:
    raise AssertionError("forged verification record was promoted")

# Tampering with the claim must also invalidate integrity.
tampered = copy.deepcopy(record)
tampered["claim"] = "A different claim."
try:
    promote_verified_claim(tampered, reviewed_by="test-reviewer")
except ValueError:
    pass
else:
    raise AssertionError("tampered claim was promoted")

# Empty reviewer is rejected before promotion.
try:
    promote_verified_claim(record, reviewed_by="")
except ValueError:
    pass
else:
    raise AssertionError("promotion without reviewer was accepted")

print("VERIFICATION INTEGRITY TEST: PASS")
