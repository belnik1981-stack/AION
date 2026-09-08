"""Single provider selection point for AION."""
from __future__ import annotations

import os

from core.truth import get_execution_limits
from providers.openai_compatible import OpenAICompatibleProvider


def _bounded_env_int(name: str, default: int, ceiling: int) -> int:
    raw = os.getenv(name)
    try:
        value = default if raw is None else int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not 1 <= value <= ceiling:
        raise ValueError(f"{name} must be between 1 and {ceiling}")
    return value


def create_provider(*, timeout: float | None = None):
    provider_name = os.getenv(
        "AION_PROVIDER",
        "openai_compatible",
    ).strip().lower()

    if provider_name == "mock":
        from providers.mock import MockProvider

        return MockProvider()

    if provider_name == "openai_compatible":
        limits = get_execution_limits()
        max_tokens = _bounded_env_int(
            "AION_MAX_TOKENS",
            limits["max_tokens"],
            limits["max_tokens"],
        )
        max_response_bytes = _bounded_env_int(
            "AION_MAX_RESPONSE_BYTES",
            limits["max_response_bytes"],
            limits["max_response_bytes"],
        )
        effective_timeout = (
            float(limits["timeout_seconds"])
            if timeout is None
            else min(float(timeout), float(limits["timeout_seconds"]))
        )
        return OpenAICompatibleProvider(
            timeout=effective_timeout,
            max_tokens=max_tokens,
            max_response_bytes=max_response_bytes,
        )

    raise ValueError(f"Unknown provider: {provider_name}")


def provider_status() -> dict:
    return create_provider().health()
