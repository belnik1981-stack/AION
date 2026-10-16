"""Deterministic multi-model runtime regression without external API."""
import os
from unittest.mock import patch
from core import pipeline


def run_case(answer_fn, final_check, role_fn=None, max_iterations=3):
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
    with patch.dict(os.environ, {"AION_MODELS": "model-a:free,model-b:free", "AION_EVIDENCE_BUNDLE": ""}):
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
            result = pipeline.run_pipeline("Compare claims.")
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
cycle, _, _ = run_case(
    lambda m: "raw evidence " + m,
    lambda task, answer, model=None: (False, "FAIL: evidence missing"),
)
assert cycle["status"] == "cycle_detected", cycle
assert cycle["rotations_used"] <= 2, cycle
assert cycle["cycle"]["type"] in {"revisited_state", "direct_repeat"}, cycle

print("MULTI MODEL RUNTIME REGRESSION: PASS")
