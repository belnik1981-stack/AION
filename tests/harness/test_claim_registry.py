"""Offline claim, source, disagreement and quarantine registry regression."""

import os
from unittest.mock import patch

from core import pipeline
from core.claim_registry import build_claim_registry, format_registry_for_prompt


answers = {
    "model-a:free": (
        "Water freezes at zero degrees. "
        "The observed result is uncertain. "
        "Perhaps rain will occur tomorrow. Source https://a.example/report"
    ),
    "model-b:free": (
        "Water not freezes at zero degrees. "
        "The observed result is uncertain. "
        "Rain will probably occur tomorrow. Source https://b.example/data"
    ),
    "model-c:free": "The observed result is uncertain.",
}
evidence_claims = [{
    "claim_id": "evidence-water",
    "text": "Water freezes at zero degrees.",
    "claim_type": "observation",
    "risk_class": "moderate",
    "evidence_refs": ["fragment-a"],
}]

registry = build_claim_registry(answers, evidence_claims)
assert registry["schema_version"] == "aion-claim-registry-v1"
assert registry["verification"]["objective_truth_verified"] is False
assert registry["verification"]["external_verification_performed"] is False
assert len(registry["agreement_groups"]) == 1, registry["agreement_groups"]
agreement = registry["agreement_groups"][0]
assert len(agreement["models"]) == 3, agreement
assert agreement["status"] == "multi_model_agreement_not_external_evidence"
assert len(registry["contradictions"]) == 1, registry["contradictions"]
assert registry["contradictions"][0]["status"] == "unresolved_possible_contradiction"
assert len(registry["model_reported_sources"]) == 2, registry["model_reported_sources"]
assert all(item["status"] == "model_reported_unverified" for item in registry["model_reported_sources"])
assert registry["evidence_alignments"], registry
assert registry["evidence_alignments"][0]["evidence_scope"] == "validated_bundle_analysis_only"

types = {item["claim_type"] for item in registry["observations"]}
assert "uncertainty_statement" in types
assert "assumption" in types or "prediction" in types
for observation in registry["observations"]:
    assert observation["verification"]["status"] == "unverified"
    assert observation["quarantine"]["auto_promote_allowed"] is False
    assert observation["quarantine"]["learning_allowed"] is False

rendered = format_registry_for_prompt(registry)
assert "not proof" in rendered
assert "CONTRADICTION?" in rendered


# The registry is part of the real multi-model result and is shown to role
# prompts, while majority agreement remains explicitly non-verifying.
captured_planner = []


def planner(task, model=None):
    captured_planner.append(task)
    return "plan"


with patch.dict(os.environ, {
    "AION_MODELS": "model-a:free,model-b:free,model-c:free",
    "AION_MULTI_TEST_ROUNDS": "1",
}, clear=False), patch.object(pipeline, "planner", planner), patch.object(
    pipeline, "analyst", return_value="analysis"
), patch.object(pipeline, "critic", return_value="OK"), patch.object(
    pipeline, "synthesizer", return_value="final"
), patch.object(pipeline, "final_critic_check", return_value=(True, "OK")), patch.object(
    pipeline, "add_episodic_event", return_value=None
):
    integrated = pipeline.run_pipeline("Compare claims", initial_raw_answers=answers)

assert integrated["status"] == "ok", integrated
assert integrated["claim_registry"]["observations"], integrated
assert integrated["claim_registry"]["verification"]["objective_truth_verified"] is False
assert "DETERMINISTIC CLAIM REGISTRY" in captured_planner[0], captured_planner[0]

with patch.dict(os.environ, {
    "AION_MODELS": "model-a:free,model-b:free,model-c:free",
    "AION_MULTI_TEST_ROUNDS": "1",
}, clear=False), patch.object(
    pipeline, "planner", return_value="[ОШИБКА:planner] provider_failure"
):
    failed_role = pipeline.run_pipeline("Compare claims", initial_raw_answers=answers)
assert failed_role["stage"] == "planner", failed_role
assert failed_role["raw_answers"] == answers, failed_role
assert failed_role["claim_registry"]["observations"], failed_role

secret_error = "PRIVATE-EVIDENCE-ERROR"
with patch.dict(os.environ, {"AION_EVIDENCE_BUNDLE": "/synthetic/bundle"}, clear=False), patch.object(
    pipeline, "load_analysis_evidence", side_effect=RuntimeError(secret_error)
):
    evidence_failure = pipeline.run_pipeline("Compare claims")
assert evidence_failure["stage"] == "evidence_bridge", evidence_failure
assert secret_error not in str(evidence_failure), evidence_failure

print("CLAIM AND DISAGREEMENT REGISTRY: PASS")
