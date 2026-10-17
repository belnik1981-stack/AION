"""
AION Provider Contract

Провайдер отвечает только за связь с LLM.
Остальная система не должна знать детали API.
"""


class ProviderError(Exception):
    """Ошибка провайдера."""
    pass


class ProviderHTTPError(ProviderError):
    """Safe HTTP failure with a machine-readable status for bounded routing."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code


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
