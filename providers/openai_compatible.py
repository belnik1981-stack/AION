"""
AION OpenAI-Compatible Provider

Работает с API, совместимыми с форматом:
POST /chat/completions

Для OpenRouter поддерживает защитный режим AION_FREE_ONLY=1:
в этом режиме разрешены только openrouter/free и модели с суффиксом :free.
"""

import json
import os
import re
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from providers.base import BaseProvider, ProviderError, ProviderHTTPError, ProviderTruncatedError, ProviderRateLimitError


_REASONING_EFFORTS = {"max", "xhigh", "high", "medium", "low", "minimal", "none"}
_TRUNCATION_REASONS = {"length", "max_tokens", "max_output_tokens"}
_MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,126}$")
_REASONING_DISABLE_FREE_ALLOWLIST = {"x-ai/grok-4-fast:free"}
_SAFE_ERROR_TYPES = {"invalid_request", "invalid_prompt", "context_length_exceeded",
    "max_tokens_exceeded", "token_limit_exceeded", "not_found", "provider_unavailable",
    "provider_overloaded", "rate_limit_exceeded", "authentication", "timeout",
    "content_policy_violation"}


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", ""}


class OpenAICompatibleProvider(BaseProvider):
    name = "openai_compatible"

    def __init__(
        self,
        api_url=None,
        api_key=None,
        model=None,
        timeout=30,
        max_tokens=1000,
        free_only=None,
    ):
        self.api_url = (
            api_url
            or os.getenv("AION_API_URL", "https://openrouter.ai/api/v1")
        ).rstrip("/")
        self.api_key = api_key or os.getenv("AION_API_KEY", "")
        self.model = model or os.getenv("AION_MODEL", "openrouter/free")
        self.timeout = int(os.getenv("AION_TIMEOUT", timeout))
        self.max_tokens = int(os.getenv("AION_MAX_TOKENS", max_tokens))

        if free_only is None:
            default_free_only = "openrouter.ai" in self.api_url.lower()
            self.free_only = _env_flag("AION_FREE_ONLY", default_free_only)
        else:
            self.free_only = bool(free_only)

        self.reasoning_effort = os.getenv("AION_REASONING_EFFORT", "").strip().lower()
        if self.reasoning_effort and self.reasoning_effort not in _REASONING_EFFORTS:
            raise ProviderError(
                "Некорректный AION_REASONING_EFFORT: "
                f"{self.reasoning_effort}. Допустимо: {sorted(_REASONING_EFFORTS)}"
            )
        self.exclude_reasoning = _env_flag("AION_EXCLUDE_REASONING", True)
        self.disable_reasoning = _env_flag("AION_DISABLE_REASONING", False)
        self.last_response_meta = {}

    def _is_openrouter(self) -> bool:
        return "openrouter.ai" in self.api_url.lower()

    def _model_is_free(self) -> bool:
        model = self.model.strip().lower()
        return model == "openrouter/free" or model.endswith(":free")

    def _enforce_cost_policy(self) -> None:
        if self.free_only and self._is_openrouter() and not self._model_is_free():
            raise ProviderError(
                "AION_FREE_ONLY блокирует потенциально платную модель: "
                f"{self.model}. Используйте openrouter/free или модель с суффиксом :free."
            )
        if self.disable_reasoning and self._is_openrouter():
            if self.model not in _REASONING_DISABLE_FREE_ALLOWLIST:
                raise ProviderError(
                    "AION_DISABLE_REASONING разрешён только для явно "
                    "поддерживаемой бесплатной модели x-ai/grok-4-fast:free; "
                    "сбросьте эту переменную для других моделей."
                )
            if self.reasoning_effort not in ("", "none"):
                raise ProviderError(
                    "Нельзя одновременно задавать AION_DISABLE_REASONING=1 "
                    "и AION_REASONING_EFFORT отличное от none."
                )

    @staticmethod
    def _safe_error_type(error: HTTPError) -> str:
        """Only show a known OpenRouter error category; never echo provider text."""
        try:
            payload = json.loads(error.read(4096).decode("utf-8"))
            error_info = payload.get("error")
            if not isinstance(error_info, dict):
                return "unknown"
            metadata = error_info.get("metadata")
            if not isinstance(metadata, dict):
                return "unknown"
            value = metadata.get("error_type")
            return value if isinstance(value, str) and value in _SAFE_ERROR_TYPES else "unknown"
        except (ValueError, TypeError, UnicodeError, OSError):
            return "unknown"

    @staticmethod
    def _extract_content(data: dict, requested_max_tokens: int | None = None) -> str:
        try:
            choice = data["choices"][0]
            message = choice["message"]
            content = message.get("content")
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("Некорректная структура ответа LLM: отсутствует content.") from exc

        finish_reason = str(choice.get("finish_reason") or "").strip().lower()
        native_finish_reason = str(choice.get("native_finish_reason") or "").strip().lower()
        if finish_reason in _TRUNCATION_REASONS or native_finish_reason in _TRUNCATION_REASONS:
            usage = data.get("usage")
            usage = usage if isinstance(usage, dict) else {}
            details = usage.get("completion_tokens_details")
            details = details if isinstance(details, dict) else {}
            response_model = data.get("model")
            model_hint = (
                response_model
                if isinstance(response_model, str) and _MODEL_ID_PATTERN.fullmatch(response_model)
                else "unknown"
            )
            def num_or_unknown(value):
                return value if type(value) is int and 0 <= value <= 10000000 else "unknown"
            raise ProviderTruncatedError(
                "Ответ модели обрезан по лимиту вывода и не принят как завершённый: "
                f"finish_reason={choice.get('finish_reason')!r}, "
                f"native_finish_reason={choice.get('native_finish_reason')!r}, "
                f"response_model={model_hint}, "
                f"budget={num_or_unknown(requested_max_tokens)}, "
                f"completion_tokens={num_or_unknown(usage.get('completion_tokens'))}, "
                f"reasoning_tokens={num_or_unknown(details.get('reasoning_tokens'))}. "
                "Укажите конкретную доступную бесплатную модель вместо openrouter/free."
            )

        if not isinstance(content, str) or not content.strip():
            usage = data.get("usage") or {}
            details = usage.get("completion_tokens_details") or {}
            raise ProviderError(
                "Модель вернула пустой content; ответ не принят как успешный. "
                f"finish_reason={choice.get('finish_reason')!r}, "
                f"completion_tokens={usage.get('completion_tokens')!r}, "
                f"reasoning_tokens={details.get('reasoning_tokens')!r}."
            )

        return content

    def health(self) -> dict:
        if not self.api_key:
            status = "missing_api_key"
            policy = "not_checked"
        else:
            try:
                self._enforce_cost_policy()
                status = "ok"
                policy = "ok"
            except ProviderError as exc:
                status = "blocked_model"
                policy = str(exc)

        return {
            "status": status,
            "provider": self.name,
            "model": self.model,
            "max_tokens": self.max_tokens,
            "free_only": self.free_only,
            "reasoning_effort": self.reasoning_effort or "provider_default",
            "reasoning_sent": self._is_openrouter() and (self.disable_reasoning or self.reasoning_effort not in ("", "none")),
            "reasoning_disabled_requested": self.disable_reasoning,
            "policy": policy,
            "connection_verified": False,
            "note": "Конфигурация проверена локально; доступность модели проверяется только реальным запросом.",
        }

    def ask(self, prompt: str, max_tokens: int | None = None) -> str:
        if not self.api_key:
            raise ProviderError("API-ключ не найден в переменных окружения (AION_API_KEY).")

        self._enforce_cost_policy()

        endpoint = f"{self.api_url}/chat/completions"
        request_max_tokens = int(max_tokens) if max_tokens is not None else self.max_tokens
        if request_max_tokens <= 0:
            raise ProviderError("max_tokens должен быть > 0")

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": request_max_tokens,
        }

        # "none" is not universally supported, especially by mandatory-reasoning
        # models that may be randomly selected by openrouter/free. Omitting the
        # field lets the selected provider use its own defaults instead of HTTP 400.
        # This does NOT guarantee that internal reasoning is disabled.
        if self._is_openrouter() and self.disable_reasoning:
            payload["reasoning"] = {"enabled": False}
        elif self._is_openrouter() and self.reasoning_effort not in ("", "none"):
            payload["reasoning"] = {
                "effort": self.reasoning_effort,
                "exclude": self.exclude_reasoning,
            }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            req = Request(
                endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urlopen(req, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
                data = json.loads(raw)

            usage = data.get("usage") or {}
            cost = usage.get("cost")
            details = usage.get("completion_tokens_details") or {}
            choice = (data.get("choices") or [{}])[0] or {}
            self.last_response_meta = {
                "model": data.get("model"),
                "provider": data.get("provider"),
                "cost": cost,
                "total_tokens": usage.get("total_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "reasoning_tokens": details.get("reasoning_tokens"),
                "finish_reason": choice.get("finish_reason"),
                "native_finish_reason": choice.get("native_finish_reason"),
                "requested_max_tokens": request_max_tokens,
            }

            if self.free_only and cost not in (None, 0, 0.0, "0", "0.0"):
                raise ProviderError(
                    f"Провайдер сообщил ненулевую стоимость запроса: {cost}. "
                    "Ответ заблокирован политикой AION_FREE_ONLY."
                )

            return self._extract_content(data, requested_max_tokens=request_max_tokens)

        except HTTPError as e:
            # Do not log the upstream response: it can contain account IDs,
            # request excerpts or provider-specific personal metadata.
            if e.code == 429:
                raise ProviderRateLimitError(
                    "HTTP 429: бесплатный провайдер ограничил частоту запросов. "
                    "Автоматические повторы отключены; повторите позднее или "
                    "выберите другую доступную бесплатную модель (:free)."
                ) from e
            if e.code in (401, 403):
                raise ProviderError(
                    f"HTTP {e.code}: проверьте ключ и доступ к выбранной модели. "
                    "Ответ провайдера скрыт во избежание утечки данных."
                ) from e
            category = self._safe_error_type(e) if e.code == 400 else "unknown"
            if e.code == 400:
                raise ProviderHTTPError(
                    400,
                    f"HTTP 400 ({category}): провайдер отклонил параметры запроса "
                    "или требования выбранной модели. Проверьте совместимость модели, "
                    "бюджет токенов и настройку reasoning; исходное сообщение скрыто."
                ) from e
            raise ProviderHTTPError(
                e.code,
                f"HTTP {e.code}: запрос отклонён провайдером. "
                "Тело ответа скрыто во избежание утечки данных."
            ) from e
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(f"Ошибка запроса: {str(e)}") from e
