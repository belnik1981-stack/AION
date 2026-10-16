from pathlib import Path
from tempfile import TemporaryDirectory

from learning.controller import AdaptiveLearningController
from learning.policy_engine import TrustPolicyEngine


def check(name, condition):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}")
    if not condition:
        raise AssertionError(name)


print("========== AION TRUST POLICY ENGINE TEST ==========")

with TemporaryDirectory() as tmp:
    root = Path(tmp)
    controller = AdaptiveLearningController(
        state_path=root / "reliability.json",
        audit_path=root / "learning.jsonl",
    )
    engine = TrustPolicyEngine(controller)

    soft = engine.assess_and_learn(
        kind="model",
        identity="model-a",
        supported=True,
        evidence_score=1.8,
        importance=0.30,
        cleanliness=0.95,
        negative_impact=0.20,
    )
    check("level 1 allows learning", soft["learning"].get("updated") is True)
    check("level 1 keeps nonzero influence", soft["effective_influence_after"] > 0)

    strict = engine.assess_and_learn(
        kind="model",
        identity="model-b",
        supported=True,
        evidence_score=2.0,
        importance=0.80,
        cleanliness=0.68,
        negative_impact=0.55,
    )
    check("level 2 blocks learning", strict["learning"]["updated"] is False)
    check("level 2 limits influence", 0 < strict["effective_influence"] <= 0.35)

    isolated = engine.assess_and_learn(
        kind="model",
        identity="model-c",
        supported=True,
        evidence_score=2.5,
        importance=0.90,
        cleanliness=0.35,
        negative_impact=0.90,
    )
    check("level 3 blocks learning", isolated["learning"]["updated"] is False)
    check("level 3 zero influence", isolated["effective_influence"] == 0.0)

print("========== RESULT ==========")
print("TRUST POLICY ENGINE: PASS")
