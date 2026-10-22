"""Offline regression for the global deadline, call and model-count limits."""

import os
from unittest.mock import patch

from core import llm, pipeline
from core.runtime_budget import ExecutionBudget, RuntimeLimitError, use_budget
from core.truth import get_execution_limits
from providers.base import (
    ProviderHTTPError,
    ProviderRateLimitError,
    ProviderResponseTooLargeError,
)


now = [100.0]
budget = ExecutionBudget(timeout_seconds=2, max_calls=2, clock=lambda: now[0])
budget.reserve_call()
budget.reserve_call()
try:
    budget.reserve_call()
except RuntimeLimitError as exc:
    assert exc.code == "runtime_call_limit_exceeded"
else:
    raise AssertionError("A third call must be blocked before provider access")
assert budget.snapshot()["calls_used"] == 2

deadline = ExecutionBudget(timeout_seconds=2, max_calls=2, clock=lambda: now[0])
now[0] = 103.0
try:
    deadline.reserve_call()
except RuntimeLimitError as exc:
    assert exc.code == "runtime_deadline_exceeded"
else:
    raise AssertionError("Expired deadline must block provider access")


created = []


class FakeProvider:
    def ask(self, prompt, max_tokens=None):
        return "safe result"


def fake_create_provider(*, model=None, timeout=None):
    created.append((model, timeout))
    return FakeProvider()


now[0] = 200.0
gateway_budget = ExecutionBudget(timeout_seconds=5, max_calls=1, clock=lambda: now[0])
with patch.object(llm, "create_provider", fake_create_provider):
    with use_budget(gateway_budget):
        assert llm.ask_llm("task", max_tokens=128, model="model-a:free") == "safe result"
        try:
            llm.ask_llm("task", max_tokens=128, model="model-a:free")
        except RuntimeLimitError as exc:
            assert exc.code == "runtime_call_limit_exceeded"
        else:
            raise AssertionError("Gateway must enforce the shared call budget")
assert len(created) == 1
assert created[0][0] == "model-a:free"
assert 0 < created[0][1] <= 5


# The longer Truth deadline applies only to a real multi-model selection.
truth_limits = get_execution_limits()
assert 0 < truth_limits["timeout_seconds"] < truth_limits["multi_model_timeout_seconds"] <= 180
with patch.dict(os.environ, {"AION_MODELS": "", "AION_MODEL": "model-a:free"}, clear=False):
    with patch.object(pipeline, "_run_pipeline_with_budget", return_value={"status": "ok"}):
        single_run = pipeline.run_pipeline("task")
with patch.dict(os.environ, {
    "AION_MODELS": "model-a:free,model-b:free",
}, clear=False):
    with patch.object(pipeline, "_run_pipeline_with_budget", return_value={"status": "ok"}):
        multi_run = pipeline.run_pipeline("task")
assert single_run["runtime_budget"]["timeout_seconds"] == truth_limits["timeout_seconds"]
assert multi_run["runtime_budget"]["timeout_seconds"] == truth_limits["multi_model_timeout_seconds"]

# Completed live preflight calls remain charged to the role execution budget.
shared = ExecutionBudget(
    timeout_seconds=truth_limits["multi_model_timeout_seconds"], max_calls=3
)
shared.reserve_call()
shared.reserve_call()
with patch.dict(os.environ, {"AION_MODELS": "model-a:free,model-b:free", "AION_MAX_LLM_CALLS": "3"}):
    with use_budget(shared), patch.object(
        pipeline, "_run_pipeline_with_budget", return_value={"status": "ok"}
    ):
        reused = pipeline.run_pipeline("compare")
assert reused["runtime_budget"]["calls_used"] == 2, reused
oversized = ExecutionBudget(timeout_seconds=truth_limits["multi_model_timeout_seconds"] + 1, max_calls=3)
with patch.dict(os.environ, {"AION_MODELS": "model-a:free,model-b:free", "AION_MAX_LLM_CALLS": "3"}):
    with use_budget(oversized):
        rejected_ambient = pipeline.run_pipeline("compare")
assert rejected_ambient["stage"] == "runtime_limits", rejected_ambient


# Five explicit model IDs are rejected before any provider call.
with patch.dict(os.environ, {
    "AION_MODELS": "a:free,b:free,c:free,d:free,e:free",
}, clear=False):
    with patch.object(pipeline, "ask_llm", side_effect=AssertionError("must not call provider")):
        rejected = pipeline.run_pipeline("compare")
assert rejected["status"] == "error", rejected
assert rejected["stage"] == "model_selection", rejected
assert rejected["runtime_budget"]["calls_used"] == 0, rejected


# A malformed configurable call budget fails closed before model selection.
with patch.dict(os.environ, {"AION_MAX_LLM_CALLS": "unbounded"}, clear=False):
    rejected_limit = pipeline.run_pipeline("compare")
assert rejected_limit["status"] == "error", rejected_limit
assert rejected_limit["stage"] == "runtime_limits", rejected_limit


# The pipeline shares one call budget across independent raw answers. The
# second request is blocked, so a one-model result cannot masquerade as a
# successful multi-model comparison.
created.clear()
with patch.dict(os.environ, {
    "AION_MODELS": "model-a:free,model-b:free",
    "AION_MAX_LLM_CALLS": "1",
    "AION_MULTI_TEST_ROUNDS": "1",
}, clear=False):
    with patch.object(llm, "create_provider", fake_create_provider):
        limited = pipeline.run_pipeline("compare independently")
assert limited["status"] == "error", limited
assert limited["stage"] == "raw_multi_model", limited
assert limited["raw_diagnostics"]["model-b:free"]["status"] == "runtime_call_limit_exceeded", limited
assert limited["runtime_budget"]["calls_used"] == 1, limited


# Structured raw diagnostics expose only stable categories and validated HTTP
# status codes, never arbitrary provider exception attributes.
with patch.object(pipeline, "ask_llm", side_effect=ProviderHTTPError("PRIVATE", "hidden")):
    unsafe_status = pipeline._raw_answer_attempt("task", "model-a:free")
assert unsafe_status == {"status": "http_error", "http_status": "unknown"}, unsafe_status

with patch.object(pipeline, "ask_llm", side_effect=ProviderResponseTooLargeError("hidden")):
    too_large = pipeline._raw_answer_attempt("task", "model-a:free")
assert too_large == {"status": "response_too_large"}, too_large

with patch.object(pipeline, "ask_llm", side_effect=ProviderRateLimitError(
    "hidden", scope="upstream_provider", retry_after_seconds=11
)):
    rate_limited = pipeline._raw_answer_attempt("task", "model-a:free")
assert rate_limited == {
    "status": "rate_limited",
    "http_status": 429,
    "rate_limit_scope": "upstream_provider",
    "retry_after_seconds": 11,
}, rate_limited

print("[PASS] Global runtime deadline, model and LLM-call budgets fail closed")
