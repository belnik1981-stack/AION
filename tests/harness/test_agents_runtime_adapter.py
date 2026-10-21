import asyncio
import os
import sys
import types
from unittest.mock import patch

from runtimes.openai_agents import (
    AgentsRuntimeConfig,
    AgentsRuntimeError,
    load_config,
    run_agent,
    runtime_status,
)


with patch.dict(os.environ, {
    "AION_API_URL": "https://openrouter.ai/api/v1",
    "AION_MODEL": "openrouter/free",
    "AION_FREE_ONLY": "1",
    "AION_MAX_TOKENS": "1000",
}, clear=False):
    status = runtime_status()

assert status["runtime"] == "openai_agents_sdk"
assert isinstance(status["sdk_installed"], bool)
assert isinstance(status["api_key_present"], bool)
assert status["api_target"] == "openrouter"
assert status["model"] == "openrouter/free"
assert status["free_only"] is True
assert status["cost_policy_ok"] is True
assert status["configuration_error"] is None
assert isinstance(status["max_turns"], int) and status["max_turns"] > 0
assert isinstance(status["max_calls"], int) and status["max_calls"] >= status["max_turns"]
assert status["max_tokens"] == 1000
assert "api_key" not in status
assert "api_url" not in status
assert os.getenv("AION_API_KEY", "") not in str(status) if os.getenv("AION_API_KEY") else True
assert status["truth_write_authority"] is False
assert status["memory_write_authority"] is False

# OpenRouter execution defaults to free-only and rejects an explicitly paid
# model before any SDK/provider call.
with patch.dict(os.environ, {
    "AION_API_KEY": "synthetic-key",
    "AION_API_URL": "https://openrouter.ai/api/v1",
    "AION_MODEL": "vendor/paid-model",
    "AION_FREE_ONLY": "1",
}, clear=False):
    try:
        load_config()
    except AgentsRuntimeError as exc:
        assert str(exc) == "agents_free_only_model_required", str(exc)
    else:
        raise AssertionError("Paid model must be blocked in free-only mode")

with patch.dict(os.environ, {
    "AION_API_KEY": "synthetic-key",
    "AION_API_URL": "https://unverified-provider.example/v1",
    "AION_MODEL": "vendor/model:free",
    "AION_FREE_ONLY": "1",
    "AION_ALLOW_CUSTOM_API": "0",
}, clear=False):
    try:
        load_config()
    except AgentsRuntimeError as exc:
        assert str(exc) == "agents_custom_api_requires_opt_in", str(exc)
    else:
        raise AssertionError("Custom credential target must require explicit opt-in")

with patch.dict(os.environ, {
    "AION_API_KEY": "synthetic-key",
    "AION_API_URL": "https://openrouter.ai/api/v1",
    "AION_MODEL": "vendor/model:free",
    "AION_FREE_ONLY": "1",
    "AION_MAX_TOKENS": "999999",
}, clear=False):
    try:
        load_config()
    except AgentsRuntimeError as exc:
        assert str(exc) == "agents_max_tokens_out_of_range", str(exc)
    else:
        raise AssertionError("Unbounded output-token request must be blocked")


class FakeClient:
    created = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.closed = False
        self.__class__.created.append(self)

    async def close(self):
        self.closed = True


class FakeModel:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeSettings:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeAgent:
    created = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.__class__.created.append(self)


class FakeResult:
    def __init__(self, final_output):
        self.final_output = final_output


class FakeRunner:
    calls = []
    error = None
    delay = 0.0
    output = "safe output"

    @classmethod
    async def run(cls, agent, task, max_turns):
        cls.calls.append({
            "agent": agent,
            "task": task,
            "max_turns": max_turns,
            "model_logging": os.environ.get("OPENAI_AGENTS_DONT_LOG_MODEL_DATA"),
            "tool_logging": os.environ.get("OPENAI_AGENTS_DONT_LOG_TOOL_DATA"),
        })
        if cls.delay:
            await asyncio.sleep(cls.delay)
        if cls.error is not None:
            raise cls.error
        return FakeResult(cls.output)


