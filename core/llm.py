"""
AION LLM Gateway

Engine обращается только к этому модулю.
Конкретный провайдер выбирается через registry.
"""

from providers.registry import create_provider
from core.runtime_budget import current_budget
from memory.session import apply_profile


def ask_llm(prompt: str, max_tokens: int | None = None, model: str | None = None) -> str:
    """Единая точка запроса к LLM с опциональным лимитом и выбором модели."""
    budget = current_budget()
    timeout = None
    if budget is not None:
        budget.reserve_call()
        timeout = budget.provider_timeout()
    provider = create_provider(model=model, timeout=timeout)
    return provider.ask(prompt, max_tokens=max_tokens)


def llm_status(model: str | None = None) -> dict:
    """Безопасный статус LLM без вывода API-ключа."""
    apply_profile()
    provider = create_provider(model=model)
    return provider.health()
