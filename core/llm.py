"""Single bounded LLM gateway for AION."""
from __future__ import annotations

from core.execution import ExecutionBudget, validate_text
from core.truth import get_execution_limits
from providers.registry import create_provider


def ask_llm(prompt: str, budget: ExecutionBudget | None = None) -> str:
    limits = get_execution_limits()
    prompt = validate_text(prompt, limits["max_prompt_chars"], "prompt")
    timeout = float(limits["timeout_seconds"])
    if budget is not None:
        timeout = budget.acquire(timeout)
    provider = create_provider(timeout=timeout)
    return provider.ask(prompt)


def llm_status() -> dict:
    return create_provider().health()
