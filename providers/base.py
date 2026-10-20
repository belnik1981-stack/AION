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
    """Typed 429 with only sanitized routing information.

    ``scope`` deliberately has three values.  A platform/account limit must
    stop all further calls, an upstream-provider limit may allow a bounded
    switch to a different model, and an unknown limit fails closed.
    """

    SAFE_SCOPES = frozenset({"platform", "upstream_provider", "unknown"})

    def __init__(
        self,
        detail: str,
        *,
        scope: str = "unknown",
        retry_after_seconds: int | None = None,
    ):
        super().__init__(detail)
        self.scope = scope if scope in self.SAFE_SCOPES else "unknown"
        self.retry_after_seconds = (
            retry_after_seconds
            if type(retry_after_seconds) is int and 0 < retry_after_seconds <= 86400
            else None
        )


class ProviderResponseTooLargeError(ProviderError):
    """Provider response exceeded the configured byte limit."""
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
