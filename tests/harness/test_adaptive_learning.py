from pathlib import Path
from tempfile import TemporaryDirectory

from learning.controller import AdaptiveLearningController, LearningPolicy


with TemporaryDirectory() as tmp:
    root = Path(tmp)
    controller = AdaptiveLearningController(
        state_path=root / "state.json",
        audit_path=root / "audit.jsonl",
    )

    base = controller.reliability("model", "model-a")
    assert base == 0.5

    result = controller.record_verified_outcome(
        kind="model",
        identity="model-a",
        supported=True,
        evidence_score=1.8,
        cleanliness_passed=True,
    )
    assert result["updated"] is True
    assert controller.reliability("model", "model-a") > base

    before_bad = controller.reliability("model", "model-a")
    result = controller.record_verified_outcome(
        kind="model",
        identity="model-a",
        supported=False,
        contradicted=True,
        evidence_score=1.9,
        cleanliness_passed=False,
    )
    assert controller.reliability("model", "model-a") < before_bad

    before_rollback = controller.reliability("model", "model-a")
    result = controller.record_verified_outcome(
        kind="model",
        identity="model-a",
        supported=True,
        evidence_score=1.9,
        cleanliness_passed=True,
        regression_detected=True,
    )
    assert result["rolled_back"] is True
    assert controller.reliability("model", "model-a") == before_rollback

    skipped = controller.record_verified_outcome(
        kind="model",
        identity="model-b",
        supported=True,
        evidence_score=0.7,
    )
    assert skipped["updated"] is False
    assert controller.reliability("model", "model-b") == 0.5

    status = controller.status()
    assert status["truth_modified"] is False
    assert status["base_model_weights_modified"] is False

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
            supported=True,
            evidence_score=1.9,
            cleanliness_passed=True,
            regression_detected=True,
        )
        assert outcome["rolled_back"] is True
        assert outcome["rollback_streak"] == expected_streak

    assert outcome["frozen"] is True

    blocked = anti_loop.record_verified_outcome(
        kind="model",
        identity="loop-model",
        supported=True,
        evidence_score=1.9,
        cleanliness_passed=True,
    )
    assert blocked["updated"] is False
    assert blocked["frozen"] is True

    recovered = anti_loop.record_verified_outcome(
        kind="model",
        identity="loop-model",
        supported=True,
        evidence_score=1.9,
        cleanliness_passed=True,
    )
    assert recovered["recovered"] is True
    assert recovered["frozen"] is False

print("ADAPTIVE LEARNING TEST: PASS")
