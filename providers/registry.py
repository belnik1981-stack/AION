"""
AION Provider Registry

Единая точка выбора LLM-провайдера.
"""

import os

from providers.openai_compatible import OpenAICompatibleProvider


def create_provider(model: str | None = None, timeout: float | None = None):
    """Создать провайдер; model позволяет выбрать модель для конкретного вызова."""
    provider_name = os.getenv(
        "AION_PROVIDER",
        "openai_compatible",
    ).strip().lower()

    if provider_name == "openai_compatible":
        return OpenAICompatibleProvider(model=model, timeout_cap=timeout)

    raise ValueError(f"Неизвестный провайдер: {provider_name}")


def provider_status():
    provider = create_provider()
    return provider.health()
