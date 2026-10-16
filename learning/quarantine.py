"""Three-level trust quarantine for AION information and model outputs.

The quarantine level depends on:
- importance of the information for the current decision;
- cleanliness after filtering/normalisation;
- potential negative impact on the final result if the information is wrong.

Truth is never modified here.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


@dataclass(frozen=True)
class QuarantineAssessment:
    level: int
    label: str
    risk_score: float
    importance: float
    cleanliness: float
    negative_impact: float
    influence_multiplier: float
    auto_promote_allowed: bool
    learning_allowed: bool
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def assess_quarantine(
    *,
    importance: float,
    cleanliness: float,
    negative_impact: float,
) -> QuarantineAssessment:
    """Return a deterministic 3-level quarantine assessment.

    Level 1: soft quarantine. Information may participate with reduced weight.
    Level 2: strict quarantine. Influence is strongly capped; no auto-promotion.
    Level 3: isolation. Influence is zero and learning from this item is blocked.
    """
    importance = _clamp01(importance)
    cleanliness = _clamp01(cleanliness)
    negative_impact = _clamp01(negative_impact)
    contamination = 1.0 - cleanliness

    # High-importance information amplifies both contamination and possible harm.
    # The interaction term prevents a moderately dirty, moderately harmful item
    # from being underrated when both conditions occur together.
    risk = (
        importance * (0.40 * contamination + 0.60 * negative_impact)
        + 0.25 * contamination * negative_impact
    )
    risk = round(_clamp01(risk), 4)

    reasons: list[str] = []
    if importance >= 0.75:
        reasons.append("high_importance")
    if cleanliness < 0.70:
        reasons.append("cleanliness_below_preferred")
    if cleanliness < 0.40:
        reasons.append("low_cleanliness")
    if negative_impact >= 0.70:
        reasons.append("high_negative_impact")

    forced_isolation = (
        (importance >= 0.65 and cleanliness < 0.40)
        or (importance >= 0.55 and negative_impact >= 0.85)
        or (cleanliness < 0.25 and negative_impact >= 0.60)
    )

    if forced_isolation or risk > 0.60:
        level = 3
        label = "isolation"
        influence = 0.0
        auto_promote = False
        learning_allowed = False
        reasons.append("isolation_threshold_reached")
    elif risk > 0.28:
        level = 2
        label = "strict_quarantine"
        # Even a reliable model cannot make this item dominate the result.
        influence = round(min(0.35, 0.15 + 0.25 * cleanliness), 4)
        auto_promote = False
        learning_allowed = False
        reasons.append("strict_quarantine_threshold_reached")
    else:
        level = 1
        label = "soft_quarantine"
        influence = round(0.55 + 0.45 * cleanliness, 4)
        auto_promote = True
        learning_allowed = True
        reasons.append("soft_quarantine")

    return QuarantineAssessment(
        level=level,
        label=label,
        risk_score=risk,
        importance=importance,
        cleanliness=cleanliness,
        negative_impact=negative_impact,
        influence_multiplier=influence,
        auto_promote_allowed=auto_promote,
        learning_allowed=learning_allowed,
        reasons=reasons,
    )


def effective_influence(base_influence: float, assessment: QuarantineAssessment) -> float:
    """Apply quarantine to an existing source/model reliability influence."""
    base = _clamp01(base_influence)
    return round(base * assessment.influence_multiplier, 4)
