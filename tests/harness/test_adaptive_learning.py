import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from learning import controller as learning_controller
from learning.controller import AdaptiveLearningController, LearningPolicy, LearningStateError
from verification.pipeline import EvidenceItem, VerificationPolicy, verify_candidate_record


def verified_record(
    candidate_id: str,
    *,
    claim: str,
    identity: str = "model-a",
    source_type: str = "model_output",
    stance: str = "supports",
    external: bool = True,
    secret_excerpt: str = "",
):
    target_quality = 0.7 if stance == "supports" else 0.2
    evidence = [
        EvidenceItem(
            identity,
            source_type,
            stance,
            target_quality,
            f"unverified:{source_type}:{identity}",
            secret_excerpt,
        )
    ]
    if external:
        evidence.extend([
            EvidenceItem("source-a", "controlled_fixture", "supports", 0.9, "root-a"),
            EvidenceItem("source-b", "controlled_fixture", "supports", 0.8, "root-b"),
        ])
    else:
        evidence.extend([
            EvidenceItem("model-b", "model_output", "supports", 0.9, "model-root-b"),
            EvidenceItem("model-c", "model_output", "supports", 0.8, "model-root-c"),
        ])
    return verify_candidate_record(
        {"candidate_id": candidate_id},
        claim,
        evidence,
        VerificationPolicy(),
    )


