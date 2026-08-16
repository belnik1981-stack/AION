"""
AION LLM Gateway

Engine обращается только к этому модулю.
Конкретный провайдер выбирается через registry.
"""

from providers.registry import create_provider


def ask_llm(prompt: str) -> str:
    """Единая точка запроса к LLM."""

    provider = create_provider()
    return provider.ask(prompt)


def llm_status() -> dict:
    """Безопасный статус LLM без вывода API-ключа."""

    provider = create_provider()
    return provider.health()
