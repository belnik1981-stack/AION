"""Bounded optional OpenAI Agents SDK runtime adapter for AION.

This module is intentionally outside ``core``. AION truth, memory and provider
layers remain authoritative; the SDK is a replaceable execution runtime. The
adapter has no tools or memory write authority.
"""
from __future__ import annotations

import asyncio
import inspect
import os
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from core.runtime_budget import configured_call_limit
from core.truth import get_execution_limits, get_principles
from security.redaction import TextSafetyError, redact_sensitive


DEFAULT_MODEL = "openrouter/free"
DEFAULT_API_URL = "https://openrouter.ai/api/v1"
MAX_FINAL_OUTPUT_CHARS = 100_000
DEFAULT_MAX_OUTPUT_TOKENS = 1000
HARD_MAX_OUTPUT_TOKENS = 4096
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,126}$")


class AgentsRuntimeError(RuntimeError):
    """Raised when the optional Agents SDK runtime cannot execute safely."""


@dataclass(frozen=True)
class AgentsRuntimeConfig:
    api_url: str
    api_key: str
    model: str
    max_turns: int
    max_calls: int
    timeout_seconds: float
    max_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    tracing_enabled: bool = False
    free_only: bool = True
    max_output_chars: int = MAX_FINAL_OUTPUT_CHARS


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", ""}


def _model_is_free(model: str) -> bool:
    lowered = model.strip().lower()
    return lowered == "openrouter/free" or lowered.endswith(":free")