with TemporaryDirectory() as tmp:
    root = Path(tmp)
    state_path = root / "state.json"
    audit_path = root / "audit.jsonl"
    controller = AdaptiveLearningController(state_path=state_path, audit_path=audit_path)

    base = controller.reliability("model", "model-a")
    assert base == 0.5

    # The old caller-controlled verdict/score API remains callable only to fail
    # closed. It cannot update reliability.
    legacy = controller.record_verified_outcome(
        kind="model",
        identity="model-a",
        supported=True,
        evidence_score=99.0,
    )
    assert legacy == {"updated": False, "reason": "structured_verification_required"}
    assert controller.reliability("model", "model-a") == base

    invalid_flags = controller.record_verified_outcome(
        kind="model",
        identity="model-a",
        verification_record=verified_record(
            "invalid-flags",
            claim="Control flags must be real booleans.",
        ),
        cleanliness_passed="yes",
    )
    assert invalid_flags["reason"] == "invalid_learning_control_flags", invalid_flags
    assert controller.reliability("model", "model-a") == base

    record = verified_record(
        "candidate-reward",
        claim="Independent fixtures support the target model output.",
    )
    rewarded = controller.record_verified_outcome(
        kind="model",
        identity="model-a",
        verification_record=record,
        cleanliness_passed=True,
    )
    assert rewarded["updated"] is True, rewarded
    assert controller.reliability("model", "model-a") > base

    # Replaying the same evidence cannot repeatedly increase trust, even if a
    # caller changes only candidate_id and recomputes a valid record.
    after_reward = controller.reliability("model", "model-a")
    duplicate = controller.record_verified_outcome(
        kind="model",
        identity="model-a",
        verification_record=record,
    )
    assert duplicate["reason"] == "duplicate_verified_outcome", duplicate
    replay_record = verified_record(
        "different-candidate-id",
        claim="Independent fixtures support the target model output.",
    )
    replay = controller.record_verified_outcome(
        kind="model",
        identity="model-a",
        verification_record=replay_record,
    )
    assert replay["reason"] == "duplicate_verified_outcome", replay
    reordered_record = verify_candidate_record(
        {"candidate_id": "reordered-candidate"},
        record["claim"],
        [EvidenceItem(**item) for item in reversed(record["evidence"])],
        VerificationPolicy(**record["policy"]),
    )
    reordered = controller.record_verified_outcome(
        kind="model",
        identity="model-a",
        verification_record=reordered_record,
    )
    assert reordered["reason"] == "duplicate_verified_outcome", reordered
    assert controller.reliability("model", "model-a") == after_reward

    # Derived evaluation fields and hashes are recomputed, not trusted.
    tampered = copy.deepcopy(record)
    tampered["evaluation"]["weighted_support"] = 999.0
    invalid = controller.record_verified_outcome(
        kind="model",
        identity="model-a",
        verification_record=tampered,
    )
    assert invalid["reason"] == "verification_record_invalid", invalid

    unrelated = controller.record_verified_outcome(
        kind="model",
        identity="unrelated-model",
        verification_record=record,
    )
    assert unrelated["reason"] == "identity_not_bound_to_evidence", unrelated

    # Agreement among models is explicitly insufficient corroboration.
    model_only = verified_record(
        "candidate-model-only",
        claim="Only model outputs repeat this claim.",
        external=False,
    )
    no_external = controller.record_verified_outcome(
        kind="model",
        identity="model-a",
        verification_record=model_only,
    )
    assert no_external["reason"] == "independent_corroboration_insufficient", no_external

    # A caller-supplied weak verification policy cannot weaken the learning
    # floor of two independent non-model corroborators.
    weak_record = verify_candidate_record(
        {"candidate_id": "candidate-weak-policy"},
        "One external fixture is not enough for learning.",
        [
            EvidenceItem(
                "weak-model", "model_output", "supports", 0.9, "unverified:weak-model"
            ),
            EvidenceItem("only-source", "reference", "supports", 0.9, "only-root"),
        ],
        VerificationPolicy(
            min_supporting_sources=1,
            min_independent_groups=1,
            min_weighted_support=0.1,
            max_weighted_contradiction=1.0,
            min_average_quality=0.1,
            require_non_llm_source=False,
        ),
    )
    weak = controller.record_verified_outcome(
        kind="model",
        identity="weak-model",
        verification_record=weak_record,
    )
    assert weak["reason"] == "independent_corroboration_insufficient", weak

    contradicted = verified_record(
        "candidate-penalty",
        claim="Independent fixtures contradict the target model output.",
        stance="contradicts",
    )
    penalized = controller.record_verified_outcome(
        kind="model",
        identity="model-a",
        verification_record=contradicted,
    )
    assert penalized["updated"] is True, penalized
    assert controller.reliability("model", "model-a") < after_reward

    # Two controller instances loaded before either write still preserve both
    # updates because every mutation performs a locked fresh read.
    stale_a = AdaptiveLearningController(state_path=state_path, audit_path=audit_path)
    stale_b = AdaptiveLearningController(state_path=state_path, audit_path=audit_path)
    record_b = verified_record(
        "candidate-b",
        claim="Independent fixtures support model B.",
        identity="model-b",
    )
    record_c = verified_record(
        "candidate-c",
        claim="Independent fixtures support model C.",
        identity="model-c",
    )
    assert stale_a.record_verified_outcome(
        kind="model", identity="model-b", verification_record=record_b
    )["updated"]
    assert stale_b.record_verified_outcome(
        kind="model", identity="model-c", verification_record=record_c
    )["updated"]
    fresh = AdaptiveLearningController(state_path=state_path, audit_path=audit_path)
    assert fresh.reliability("model", "model-b") > 0.5
    assert fresh.reliability("model", "model-c") > 0.5

    # Manual checkpoints remain reversible without affecting Truth.
    checkpoint_index = fresh.checkpoint("before source learning")
    source_record = verified_record(
        "candidate-source",
        claim="Two other fixtures corroborate source C.",
        identity="source-c",
        source_type="reference",
    )
    assert fresh.record_verified_outcome(
        kind="source", identity="source-c", verification_record=source_record
    )["updated"]
    assert fresh.reliability("source", "source-c") > 0.5
    fresh.rollback(checkpoint_index, reason="test rollback")
    assert fresh.reliability("source", "source-c") == 0.5

    status = fresh.status()
    assert status["truth_modified"] is False
    assert status["base_model_weights_modified"] is False
    assert status["pending_audit_events"] == 0


with TemporaryDirectory() as tmp:
    root = Path(tmp)
    anti_loop = AdaptiveLearningController(
        state_path=root / "state.json",
        audit_path=root / "audit.jsonl",
        policy=LearningPolicy(max_consecutive_rollbacks=3, recovery_observations_required=2),
    )

    for expected_streak in (1, 2, 3):
        outcome = anti_loop.record_verified_outcome(
            kind="model",
            identity="loop-model",
            verification_record=verified_record(
                f"regression-{expected_streak}",
                claim=f"Regression fixture {expected_streak} supports the model output.",
                identity="loop-model",
            ),
            regression_detected=True,
        )
        assert outcome["rolled_back"] is True, outcome
        assert outcome["rollback_streak"] == expected_streak, outcome

    assert outcome["frozen"] is True
    blocked = anti_loop.record_verified_outcome(
        kind="model",
        identity="loop-model",
        verification_record=verified_record(
            "recovery-1",
            claim="First distinct recovery fixture supports the model output.",
            identity="loop-model",
        ),
    )
    assert blocked["updated"] is False and blocked["frozen"] is True, blocked

    recovered = anti_loop.record_verified_outcome(
        kind="model",
        identity="loop-model",
        verification_record=verified_record(
            "recovery-2",
            claim="Second distinct recovery fixture supports the model output.",
            identity="loop-model",
        ),
    )
    assert recovered["recovered"] is True and recovered["frozen"] is False, recovered


