"""Offline integration test for the non-authoritative commercial risk view."""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from core import pipeline
from core.claim_registry import build_claim_registry
from core.commercial_bridge import parallel_commercial_view


answers = {
    "model-a:free": "A disputed claim remains uncertain.",
    "model-b:free": "A separate claim remains uncertain.",
}
registry = build_claim_registry(answers)
baseline_snapshot = json.dumps(registry, sort_keys=True, ensure_ascii=False)
disabled = parallel_commercial_view(registry, list(answers))
assert disabled["status"] == "not_configured"
assert disabled["trusted_pipeline_modified"] is False

with TemporaryDirectory() as temp_dir:
    config = Path(temp_dir) / "commercial-factors.json"
    config.write_text(json.dumps({
        "version": 1,
        "targets": {
            "model-a:free": {
                "factors": {
                    "financial_dependency": 0.95,
                    "funding_opacity": 0.85,
                    "ownership_concentration": 0.90,
                    "conflict_of_interest": 0.95,
                    "incentive_to_distort": 0.90,
                    "positive_work_motivation": 0.20,
                    "harmful_behavior_risk_if_used": 0.75,
                    "harmful_behavior_risk_if_refused": 0.10,
                    "reverse_incentive_risk": 0.15,
                    "consequence_reversibility": 0.25,
                    "evidence_quality": 0.80
                },
                "basis": ["synthetic unverified fixture"]
            },
            "model-b:free": {
                "factors": {"evidence_quality": 0.90},
                "basis": []
            }
        }
    }), encoding="utf-8")

    view = parallel_commercial_view(registry, list(answers), config)
    assert view["status"] == "parallel_analysis_only", view
    assert view["commercial_causality_verified"] is False
    assert view["decision_authority"] == "none"
    assert view["trusted_pipeline_modified"] is False
    assert view["assessments"]["model-a:free"]["quarantine_level"] == 3
    assert view["assessments"]["model-a:free"]["auto_learning_applied"] is False
    model_a = [item for item in view["influence_comparison"] if item["model_id"] == "model-a:free"]
    assert model_a and all(item["with_commercial_layer"] == 0.0 for item in model_a)
    assert json.dumps(registry, sort_keys=True, ensure_ascii=False) == baseline_snapshot

    # The main pipeline exposes both paths but does not feed this layer into
    # Planner, Synthesizer or the accepted base answer.
    with patch.dict(os.environ, {
        "AION_MODELS": "model-a:free,model-b:free",
        "AION_MULTI_TEST_ROUNDS": "1",
        "AION_COMMERCIAL_FACTORS_FILE": str(config),
    }, clear=False), patch.object(
        pipeline, "planner", return_value="plan"
    ), patch.object(pipeline, "analyst", return_value="analysis"), patch.object(
        pipeline, "critic", return_value="OK"
    ), patch.object(pipeline, "synthesizer", return_value="base final"), patch.object(
        pipeline, "final_critic_check", return_value=(True, "OK")
    ), patch.object(pipeline, "add_episodic_event", return_value=None):
        integrated = pipeline.run_pipeline("Compare", initial_raw_answers=answers)
    assert integrated["status"] == "ok", integrated
    assert integrated["final_answer"] == "base final", integrated
    assert integrated["commercial_dependency"]["status"] == "parallel_analysis_only"
    assert integrated["commercial_dependency"]["trusted_pipeline_modified"] is False

    invalid = Path(temp_dir) / "invalid.json"
    invalid.write_text(json.dumps({
        "version": 1,
        "targets": {"model-a:free": {"factors": {"financial_dependency": 2.0}}}
    }), encoding="utf-8")
    rejected = parallel_commercial_view(registry, list(answers), invalid)
    assert rejected["status"] == "rejected", rejected
    assert rejected["reason"] == "commercial_factor_out_of_range", rejected
    assert rejected["trusted_pipeline_modified"] is False

print("COMMERCIAL PARALLEL BRIDGE: PASS")