tracing = []
fake_agents = types.ModuleType("agents")
fake_agents.Agent = FakeAgent
fake_agents.ModelSettings = FakeSettings
fake_agents.OpenAIChatCompletionsModel = FakeModel
fake_agents.Runner = FakeRunner
fake_agents.set_tracing_disabled = tracing.append
fake_openai = types.ModuleType("openai")
fake_openai.AsyncOpenAI = FakeClient

secret = "sk-proj-" + ("S" * 32)
FakeRunner.output = f"answer {secret}"
with patch.dict(sys.modules, {"agents": fake_agents, "openai": fake_openai}), patch.dict(
    os.environ,
    {
        "AION_API_KEY": "synthetic-key",
        "AION_API_URL": "https://openrouter.ai/api/v1",
        "AION_MODEL": "model/test:free",
        "AION_FREE_ONLY": "1",
        "AION_MAX_TOKENS": "1000",
        "AION_AGENTS_TRACING": "0",
    },
    clear=False,
):
    result = run_agent(f"task {secret}")

assert result["status"] == "ok"
assert result["model"] == "model/test:free"
assert result["truth_verified"] is False
assert result["verification_scope"] == "agents_sdk_runtime_only"
assert result["truth_modified"] is False and result["memory_modified"] is False
assert secret not in str(result)
assert result["redactions"] == {"input": 1, "output": 1}
assert secret not in FakeRunner.calls[-1]["task"]
assert FakeRunner.calls[-1]["max_turns"] == 3
assert tracing[-1] is True
assert FakeClient.created[-1].kwargs["max_retries"] == 0
assert FakeClient.created[-1].kwargs["timeout"] == 30.0
assert FakeClient.created[-1].closed is True
assert FakeAgent.created[-1].kwargs["model_settings"].kwargs["timeout"] == 30.0
assert FakeAgent.created[-1].kwargs["model_settings"].kwargs["max_tokens"] == 1000
assert FakeRunner.calls[-1]["model_logging"] == "1"
assert FakeRunner.calls[-1]["tool_logging"] == "1"

# Provider exception text is never serialized across the adapter boundary.
FakeRunner.error = RuntimeError(f"provider leaked {secret}")
with patch.dict(sys.modules, {"agents": fake_agents, "openai": fake_openai}), patch.dict(
    os.environ,
    {
        "AION_API_KEY": "synthetic-key",
        "AION_MODEL": "model/test:free",
        "AION_FREE_ONLY": "1",
        "AION_MAX_TOKENS": "1000",
    },
    clear=False,
):
    try:
        run_agent("safe task")
    except AgentsRuntimeError as exc:
        assert str(exc) == "agents_sdk_execution_failed", str(exc)
        assert secret not in str(exc)
    else:
        raise AssertionError("SDK error must fail closed")
FakeRunner.error = None

# A wall-clock deadline wraps the whole run in addition to each model-call
# timeout. A synthetic slow runner is cancelled without a provider response.
FakeRunner.delay = 0.05
short = AgentsRuntimeConfig(
    api_url="https://openrouter.ai/api/v1",
    api_key="synthetic-key",
    model="model/test:free",
    max_turns=1,
    max_calls=1,
    timeout_seconds=0.01,
    max_tokens=100,
)
with patch.dict(sys.modules, {"agents": fake_agents, "openai": fake_openai}), patch(
    "runtimes.openai_agents.load_config", return_value=short
):
    try:
        run_agent("safe task")
    except AgentsRuntimeError as exc:
        assert str(exc) == "agents_runtime_deadline_exceeded", str(exc)
    else:
        raise AssertionError("Whole-run deadline must stop a slow SDK run")
FakeRunner.delay = 0.0


async def reject_sync_adapter_inside_loop():
    try:
        run_agent("safe task")
    except AgentsRuntimeError as exc:
        assert str(exc) == "agents_async_context_requires_run_agent_async", str(exc)
    else:
        raise AssertionError("Sync adapter must not nest an event loop")


asyncio.run(reject_sync_adapter_inside_loop())

print("AGENTS RUNTIME ADAPTER TEST: PASS")
