"""
AION OpenAI-Compatible Provider

Работает с API, совместимыми с форматом:
POST /chat/completions
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
        max_tokens=1000,
    ):
        self.api_url = (
            api_url
            or os.getenv("AION_API_URL", "https://openrouter.ai/api/v1")
        ).rstrip("/")
        self.api_key = api_key or os.getenv("AION_API_KEY", "")
        self.model = model or os.getenv("AION_MODEL", "google/gemini-2.5-flash")
        self.timeout = timeout
        self.max_tokens = int(os.getenv("AION_MAX_TOKENS", max_tokens))

    def health(self) -> dict:
        return {
            "status": "ok" if self.api_key else "missing_api_key",
            "provider": self.name,
            "model": self.model,
            "max_tokens": self.max_tokens,
        }

    def ask(self, prompt: str) -> str:
        if not self.api_key:
            raise ProviderError("API-ключ не найден в переменных окружения (AION_API_KEY).")

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
                return data["choices"][0]["message"]["content"]
        except HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            raise ProviderError(f"HTTP {e.code}: {err_body}") from e
        except Exception as e:
            raise ProviderError(f"Ошибка запроса: {str(e)}") from e
