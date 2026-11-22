import json
import warnings
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import commercial_dependency.monitor as commercial_monitor
from commercial_dependency.layer import (
    CommercialFactors,
    assess_commercial_dependency,
    compare_parallel_outcomes,
)
from commercial_dependency.monitor import (
    CommercialDependencyMonitor,
    CommercialMonitorPolicy,
    CommercialMonitorStateError,
)
from storage.atomic_json import JsonRecoveryWarning


def main() -> None:
    # Useful motivation without strong distortion must not be treated as falsehood.
    useful = assess_commercial_dependency(
        CommercialFactors(
            financial_dependency=0.35,
            funding_opacity=0.10,
            ownership_concentration=0.20,
            conflict_of_interest=0.15,
            incentive_to_distort=0.10,
            positive_work_motivation=0.85,
            harmful_behavior_risk_if_used=0.10,
            harmful_behavior_risk_if_refused=0.55,
            reverse_incentive_risk=0.65,
            consequence_reversibility=0.90,
            evidence_quality=0.85,
        )
    )
    assert useful.keep_factual_data_separate is True
    assert useful.quarantine_level in {1, 2}
    assert useful.motivation_benefit >= 0.8

    # Strong conflict + incentive to distort should isolate influence.
    distorted = assess_commercial_dependency(
        CommercialFactors(
            financial_dependency=0.95,
            funding_opacity=0.80,
            ownership_concentration=0.85,
            conflict_of_interest=0.95,
            incentive_to_distort=0.90,
            positive_work_motivation=0.30,
            harmful_behavior_risk_if_used=0.75,
            harmful_behavior_risk_if_refused=0.15,
            reverse_incentive_risk=0.20,
            consequence_reversibility=0.30,
            evidence_quality=0.90,
        )
    )
    assert distorted.quarantine_level == 3
    assert distorted.influence_multiplier == 0.0
    assert distorted.auto_learning_allowed is False

    # If applying the commercial filter makes the real outcome worse, roll back.
    rollback = compare_parallel_outcomes(
        predicted_without_layer=0.70,
        predicted_with_layer=0.82,
        actual_without_layer=0.74,
        actual_with_layer=0.48,
        negative_consequence=0.65,
        consequence_reversibility=0.40,
        rollback_threshold=0.20,
    )
    assert rollback.rollback_required is True
    assert rollback.preferred_path == "without_commercial_adjustment"

    # If the layer improves the observed outcome without material harm, retain it.
    keep = compare_parallel_outcomes(
        predicted_without_layer=0.60,
        predicted_with_layer=0.72,
        actual_without_layer=0.58,
        actual_with_layer=0.77,
        negative_consequence=0.05,
        consequence_reversibility=0.95,
        rollback_threshold=0.20,
    )
    assert keep.rollback_required is False
    assert keep.preferred_path == "with_commercial_adjustment"

    # Mutable monitoring state must preserve updates made by controller
    # instances that were constructed from the same stale snapshot.
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        state_path = root / "commercial-state.json"
        audit_path = root / "commercial-audit.jsonl"
        stale_a = CommercialDependencyMonitor(state_path, audit_path)
        stale_b = CommercialDependencyMonitor(state_path, audit_path)
        stale_a.register_assessment("case-a", useful)
        stale_b.register_assessment("case-b", distorted)

        fresh = CommercialDependencyMonitor(state_path, audit_path)
        status = fresh.status()
        assert set(status["cases"]) == {"case-a", "case-b"}, status
        assert status["pending_audit_events"] == 0, status
        assert status["truth_modified"] is False

        # An identical immediate replay is idempotent and does not grow
        # history or duplicate the audit event.
        history_before = len(status["cases"]["case-a"]["history"])
        audit_before = len(audit_path.read_text(encoding="utf-8").splitlines())
        fresh.register_assessment("case-a", useful)
        replay_status = fresh.status()
        assert len(replay_status["cases"]["case-a"]["history"]) == history_before
        assert len(audit_path.read_text(encoding="utf-8").splitlines()) == audit_before

        fresh.record_comparison("case-a", keep)
        assert fresh.should_use_adjusted_path("case-a") is True

        audit_records = [
            json.loads(line)
            for line in audit_path.read_text(encoding="utf-8").splitlines()
        ]
        event_ids = [item["event_id"] for item in audit_records]
        assert len(event_ids) == len(set(event_ids))
        assert all(item["truth_modified"] is False for item in audit_records)

    # A crash after the atomic state commit but before JSONL append leaves a
    # recoverable pending event. Replaying recovery must not duplicate it.
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        state_path = root / "commercial-state.json"
        audit_path = root / "commercial-audit.jsonl"
        interrupted = CommercialDependencyMonitor(state_path, audit_path)
        with patch.object(
            commercial_monitor,
            "append_jsonl_record",
            side_effect=OSError("synthetic commercial audit interruption"),
        ):
            try:
                interrupted.register_assessment("recoverable-case", useful)
            except CommercialMonitorStateError:
                pass
            else:
                raise AssertionError("Interrupted audit append must surface")

        committed = json.loads(state_path.read_text(encoding="utf-8"))
        assert "recoverable-case" in committed["cases"]
        assert len(committed["pending_audit"]) == 1

        recovered = CommercialDependencyMonitor(state_path, audit_path)
        first_recovery = recovered.recover_pending_audit()
        second_recovery = recovered.recover_pending_audit()
        assert first_recovery == {"status": "ok", "recovered": 1, "pending": 0}
        assert second_recovery == {"status": "ok", "recovered": 0, "pending": 0}
        records = [
            json.loads(line)
            for line in audit_path.read_text(encoding="utf-8").splitlines()
        ]
        assert len(records) == 1

    # Secret-bearing identifiers and payload fields are rejected before any
    # state or audit persistence.
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        state_path = root / "commercial-state.json"
        audit_path = root / "commercial-audit.jsonl"
        monitor = CommercialDependencyMonitor(state_path, audit_path)
        secret = "sk-proj-" + "C" * 24
        for case_id, assessment in (
            (secret, useful),
            ("safe-case", replace(useful, reasons=[secret])),
            ("nan-case", replace(useful, distortion_risk=float("nan"))),
        ):
            try:
                monitor.register_assessment(case_id, assessment)
            except CommercialMonitorStateError:
                pass
            else:
                raise AssertionError("Sensitive commercial data was accepted")
        persisted = ""
        if state_path.exists():
            persisted += state_path.read_text(encoding="utf-8")
        if audit_path.exists():
            persisted += audit_path.read_text(encoding="utf-8")
        assert secret not in persisted

    # A damaged primary state recovers from the validated backup rather than
    # silently becoming an empty store. The next transaction repairs primary.
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        state_path = root / "commercial-state.json"
        audit_path = root / "commercial-audit.jsonl"
        monitor = CommercialDependencyMonitor(state_path, audit_path)
        monitor.register_assessment("case-a", useful)
        monitor.register_assessment("case-b", distorted)
        state_path.write_text("{damaged", encoding="utf-8")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", JsonRecoveryWarning)
            recovered = CommercialDependencyMonitor(state_path, audit_path)
            recovered.recover_pending_audit()
            recovered_status = recovered.status()
        assert set(recovered_status["cases"]) == {"case-a", "case-b"}
        assert list(root.glob("commercial-state.json.corrupt-*"))

    # Storage caps fail closed instead of dropping old evidence or allowing
    # unbounded history growth.
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        limited = CommercialDependencyMonitor(
            root / "commercial-state.json",
            root / "commercial-audit.jsonl",
            policy=CommercialMonitorPolicy(
                max_cases=1,
                max_history_per_case=1,
                max_pending_audit=4,
            ),
        )
        limited.register_assessment("only-case", useful)
        for action in (
            lambda: limited.register_assessment("second-case", useful),
            lambda: limited.record_comparison("only-case", keep),
        ):
            try:
                action()
            except CommercialMonitorStateError:
                pass
            else:
                raise AssertionError("Commercial monitor capacity did not fail closed")
        bounded = limited.status()
        assert set(bounded["cases"]) == {"only-case"}
        assert len(bounded["cases"]["only-case"]["history"]) == 1

    print("PASS: commercial dependency + incentive layer")


if __name__ == "__main__":
    main()
