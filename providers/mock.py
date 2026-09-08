"""Deterministic provider used only when AION_PROVIDER=mock."""
from providers.base import BaseProvider


class MockProvider(BaseProvider):
    name = "mock"

    def __init__(self) -> None:
        self.calls = 0

    def health(self) -> dict:
        return {
            "provider": self.name,
            "status": "ok",
            "mode": "offline_no_network",
        }

    def ask(self, prompt: str) -> str:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        self.calls += 1
        if "Оцени финальный ответ." in prompt:
            return "OK"
        return "MOCK_RESPONSE: bounded offline execution succeeded."
