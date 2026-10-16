"""
AION Provider Contract

Провайдер отвечает только за связь с LLM.
Остальная система не должна знать детали API.
"""


class ProviderError(Exception):
    """Ошибка провайдера."""
    pass


class ProviderTruncatedError(ProviderError):
    """The model hit its output limit; partial output must not be trusted."""
    pass


class ProviderRateLimitError(ProviderError):
    """Provider rejected a request for quota/rate reasons; do not retry automatically."""
    pass


class BaseProvider:
    """Базовый контракт любого LLM-провайдера."""

    name = "base"

    def ask(self, prompt: str, max_tokens: int | None = None) -> str:
        """Выполнить запрос. max_tokens — опциональный лимит конкретного вызова."""
        raise NotImplementedError(
            "Provider должен реализовать метод ask()"
        )

    def health(self) -> dict:
        return {
            "provider": self.name,
            "status": "unknown",
        }
