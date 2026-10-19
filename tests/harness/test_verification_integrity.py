import copy
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from memory import store
from verification import pipeline as verification_pipeline
from verification.pipeline import (
    EvidenceItem,
    VerificationPolicy,
    promote_verified_claim,
    recover_pending_promotions,
    verify_candidate_record,
)


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


# Successful promotion is a recoverable sequence: prepared audit -> staged
# memory -> committed audit -> visible long-term lesson.
with tempfile.TemporaryDirectory() as temp_dir:
    root = Path(temp_dir)
    knowledge = root / "knowledge.json"
    audit_file = root / "verification.jsonl"
    journal_file = root / "promotion-transactions.json"
    with patch.object(store, "LONG_TERM_FILE", knowledge):
        promoted = promote_verified_claim(
            record,
            reviewed_by="test-reviewer",
            audit_file=audit_file,
            journal_file=journal_file,
        )
        assert promoted["event"] == "promote_to_long_term", promoted
        assert store.get_long_term_knowledge() == "- A verified test claim."
        journal = json.loads(journal_file.read_text(encoding="utf-8"))
        transaction = journal["transactions"][promoted["promotion_id"]]
        assert transaction["state"] == "committed", transaction
        audit_records = [json.loads(line) for line in audit_file.read_text(encoding="utf-8").splitlines()]
        assert [item["event"] for item in audit_records] == [
            "promotion_prepared", "promote_to_long_term"
        ], audit_records

        # Repeating the same confirmed transaction is idempotent.
        repeated = promote_verified_claim(
            record,
            reviewed_by="test-reviewer",
            audit_file=audit_file,
            journal_file=journal_file,
        )
        assert repeated["promotion_id"] == promoted["promotion_id"]
        assert len(audit_file.read_text(encoding="utf-8").splitlines()) == 2


# Inject failure exactly when the committed audit should be appended. The
# claim remains pending and invisible; recovery resumes idempotently.
with tempfile.TemporaryDirectory() as temp_dir:
    root = Path(temp_dir)
    knowledge = root / "knowledge.json"
    audit_file = root / "verification.jsonl"
    journal_file = root / "promotion-transactions.json"
    real_append = verification_pipeline.append_audit_record

    def fail_committed_audit(audit_record, destination):
        if audit_record.get("event") == "promote_to_long_term":
            raise OSError("synthetic audit interruption")
        return real_append(audit_record, destination)

    with patch.object(store, "LONG_TERM_FILE", knowledge), patch.object(
        verification_pipeline, "append_audit_record", side_effect=fail_committed_audit
    ):
        try:
            promote_verified_claim(
                record,
                reviewed_by="recovery-reviewer",
                audit_file=audit_file,
                journal_file=journal_file,
            )
        except OSError:
            pass
        else:
            raise AssertionError("Injected audit interruption must surface")
        assert store.get_long_term_knowledge() == "Уроки отсутствуют."
        pending = json.loads(knowledge.read_text(encoding="utf-8"))["pending_promotions"]
        assert len(pending) == 1, pending

    with patch.object(store, "LONG_TERM_FILE", knowledge):
        recovery = recover_pending_promotions(
            audit_file=audit_file,
            journal_file=journal_file,
        )
        assert recovery["recovered"] == 1, recovery
        assert store.get_long_term_knowledge() == "- A verified test claim."
        final_journal = json.loads(journal_file.read_text(encoding="utf-8"))
        assert next(iter(final_journal["transactions"].values()))["state"] == "committed"

print("VERIFICATION INTEGRITY TEST: PASS")
