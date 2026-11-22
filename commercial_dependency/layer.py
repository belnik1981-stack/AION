"""Parallel commercial-dependency and incentive-distortion assessment.

Financial/commercial relationships are treated as causal-risk signals, never as
proof that factual content is false. Clean factual content remains separate.
This layer estimates distortion risk and compares decisions made with and
without the commercial-risk adjustment.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


def _c(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


@dataclass(frozen=True)
class CommercialFactors:
    financial_dependency: float = 0.0
    funding_opacity: float = 0.0
    ownership_concentration: float = 0.0
    conflict_of_interest: float = 0.0
    incentive_to_distort: float = 0.0
    positive_work_motivation: float = 0.0
    harmful_behavior_risk_if_used: float = 0.0
    harmful_behavior_risk_if_refused: float = 0.0
    reverse_incentive_risk: float = 0.0
    consequence_reversibility: float = 1.0
    evidence_quality: float = 0.5

    def normalised(self) -> "CommercialFactors":
        return CommercialFactors(**{k: _c(v) for k, v in asdict(self).items()})


@dataclass(frozen=True)
class CommercialAssessment:
    quarantine_level: int
    label: str
    distortion_risk: float
    motivation_benefit: float
    use_harm_risk: float
    refusal_harm_risk: float
    reverse_incentive_risk: float
    uncertainty_risk: float
    rollback_risk: float
    influence_multiplier: float
    keep_factual_data_separate: bool
    auto_learning_allowed: bool
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ParallelOutcomeComparison:
    predicted_without_layer: float
    predicted_with_layer: float
    actual_without_layer: float
    actual_with_layer: float
    predicted_delta: float
    actual_delta: float
    calibration_error: float
    negative_consequence: float
    rollback_risk: float
    rollback_required: bool
    preferred_path: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def assess_commercial_dependency(factors: CommercialFactors) -> CommercialAssessment:
    f = factors.normalised()

    structural = (
        0.28 * f.financial_dependency
        + 0.18 * f.funding_opacity
        + 0.14 * f.ownership_concentration
        + 0.20 * f.conflict_of_interest
        + 0.20 * f.incentive_to_distort
    )

    # Low-quality evidence increases uncertainty. It does not prove distortion,
    # but it prevents the system from confidently treating the relationship as benign.
    uncertainty = 1.0 - f.evidence_quality

    # Positive motivation is tracked separately. It can justify preserving a
    # useful incentive, but cannot erase evidence of conflict or distortion.
    motivation_benefit = f.positive_work_motivation

    # Ethical/consequence balance is directional: both action and refusal can
    # create harm. Reverse-incentive risk captures cases where removing an
    # incentive makes behaviour or quality worse.
    consequence_pressure = max(
        f.harmful_behavior_risk_if_used,
        f.harmful_behavior_risk_if_refused,
        f.reverse_incentive_risk,
    )

    distortion = _c(structural + 0.15 * uncertainty + 0.10 * consequence_pressure)

    # Motivation may lower operational concern only modestly. It never cancels
    # a high conflict-of-interest or manipulation signal.
    adjusted = _c(distortion - 0.10 * motivation_benefit)

    rollback_risk = _c(
        max(f.harmful_behavior_risk_if_used, f.harmful_behavior_risk_if_refused)
        * (1.0 - f.consequence_reversibility)
        + 0.35 * f.reverse_incentive_risk
    )

    reasons: list[str] = []
    if f.financial_dependency >= 0.70:
        reasons.append("high_financial_dependency")
    if f.funding_opacity >= 0.60:
        reasons.append("funding_opacity")
    if f.conflict_of_interest >= 0.60:
        reasons.append("material_conflict_of_interest")
    if f.incentive_to_distort >= 0.60:
        reasons.append("material_incentive_to_distort")
    if motivation_benefit >= 0.60:
        reasons.append("positive_work_motivation_present")
    if f.harmful_behavior_risk_if_used >= 0.60:
        reasons.append("harm_risk_if_used")
    if f.harmful_behavior_risk_if_refused >= 0.60:
        reasons.append("harm_risk_if_refused")
    if f.reverse_incentive_risk >= 0.60:
        reasons.append("reverse_incentive_risk")
    if uncertainty >= 0.50:
        reasons.append("commercial_causality_uncertain")

    forced_isolation = (
        (f.conflict_of_interest >= 0.80 and f.incentive_to_distort >= 0.70)
        or (adjusted >= 0.75)
        or (rollback_risk >= 0.75)
    )

    if forced_isolation:
        level = 3
        label = "isolation"
        influence = 0.0
        learning_allowed = False
        reasons.append("commercial_isolation_threshold")
    elif adjusted >= 0.40 or rollback_risk >= 0.40:
        level = 2
        label = "strict_quarantine"
        influence = round(max(0.10, 0.45 * (1.0 - adjusted)), 4)
        learning_allowed = False
        reasons.append("commercial_strict_quarantine")
    else:
        level = 1
        label = "soft_quarantine"
        influence = round(max(0.50, 1.0 - 0.55 * adjusted), 4)
        learning_allowed = True
        reasons.append("commercial_soft_quarantine")

    return CommercialAssessment(
        quarantine_level=level,
        label=label,
        distortion_risk=round(adjusted, 4),
        motivation_benefit=round(motivation_benefit, 4),
        use_harm_risk=round(f.harmful_behavior_risk_if_used, 4),
        refusal_harm_risk=round(f.harmful_behavior_risk_if_refused, 4),
        reverse_incentive_risk=round(f.reverse_incentive_risk, 4),
        uncertainty_risk=round(uncertainty, 4),
        rollback_risk=round(rollback_risk, 4),
        influence_multiplier=influence,
        keep_factual_data_separate=True,
        auto_learning_allowed=learning_allowed,
        reasons=reasons,
    )


def compare_parallel_outcomes(
    *,
    predicted_without_layer: float,
    predicted_with_layer: float,
    actual_without_layer: float,
    actual_with_layer: float,
    negative_consequence: float,
    consequence_reversibility: float,
    rollback_threshold: float = 0.20,
) -> ParallelOutcomeComparison:
    """Compare decisions made without and with the commercial-risk layer.

    Scores are normalised quality/benefit values where higher is better.
    A rollback is required when the commercial adjustment causes a sufficiently
    worse actual result or when observed negative consequences are too risky.
    """
    pwo = _c(predicted_without_layer)
    pw = _c(predicted_with_layer)
    awo = _c(actual_without_layer)
    aw = _c(actual_with_layer)
    neg = _c(negative_consequence)
    rev = _c(consequence_reversibility)
    threshold = max(0.0, float(rollback_threshold))

    predicted_delta = round(pw - pwo, 4)
    actual_delta = round(aw - awo, 4)
    calibration_error = round(abs(predicted_delta - actual_delta), 4)
    rollback_risk = round(_c(neg * (1.0 - rev) + max(0.0, -actual_delta)), 4)

    worsened_beyond_threshold = actual_delta <= -threshold
    consequence_beyond_threshold = rollback_risk >= threshold
    rollback_required = worsened_beyond_threshold or consequence_beyond_threshold

    if rollback_required:
        preferred = "without_commercial_adjustment"
        reason = "commercial_layer_worsened_actual_outcome_or_crossed_risk_threshold"
    elif actual_delta > 0:
        preferred = "with_commercial_adjustment"
        reason = "commercial_layer_improved_actual_outcome"
    else:
        preferred = "no_clear_advantage"
        reason = "difference_not_material"

    return ParallelOutcomeComparison(
        predicted_without_layer=pwo,
        predicted_with_layer=pw,
        actual_without_layer=awo,
        actual_with_layer=aw,
        predicted_delta=predicted_delta,
        actual_delta=actual_delta,
        calibration_error=calibration_error,
        negative_consequence=neg,
        rollback_risk=rollback_risk,
        rollback_required=rollback_required,
        preferred_path=preferred,
        reason=reason,
    )
