"""
AION OpenAI-Compatible Provider

Работает с API, совместимыми с форматом:
POST /chat/completions

Для OpenRouter поддерживает защитный режим AION_FREE_ONLY=1:
в этом режиме разрешены только openrouter/free и модели с суффиксом :free.
"""

import json
import os
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from providers.base import BaseProvider, ProviderError


_REASONING_EFFORTS = {"max", "xhigh", "high", "medium", "low", "minimal", "none"}


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

    @staticmethod
    def _extract_content(data: dict) -> str:
        try:
            choice = data["choices"][0]
            message = choice["message"]
            content = message.get("content")
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("Некорректная структура ответа LLM: отсутствует content.") from exc

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
            "policy": policy,
        }

    def ask(self, prompt: str, max_tokens: int | None = None) -> str:
        if not self.api_key:
            raise ProviderError("API-ключ не найден в переменных окружения (AION_API_KEY).")

        self._enforce_cost_policy()

        effective_max_tokens = self.max_tokens if max_tokens is None else int(max_tokens)
        if effective_max_tokens <= 0:
            raise ProviderError("max_tokens должен быть > 0")

        endpoint = f"{self.api_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": effective_max_tokens,
        }

        if self._is_openrouter() and self.reasoning_effort:
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
            self.last_response_meta = {
                "model": data.get("model"),
                "provider": data.get("provider"),
                "cost": cost,
                "total_tokens": usage.get("total_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "reasoning_tokens": details.get("reasoning_tokens"),
                "max_tokens_requested": effective_max_tokens,
            }

            if self.free_only and cost not in (None, 0, 0.0, "0", "0.0"):
                raise ProviderError(
                    f"Провайдер сообщил ненулевую стоимость запроса: {cost}. "
                    "Ответ заблокирован политикой AION_FREE_ONLY."
                )

            return self._extract_content(data)

        except HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            raise ProviderError(f"HTTP {e.code}: {err_body}") from e
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(f"Ошибка запроса: {str(e)}") from e
