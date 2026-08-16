"""
AION OpenAI-Compatible Provider

Работает с API, совместимыми с форматом:
POST /chat/completions

Не содержит ключей внутри кода.
"""

import json
import os
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from providers.base import BaseProvider, ProviderError


class OpenAICompatibleProvider(BaseProvider):
    name = "openai_compatible"

    def __init__(
        self,
        api_url=None,
        api_key=None,
        model=None,
        timeout=30,
    ):
        self.api_url = (
            api_url
            or os.getenv("AION_API_URL", "")
        ).strip()

        self.api_key = (
            api_key
            or os.getenv("AION_API_KEY", "")
        ).strip()

        self.model = (
            model
            or os.getenv("AION_MODEL", "")
        ).strip()

        self.timeout = timeout

    def health(self) -> dict:
        return {
            "provider": self.name,
            "configured": bool(
                self.api_url
                and self.api_key
                and self.model
            ),
            "model": self.model or None,
        }

    def ask(self, prompt: str) -> str:
        if not isinstance(prompt, str):
            raise ProviderError(
                "prompt должен быть строкой"
            )

        prompt = prompt.strip()

        if not prompt:
            raise ProviderError(
                "Пустой запрос"
            )

        if not self.api_url:
            raise ProviderError(
                "AION_API_URL не задан"
            )

        if not self.api_key:
            raise ProviderError(
                "AION_API_KEY не задан"
            )

        if not self.model:
            raise ProviderError(
                "AION_MODEL не задан"
            )

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            "temperature": 0.2,
        }

        request = Request(
            self.api_url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": (
                    f"Bearer {self.api_key}"
                ),
            },
        )

        try:
            with urlopen(
                request,
                timeout=self.timeout,
            ) as response:

                raw = response.read().decode(
                    "utf-8"
                )

            data = json.loads(raw)

            choices = data.get("choices")

            if not choices:
                raise ProviderError(
                    "API не вернул choices"
                )

            message = choices[0].get(
                "message",
                {},
            )

            content = message.get("content")

            if content is None:
                raise ProviderError(
                    "API не вернул message.content"
                )

            return str(content).strip()

        except HTTPError as exc:
            try:
                body = exc.read().decode(
                    "utf-8",
                    errors="replace",
                )
            except Exception:
                body = ""

            raise ProviderError(
                f"HTTP {exc.code}: {body[:500]}"
            ) from exc

        except URLError as exc:
            raise ProviderError(
                f"Сетевая ошибка: {exc}"
            ) from exc

        except json.JSONDecodeError as exc:
            raise ProviderError(
                "API вернул некорректный JSON"
            ) from exc

        except TimeoutError as exc:
            raise ProviderError(
                "Превышено время ожидания"
            ) from exc
