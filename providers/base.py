"""
AION Provider Contract

Провайдер отвечает только за связь с LLM.
Остальная система не должна знать детали API.
"""


class ProviderError(Exception):
    """Ошибка провайдера."""
    pass


class BaseProvider:
    """Базовый контракт любого LLM-провайдера."""

    name = "base"

    def ask(self, prompt: str) -> str:
        raise NotImplementedError(
            "Provider должен реализовать метод ask()"
        )

    def health(self) -> dict:
        return {
            "provider": self.name,
            "status": "unknown",
        }
