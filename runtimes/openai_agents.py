"""Optional OpenAI Agents SDK runtime adapter for AION.

This module is intentionally outside ``core``. AION truth, memory and provider
layers remain authoritative; the SDK is a replaceable execution runtime.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from core.truth import get_execution_limits, get_principles


class AgentsRuntimeError(RuntimeError):
    """Raised when the optional Agents SDK runtime cannot execute safely."""


@dataclass(frozen=True)
class AgentsRuntimeConfig:
    api_url: str
    api_key: str
    model: str
    max_turns: int
    tracing_enabled: bool = False


def load_config() -> AgentsRuntimeConfig:
    limits = get_execution_limits()
    api_key = os.getenv("AION_API_KEY", "").strip()
    if not api_key:
        raise AgentsRuntimeError("AION_API_KEY is not set")

    return AgentsRuntimeConfig(
        api_url=os.getenv("AION_API_URL", "https://openrouter.ai/api/v1").rstrip("/"),
        api_key=api_key,
        model=os.getenv("AION_MODEL", "google/gemini-2.5-flash"),
        max_turns=max(1, int(limits["max_iterations"])),
        tracing_enabled=os.getenv("AION_AGENTS_TRACING", "0") == "1",
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


def runtime_status() -> dict:
    """Return non-secret configuration status without importing the SDK."""
    limits = get_execution_limits()
    return {
        "runtime": "openai_agents_sdk",
        "sdk_installed": _sdk_available(),
        "api_key_present": bool(os.getenv("AION_API_KEY", "").strip()),
        "api_url": os.getenv("AION_API_URL", "https://openrouter.ai/api/v1"),
        "model": os.getenv("AION_MODEL", "google/gemini-2.5-flash"),
        "max_turns": int(limits["max_iterations"]),
        "tracing_enabled": os.getenv("AION_AGENTS_TRACING", "0") == "1",
    }


def _sdk_available() -> bool:
    try:
        import agents  # noqa: F401
        import openai  # noqa: F401
    except ImportError:
        return False
    return True


def run_agent(task: str) -> dict:
    """Execute one bounded Agents SDK run through the configured provider."""
    if not task or not task.strip():
        raise AgentsRuntimeError("Task is empty")

    try:
        from agents import Agent, AsyncOpenAI, OpenAIChatCompletionsModel, Runner
        from agents import set_tracing_disabled
    except ImportError as exc:
        raise AgentsRuntimeError(
            "Optional dependency is missing. Install requirements-agents.txt"
        ) from exc

    config = load_config()

    # Tracing is opt-in. This avoids sending traces with a third-party provider
    # key and keeps AION execution auditable through its own layers by default.
    set_tracing_disabled(not config.tracing_enabled)

    client = AsyncOpenAI(api_key=config.api_key, base_url=config.api_url)
    model = OpenAIChatCompletionsModel(
        model=config.model,
        openai_client=client,
        strict_feature_validation=True,
    )
    agent = Agent(
        name="AION Runtime Agent",
        instructions=_instructions(),
        model=model,
    )

    try:
        result = Runner.run_sync(agent, task.strip(), max_turns=config.max_turns)
    except Exception as exc:
        raise AgentsRuntimeError(f"Agents SDK execution failed: {exc}") from exc

    return {
        "status": "ok",
        "runtime": "openai_agents_sdk",
        "model": config.model,
        "max_turns": config.max_turns,
        "final_output": str(result.final_output),
    }
