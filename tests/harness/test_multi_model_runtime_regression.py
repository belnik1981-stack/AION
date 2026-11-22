"""Deterministic multi-model runtime regression without external API."""
import os
from unittest.mock import patch
from core import pipeline
from providers.base import ProviderTruncatedError, ProviderRateLimitError, ProviderHTTPError


def run_case(answer_fn, final_check, role_fn=None, max_iterations=3, prepared_raw=None):
    calls = []
    saved = []
    def ask(prompt, max_tokens, model):
        calls.append(model)
        return answer_fn(model)
    def role(role_name):
        def fake(*args, model=None, **kwargs):
            if role_fn is not None:
                return role_fn(role_name, model)
            return role_name + " by " + str(model)
        return fake
    with patch.dict(os.environ, {"AION_MODELS": "model-a:free,model-b:free", "AION_EVIDENCE_BUNDLE": "", "AION_TRUNCATION_RETRY": "1", "AION_ROLE_TOKEN_CEILING": "1800", "AION_ANALYST_TOKENS": "900"}):
        with patch.multiple(
            pipeline,
            get_execution_limits=lambda: {"max_iterations": max_iterations, "timeout_seconds": 30},
            ask_llm=ask,
            planner=role("planner"),
            analyst=role("analyst"),
            critic=role("critic"),
            synthesizer=role("synthesizer"),
            final_critic_check=final_check,
            add_episodic_event=lambda task, answer: saved.append(answer),
        ):
            result = pipeline.run_pipeline("Compare claims.", initial_raw_answers=prepared_raw)
    return result, calls, saved


# Opposing raw answers stay separate; a verifier determines acceptance, not majority vote.
ok, calls, saved = run_case(
    lambda m: "Claim true" if m == "model-a:free" else "Claim false",
    lambda task, answer, model=None: (True, "OK"),
)
assert ok["status"] == "ok", ok
assert ok["mode"] == "multi_model_role_rotation", ok
assert ok["independent_model_count"] == 2, ok
assert ok["raw_answers"]["model-a:free"] != ok["raw_answers"]["model-b:free"], ok
assert ok["rounds"][0]["role_assignment"]["planner"] != ok["rounds"][0]["role_assignment"]["analyst"], ok
assert calls[:2] == ["model-a:free", "model-b:free"], calls
assert ok["rotations_used"] == 1, ok
assert saved == ["synthesizer by model-b:free"], saved

# Losing a model cannot be classified as a successful multi-model consensus.
provider_failure, _, _ = run_case(
    lambda m: (_ for _ in ()).throw(RuntimeError("no provider")) if m == "model-b:free" else "Only one answer",
    lambda task, answer, model=None: (True, "OK"),
)
assert provider_failure["status"] == "error", provider_failure
assert provider_failure["stage"] == "raw_multi_model", provider_failure

# A failed role must not be passed off as validated output.
critic_failure, _, _ = run_case(
    lambda m: "raw evidence " + m,
    lambda task, answer, model=None: (True, "OK"),
    role_fn=lambda role, model: "[ОШИБКА:critic] provider unavailable" if role == "critic" else role + " ok",
)
assert critic_failure["status"] == "error", critic_failure
assert critic_failure["stage"] == "critic", critic_failure

# Repeated synthesized answer with unverifiable result must stop before max rounds.
cycle, _, rejected_memory = run_case(
    lambda m: "raw evidence " + m,
    lambda task, answer, model=None: (False, "FAIL: evidence missing"),
    role_fn=lambda role, model: "Same final answer" if role == "synthesizer" else role + " ok",
)
assert cycle["status"] == "cycle_detected", cycle
assert rejected_memory == [], rejected_memory
assert cycle["rotations_used"] <= 2, cycle
assert cycle["cycle"]["type"] in {"revisited_state", "direct_repeat"}, cycle

attempts = {}
def truncated_once(model):
    attempts[model] = attempts.get(model, 0) + 1
    if model == "model-a:free" and attempts[model] == 1:
        raise ProviderTruncatedError("length")
    return "independent response " + model


raw_retry, calls, _ = run_case(
    truncated_once,
    lambda task, answer, model=None: (True, "OK"),
)
assert raw_retry["status"] == "ok", raw_retry
assert raw_retry["independent_model_count"] == 2, raw_retry
assert calls[:3] == ["model-a:free", "model-a:free", "model-b:free"], calls


# Never downgrade a user-requested comparison to a single model after
# normalizing duplicates or dynamic openrouter/free model names.
for bad_models in (
    "model-a:free,model-a:free",
    "model-a:free,model-a:free,model-b:free",
    "openrouter/free,model-b:free",
    "model-a:free",
    "model-a:free,,model-b:free",
):
    with patch.dict(os.environ, {"AION_MODELS": bad_models, "AION_EVIDENCE_BUNDLE": ""}):
        with patch.object(pipeline, "planner", side_effect=AssertionError("Must not run LLM")):
            rejected = pipeline.run_pipeline("Compare independently.")
    assert rejected["status"] == "error" and rejected["stage"] == "model_selection", (bad_models, rejected)