with TemporaryDirectory() as tmp:
    root = Path(tmp)
    bounded = AdaptiveLearningController(
        state_path=root / "state.json",
        audit_path=root / "audit.jsonl",
        policy=LearningPolicy(max_processed_observations=1),
    )
    first = bounded.record_verified_outcome(
        kind="model",
        identity="bounded-a",
        verification_record=verified_record(
            "bounded-1",
            claim="First bounded observation.",
            identity="bounded-a",
        ),
    )
    assert first["updated"] is True, first
    capacity = bounded.record_verified_outcome(
        kind="model",
        identity="bounded-b",
        verification_record=verified_record(
            "bounded-2",
            claim="Second bounded observation.",
            identity="bounded-b",
        ),
    )
    assert capacity["reason"] == "observation_capacity_reached", capacity
    assert bounded.reliability("model", "bounded-b") == 0.5
    assert bounded.status()["processed_observations"] == 1


with TemporaryDirectory() as tmp:
    root = Path(tmp)
    state_path = root / "state.json"
    audit_path = root / "audit.jsonl"
    controller = AdaptiveLearningController(state_path=state_path, audit_path=audit_path)
    secret = "sk-proj-" + "A" * 24

    identity_rejection = controller.record_verified_outcome(
        kind="model",
        identity=secret,
        verification_record={},
    )
    assert identity_rejection["reason"] == "sensitive_identity_rejected"

    secret_record = verified_record(
        "candidate-secret",
        claim="Independent fixtures support a record containing a forbidden excerpt.",
        secret_excerpt=secret,
    )
    evidence_rejection = controller.record_verified_outcome(
        kind="model",
        identity="model-a",
        verification_record=secret_record,
    )
    assert evidence_rejection["reason"] == "sensitive_verification_rejected"
    persisted = ""
    if state_path.exists():
        persisted += state_path.read_text(encoding="utf-8")
    if audit_path.exists():
        persisted += audit_path.read_text(encoding="utf-8")
    assert secret not in persisted


with TemporaryDirectory() as tmp:
    root = Path(tmp)
    state_path = root / "state.json"
    audit_path = root / "audit.jsonl"
    controller = AdaptiveLearningController(state_path=state_path, audit_path=audit_path)
    record = verified_record(
        "candidate-audit-recovery",
        claim="Audit recovery fixture supports the target model output.",
    )
    # The state commit survives an interrupted JSONL append and retains the
    # exact pending event for idempotent recovery.
    with patch.object(
        learning_controller,
        "append_jsonl_record",
        side_effect=OSError("synthetic audit interruption"),
    ):
        try:
            controller.record_verified_outcome(
                kind="model", identity="model-a", verification_record=record
            )
        except LearningStateError:
            pass
        else:
            raise AssertionError("Interrupted audit append must surface")

    committed = json.loads(state_path.read_text(encoding="utf-8"))
    assert committed["models"]["model-a"]["reliability"] > 0.5
    assert len(committed["pending_audit"]) == 1

    recovered_controller = AdaptiveLearningController(
        state_path=state_path, audit_path=audit_path
    )
    recovery = recovered_controller.recover_pending_audit()
    assert recovery["recovered"] == 1 and recovery["pending"] == 0, recovery
    before_retry = recovered_controller.reliability("model", "model-a")
    duplicate = recovered_controller.record_verified_outcome(
        kind="model", identity="model-a", verification_record=record
    )
    assert duplicate["reason"] == "duplicate_verified_outcome", duplicate
    assert recovered_controller.reliability("model", "model-a") == before_retry
    records = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert len({item["event_id"] for item in records}) == len(records)

try:
    AdaptiveLearningController(policy=LearningPolicy(reward_step=float("nan")))
except ValueError:
    pass
else:
    raise AssertionError("non-finite learning policy was accepted")

print("ADAPTIVE LEARNING TEST: PASS")
