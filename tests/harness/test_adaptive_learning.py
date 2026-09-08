from pathlib import Path
from tempfile import TemporaryDirectory

from learning.controller import AdaptiveLearningController


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

print("ADAPTIVE LEARNING TEST: PASS")