# Distinct model IDs are not external evidence of truth, even if responses
# appear the same or the mocked verifier says OK.
same, calls, _ = run_case(
    lambda model: "Same unsupported claim",
    lambda task, answer, model=None: (True, "OK"),
)
assert same["status"] == "ok"
assert same["truth_verified"] is False and same["verification_scope"] == "llm_review_only"
assert same["independent_initial_outputs"] == 2 and same["model_ids_distinct"] is True
assert calls[:2] == ["model-a:free", "model-b:free"]

# If one model returns HTTP 429, do not invoke the next model in the raw stage.
rate_limited, calls, _ = run_case(
    lambda model: (_ for _ in ()).throw(ProviderRateLimitError("HTTP 429"))
        if model == "model-a:free" else "should never be requested",
    lambda task, answer, model=None: (True, "OK"),
)
assert rate_limited["status"] == "error"
assert rate_limited["stage"] == "raw_multi_model"
assert calls == ["model-a:free"], calls

# One verification rotation can be explicitly requested for a bounded live
# smoke without altering the immutable Truth iteration ceiling.
with patch.dict(os.environ, {"AION_MULTI_TEST_ROUNDS": "1"}):
    one_round, calls, _ = run_case(
        lambda model: "Response from " + model,
        lambda task, answer, model=None: (False, "FAIL: evidence not independently verified"),
    )
assert one_round["status"] == "rotations_exhausted", one_round
assert one_round["rotations_used"] == 1, one_round

# Preserve distinct, complete initial answers from a successful real task
# instead of sending two redundant "raw" requests after a 2+2 preflight.
prepared = {"model-a:free": "Independent A", "model-b:free": "Independent B"}
reused, calls, _ = run_case(
    lambda m: (_ for _ in ()).throw(AssertionError("Unexpected raw LLM request")),
    lambda task, answer, model=None: (True, "OK"),
    prepared_raw=prepared,
)
assert reused["status"] == "ok"
assert reused["raw_answers"] == prepared
assert all(reused["raw_diagnostics"][m] == {"status": "ok", "reused": True} for m in prepared)
assert calls == [], calls

# A partial or mismatched cache must not be reported as two independent
# model answers. These are rejected before any role is invoked.
for wrong_raw in (
    {"model-a:free": "one answer"},
    {"model-a:free": "A", "model-b:free": ""},
    {"model-a:free": "A", "model-b:free": "[ОШИБКА:raw] HTTP 404"},
    {"model-a:free": "A", "not-our-model:free": "B"},
):
    bad, calls, _ = run_case(
        lambda m: "should-not-be-called",
        lambda task, answer, model=None: (True, "OK"),
        prepared_raw=wrong_raw,
    )
    assert bad["status"] == "error" and bad["stage"] == "raw_multi_model"
    assert not calls, calls

# Typed HTTP failures must expose which model failed without echoing
# provider-supplied error bodies or consuming extra requests on 429.
http_fail, calls, _ = run_case(
    lambda m: (_ for _ in ()).throw(ProviderHTTPError(502, "SECRET-TEXT"))
        if m == "model-a:free" else "Complete answer B",
    lambda task, answer, model=None: (True, "OK"),
)
assert http_fail["status"] == "error" and http_fail["stage"] == "raw_multi_model"
assert http_fail["raw_diagnostics"]["model-a:free"] == {
    "status": "http_error", "http_status": 502
}
assert "SECRET-TEXT" not in str(http_fail)
assert calls == ["model-a:free", "model-b:free"], calls

rate_diag, calls, _ = run_case(
    lambda m: (_ for _ in ()).throw(ProviderRateLimitError("secret-account-id"))
        if m == "model-a:free" else "Do not call",
    lambda task, answer, model=None: (True, "OK"),
)
assert rate_diag["status"] == "error" and rate_diag["stage"] == "raw_multi_model"
assert rate_diag["raw_diagnostics"]["model-a:free"]["status"] == "rate_limited"
assert "secret-account-id" not in str(rate_diag) and calls == ["model-a:free"]

# A model exhausting both bounded output budgets is logged as truncated,
# not misleadingly as "non-independent models".
truncated, calls, _ = run_case(
    lambda m: (_ for _ in ()).throw(ProviderTruncatedError("length"))
        if m == "model-a:free" else "Answer B",
    lambda task, answer, model=None: (True, "OK"),
)
assert truncated["stage"] == "raw_multi_model"
assert truncated["raw_diagnostics"]["model-a:free"]["status"] == "truncated"
assert calls[:2] == ["model-a:free", "model-a:free"] and len(calls) == 3

# Invalid rotation limits fail closed instead of raising.
for invalid_rounds in ("abc", "1.5", "0", "-1", "999"):
    with patch.dict(os.environ, {"AION_MULTI_TEST_ROUNDS": invalid_rounds}):
        invalid, _, memory = run_case(
            lambda m: "Complete response " + m,
            lambda task, answer, model=None: (True, "OK"),
        )
    assert invalid["status"] == "error" and invalid["stage"] == "model_selection", invalid
    assert memory == [], memory

print("MULTI MODEL RUNTIME REGRESSION: PASS")
