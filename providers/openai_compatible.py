"""Bounded OpenAI-compatible chat-completions provider."""
from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from providers.base import BaseProvider, ProviderError


class OpenAICompatibleProvider(BaseProvider):
    name = "openai_compatible"

    def __init__(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 30,
        max_tokens: int = 800,
        max_response_bytes: int = 1_048_576,
    ) -> None:
        self.api_url = (
            api_url
            if api_url is not None
            else os.getenv("AION_API_URL", "https://openrouter.ai/api/v1")
        ).rstrip("/")
        self.api_key = (
            api_key if api_key is not None else os.getenv("AION_API_KEY", "")
        )
        self.model = (
            model if model is not None else os.getenv("AION_MODEL", "openrouter/free")
        ).strip()
        self.timeout = float(timeout)
        self.max_tokens = int(max_tokens)
        self.max_response_bytes = int(max_response_bytes)
        self._validate_configuration()

    def _validate_configuration(self) -> None:
        parsed = urlparse(self.api_url)
        loopback_hosts = {"127.0.0.1", "::1", "localhost"}
        insecure_local = (
            parsed.scheme == "http"
            and parsed.hostname in loopback_hosts
            and os.getenv("AION_ALLOW_INSECURE_HTTP", "") == "1"
        )
        if parsed.scheme != "https" and not insecure_local:
            raise ProviderError("Provider URL must use HTTPS")
        if not parsed.hostname:
            raise ProviderError("Provider URL has no hostname")
        if not self.model:
            raise ProviderError("Provider model is empty")
        if self.timeout <= 0:
            raise ProviderError("Provider timeout must be greater than zero")
        if self.max_tokens <= 0:
            raise ProviderError("Provider max_tokens must be greater than zero")
        if self.max_response_bytes < 1_024:
            raise ProviderError("Provider response byte limit is too small")

    def health(self) -> dict:
        parsed = urlparse(self.api_url)
        return {
            "status": "ok" if self.api_key else "missing_api_key",
            "provider": self.name,
            "endpoint_host": parsed.hostname,
            "model": self.model,
            "timeout_seconds": self.timeout,
            "max_tokens": self.max_tokens,
            "max_response_bytes": self.max_response_bytes,
        }

    def ask(self, prompt: str) -> str:
        if not self.api_key:
            raise ProviderError("AION_API_KEY is not configured")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ProviderError("Prompt is empty")

        endpoint = f"{self.api_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": self.max_tokens,
        }
        request = Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "AION-trial/0.3",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw_bytes = response.read(self.max_response_bytes + 1)
            if len(raw_bytes) > self.max_response_bytes:
                raise ProviderError("Provider response exceeded the byte limit")
            data = json.loads(raw_bytes.decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("content is not a string")
            return content
        except ProviderError:
            raise
        except HTTPError as exc:
            raise ProviderError(f"Provider returned HTTP {exc.code}") from exc
        except (URLError, TimeoutError):
            raise ProviderError("Provider network request failed or timed out")
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError):
            raise ProviderError("Provider returned an invalid response")
        except Exception:
            raise ProviderError("Unexpected provider request failure")
