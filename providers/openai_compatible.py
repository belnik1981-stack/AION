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
            # Для OpenRouter безопасный режим включён по умолчанию.
            default_free_only = "openrouter.ai" in self.api_url.lower()
            self.free_only = _env_flag("AION_FREE_ONLY", default_free_only)
        else:
            self.free_only = bool(free_only)

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
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("Некорректная структура ответа LLM: отсутствует content.") from exc

        if not isinstance(content, str) or not content.strip():
            raise ProviderError(
                "Модель вернула пустой content; ответ не принят как успешный."
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
            "policy": policy,
        }

    def ask(self, prompt: str) -> str:
        if not self.api_key:
            raise ProviderError("API-ключ не найден в переменных окружения (AION_API_KEY).")

        # Блокируем потенциально платный маршрут ДО сетевого запроса.
        self._enforce_cost_policy()

        endpoint = f"{self.api_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": self.max_tokens,
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
            actual_model = data.get("model")
            provider = data.get("provider")
            self.last_response_meta = {
                "model": actual_model,
                "provider": provider,
                "cost": cost,
                "total_tokens": usage.get("total_tokens"),
            }

            # Это второй барьер. Основной барьер выше не позволяет отправить
            # запрос платной модели, но если API всё же сообщает стоимость,
            # такой ответ не считается успешным.
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
