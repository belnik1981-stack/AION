from commercial_dependency.layer import (
    CommercialFactors,
    assess_commercial_dependency,
    compare_parallel_outcomes,
)


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

    print("PASS: commercial dependency + incentive layer")


if __name__ == "__main__":
    main()
