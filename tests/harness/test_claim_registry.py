"""Offline claim, source, disagreement and quarantine registry regression."""

import copy
import os
from unittest.mock import patch

from core import pipeline
from core.claim_registry import (
    ClaimRegistryEvidenceError,
    build_claim_registry,
    format_registry_for_prompt,
)
from core.evidence_bridge import load_analysis_evidence
from trials.evidence_objects_v2.run_trial import VALID_BUNDLE


answers = {
    "model-a:free": (
        "Water freezes at zero degrees. "
        "The observed result is uncertain. "
        "Perhaps rain will occur tomorrow. Source https://a.example/report. "
        "Two independent fixture roots support use of this record for bounded analysis."
    ),
    "model-b:free": (
        "Water not freezes at zero degrees. "
        "The observed result is uncertain. "
        "Rain will probably occur tomorrow. Source https://b.example/data"
    ),
    "model-c:free": "The observed result is uncertain.",
}
evidence_context = load_analysis_evidence(VALID_BUNDLE)

registry = build_claim_registry(answers, evidence_context)
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
assert registry["verification"]["evidence_context_integrity_verified"] is True
assert registry["verification"]["evidence_context_digest"] == evidence_context["context_digest"]

# A raw list can no longer be mislabeled as a validated Evidence Objects
# context, and mutation after bridge validation is detected.
try:
    build_claim_registry(answers, evidence_context["claims"])
except ClaimRegistryEvidenceError:
    pass
else:
    raise AssertionError("Raw evidence claims bypassed the bridge boundary")

tampered_context = copy.deepcopy(evidence_context)
tampered_context["claims"][0]["text"] = "Forged evidence text."
try:
    build_claim_registry(answers, tampered_context)
except ClaimRegistryEvidenceError:
    pass
else:
    raise AssertionError("Tampered evidence context entered the claim registry")

# The real pipeline rejects a modified context before the first provider call.
tampered_meta = {
    "enabled": True,
    "status": "available_for_analysis",
    "analysis_context": tampered_context,
}
with patch.dict(
    os.environ,
    {"AION_MODELS": "model-a:free,model-b:free"},
    clear=False,
), patch.object(
    pipeline, "_evidence_context", return_value=("", tampered_meta)
), patch.object(
    pipeline,
    "ask_llm",
    side_effect=AssertionError("provider must not be called"),
):
    rejected_context = pipeline.run_pipeline("Compare claims")
assert rejected_context["stage"] == "evidence_bridge", rejected_context
assert rejected_context["detail"] == "evidence_context_rejected_by_claim_registry"

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
    "AION_EVIDENCE_BUNDLE": str(VALID_BUNDLE),
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
assert integrated["claim_registry"]["verification"]["evidence_context_integrity_verified"] is True
assert "bundle_path" not in integrated["evidence"]["analysis_context"]
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