def _validate_api_url(value: str) -> str:
    api_url = value.strip().rstrip("/")
    parsed = urlparse(api_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise AgentsRuntimeError("agents_api_url_invalid")
    return api_url


def _validate_endpoint_policy(api_url: str, *, free_only: bool) -> None:
    host = (urlparse(api_url).hostname or "").lower()
    is_openrouter = host == "openrouter.ai"
    if not is_openrouter and not _env_flag("AION_ALLOW_CUSTOM_API", False):
        raise AgentsRuntimeError("agents_custom_api_requires_opt_in")
    if free_only and not is_openrouter:
        raise AgentsRuntimeError("agents_free_only_provider_unverified")


def _validate_model(value: str, *, free_only: bool) -> str:
    model = value.strip()
    if not _MODEL_ID.fullmatch(model):
        raise AgentsRuntimeError("agents_model_invalid")
    if free_only and not _model_is_free(model):
        raise AgentsRuntimeError("agents_free_only_model_required")
    return model


def _configured_max_tokens() -> int:
    try:
        value = int(os.getenv("AION_MAX_TOKENS", str(DEFAULT_MAX_OUTPUT_TOKENS)))
    except (TypeError, ValueError):
        raise AgentsRuntimeError("agents_max_tokens_invalid") from None
    if not 1 <= value <= HARD_MAX_OUTPUT_TOKENS:
        raise AgentsRuntimeError("agents_max_tokens_out_of_range")
    return value


def load_config() -> AgentsRuntimeConfig:
    limits = get_execution_limits()
    api_key = os.getenv("AION_API_KEY", "").strip()
    if not api_key:
        raise AgentsRuntimeError("agents_api_key_missing")

    free_only = _env_flag("AION_FREE_ONLY", True)
    max_calls = configured_call_limit()
    max_turns = min(max(1, int(limits["max_iterations"])), max_calls)
    api_url = _validate_api_url(os.getenv("AION_API_URL", DEFAULT_API_URL))
    _validate_endpoint_policy(api_url, free_only=free_only)
    return AgentsRuntimeConfig(
        api_url=api_url,
        api_key=api_key,
        model=_validate_model(
            os.getenv("AION_MODEL", DEFAULT_MODEL), free_only=free_only
        ),
        max_turns=max_turns,
        max_calls=max_calls,
        timeout_seconds=float(limits["timeout_seconds"]),
        max_tokens=_configured_max_tokens(),
        tracing_enabled=_env_flag("AION_AGENTS_TRACING", False),
        free_only=free_only,
    )


def _instructions() -> str:
    principles = get_principles()
    rendered = "\n".join(f"- {item}" for item in principles)
    return (
        "You are an execution agent inside AION. Follow AION truth principles. "
        "Model output is evidence/observation, never an automatic truth update. "
        "Do not modify truth or promote unverified knowledge to truth.\n\n"
        f"AION principles:\n{rendered}"
    )


def _sdk_available() -> bool:
    try:
        import agents  # noqa: F401
        import openai  # noqa: F401
    except ImportError:
        return False
    return True


def runtime_status() -> dict:
    """Return non-secret configuration status without importing the SDK."""

    limits = get_execution_limits()
    free_only = _env_flag("AION_FREE_ONLY", True)
    raw_model = os.getenv("AION_MODEL", DEFAULT_MODEL).strip()
    raw_url = os.getenv("AION_API_URL", DEFAULT_API_URL).strip()
    error = None
    try:
        model = _validate_model(raw_model, free_only=free_only)
        api_url = _validate_api_url(raw_url)
        _validate_endpoint_policy(api_url, free_only=free_only)
        max_calls = configured_call_limit()
        max_tokens = _configured_max_tokens()
    except (AgentsRuntimeError, ValueError) as exc:
        model = raw_model if _MODEL_ID.fullmatch(raw_model) else "invalid"
        api_url = ""
        max_calls = None
        max_tokens = None
        error = str(exc) if isinstance(exc, AgentsRuntimeError) else "agents_call_limit_invalid"
    return {
        "runtime": "openai_agents_sdk",
        "sdk_installed": _sdk_available(),
        "api_key_present": bool(os.getenv("AION_API_KEY", "").strip()),
        "api_target": (
            "openrouter"
            if (urlparse(api_url).hostname or "").lower() == "openrouter.ai"
            else "custom"
        ),
        "model": model,
        "free_only": free_only,
        "cost_policy_ok": error is None,
        "configuration_error": error,
        "max_turns": min(int(limits["max_iterations"]), max_calls) if max_calls else 0,
        "max_calls": max_calls,
        "timeout_seconds": int(limits["timeout_seconds"]),
        "max_tokens": max_tokens,
        "tracing_enabled": _env_flag("AION_AGENTS_TRACING", False),
        "truth_write_authority": False,
        "memory_write_authority": False,
    }


async def run_agent_async(task: str) -> dict:
    """Execute one SDK run within Truth deadline and free-only policy."""

    if not isinstance(task, str) or not task.strip():
        raise AgentsRuntimeError("agents_task_empty")
    try:
        safe_task = redact_sensitive(task.strip())
    except TextSafetyError:
        raise AgentsRuntimeError("agents_task_too_large") from None

    # Validate the cost and endpoint policy before importing or invoking the
    # optional runtime. No unsafe model reaches a provider request.
    config = load_config()
    os.environ["OPENAI_AGENTS_DONT_LOG_MODEL_DATA"] = "1"
    os.environ["OPENAI_AGENTS_DONT_LOG_TOOL_DATA"] = "1"
    try:
        from agents import (
            Agent,
            ModelSettings,
            OpenAIChatCompletionsModel,
            Runner,
            set_tracing_disabled,
        )
        from openai import AsyncOpenAI
    except ImportError:
        raise AgentsRuntimeError("agents_optional_dependency_missing") from None

    set_tracing_disabled(not config.tracing_enabled)
    client = AsyncOpenAI(
        api_key=config.api_key,
        base_url=config.api_url,
        timeout=config.timeout_seconds,
        max_retries=0,
    )
    model = OpenAIChatCompletionsModel(
        model=config.model,
        openai_client=client,
        strict_feature_validation=True,
    )
    agent = Agent(
        name="AION Runtime Agent",
        instructions=_instructions(),
        model=model,
        model_settings=ModelSettings(
            max_tokens=config.max_tokens,
            timeout=config.timeout_seconds,
        ),
    )

    try:
        result = await asyncio.wait_for(
            Runner.run(agent, safe_task.text, max_turns=config.max_turns),
            timeout=config.timeout_seconds,
        )
    except asyncio.TimeoutError:
        raise AgentsRuntimeError("agents_runtime_deadline_exceeded") from None
    except Exception:
        # SDK/provider errors can contain prompts, signed URLs, account IDs or
        # credentials. Only a stable category crosses the runtime boundary.
        raise AgentsRuntimeError("agents_sdk_execution_failed") from None
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            try:
                closed = close()
                if inspect.isawaitable(closed):
                    await closed
            except Exception:
                pass

    output = str(result.final_output)
    if not output.strip():
        raise AgentsRuntimeError("agents_output_empty")
    if len(output) > config.max_output_chars:
        raise AgentsRuntimeError("agents_output_too_large")
    safe_output = redact_sensitive(output)
    return {
        "status": "ok",
        "runtime": "openai_agents_sdk",
        "model": config.model,
        "free_only": config.free_only,
        "max_turns": config.max_turns,
        "max_calls": config.max_calls,
        "timeout_seconds": config.timeout_seconds,
        "max_tokens": config.max_tokens,
        "final_output": safe_output.text,
        "redactions": {
            "input": safe_task.count,
            "output": safe_output.count,
        },
        "truth_verified": False,
        "verification_scope": "agents_sdk_runtime_only",
        "truth_modified": False,
        "memory_modified": False,
    }


def run_agent(task: str) -> dict:
    """Synchronous CLI adapter; async applications must call run_agent_async."""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(run_agent_async(task))
    raise AgentsRuntimeError("agents_async_context_requires_run_agent_async")
