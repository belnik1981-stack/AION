"""
AION Provider Registry

Единая точка выбора LLM-провайдера.
"""

import os

from providers.openai_compatible import (
    OpenAICompatibleProvider,
)


def create_provider():
    provider_name = os.getenv(
        "AION_PROVIDER",
        "openai_compatible",
    ).strip().lower()

    if provider_name == "openai_compatible":
        return OpenAICompatibleProvider()

    raise ValueError(
        f"Неизвестный провайдер: {provider_name}"
    )


def provider_status():
    provider = create_provider()
    return provider.health()
