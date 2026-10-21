"""Integrated learning policy: quarantine + adaptive reliability.

This module is the single safe path for learning from evaluated information.
It combines the three-level quarantine with rollback-safe source/model learning.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .controller import AdaptiveLearningController
from .quarantine import assess_quarantine, effective_influence


class TrustPolicyEngine:
    def __init__(self, controller: AdaptiveLearningController | None = None) -> None:
        self.controller = controller or AdaptiveLearningController()

    def assess_and_learn(
        self,
        *,
        kind: str,
        identity: str,
        importance: float,
        cleanliness: float,
        negative_impact: float,
        verification_record: dict[str, Any] | None = None,
        regression_detected: bool = False,
        # Kept only for a fail-closed transition from the old API. Bare
        # verdicts and scores are never used for learning.
        supported: bool | None = None,
        evidence_score: float | None = None,
        contradicted: bool | None = None,
    ) -> dict[str, Any]:
        del supported, evidence_score, contradicted
        quarantine = assess_quarantine(
            importance=importance,
            cleanliness=cleanliness,
            negative_impact=negative_impact,
        )

        base_influence = self.controller.influence(kind, identity)
        result: dict[str, Any] = {
            "quarantine": asdict(quarantine),
            "base_influence": base_influence,
            "effective_influence": effective_influence(base_influence, quarantine),
            "truth_modified": False,
            "base_model_weights_modified": False,
        }

        if not quarantine.learning_allowed:
            result["learning"] = {
                "updated": False,
                "reason": f"blocked_by_quarantine_level_{quarantine.level}",
            }
            return result

        learning = self.controller.record_verified_outcome(
            kind=kind,
            identity=identity,
            verification_record=verification_record,
            cleanliness_passed=quarantine.cleanliness >= 0.70,
            regression_detected=regression_detected,
        )
        result["learning"] = learning
        result["base_influence_after"] = self.controller.influence(kind, identity)
        result["effective_influence_after"] = effective_influence(
            self.controller.influence(kind, identity), quarantine
        )
        return result
