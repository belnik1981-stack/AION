"""Offline negative and invariance tests for the trial safety boundary."""
from __future__ import annotations

import hashlib
import io
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server
from core.execution import ExecutionBudget, ExecutionLimitError
from core.engine import run_cycle
from core.llm import ask_llm
from core.pipeline import run_pipeline
from core.truth import get_execution_limits
from providers.base import ProviderError
from providers.openai_compatible import OpenAICompatibleProvider

TRUTH_FILES = [
    ROOT / "knowledge" / "truth" / "truth.json",
    ROOT / "knowledge" / "truth" / "system.yaml",
]
LEGACY_STATE = ROOT / "state.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FakeProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def ask(self, prompt: str) -> str:
        self.calls.append(prompt)
        if "Оцени финальный ответ." in prompt:
            return "OK"
        return "OFFLINE_TEST_RESPONSE"

    def health(self) -> dict:
        return {"provider": "fake", "status": "ok"}


class OversizedResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, size: int) -> bytes:
        return b"x" * size


truth_before = {path: digest(path) for path in TRUTH_FILES}
legacy_state_before = digest(LEGACY_STATE)
fake = FakeProvider()

with patch("core.llm.create_provider", return_value=fake):
    result = run_pipeline("Проведи безопасный автономный тест ограничителей.")

assert result["status"] == "ok", result
assert result["execution"]["api_calls"] == 5, result["execution"]
assert len(fake.calls) == 5
assert len(fake.calls) <= get_execution_limits()["max_api_calls"]
assert {path: digest(path) for path in TRUTH_FILES} == truth_before
assert digest(LEGACY_STATE) == legacy_state_before

with patch("core.engine.ask_llm") as unexpected_call:
    try:
        run_cycle(None)
    except (TypeError, ValueError):
        pass
    else:
        raise AssertionError("Single cycle accepted an implicit empty task")
    unexpected_call.assert_not_called()

one_call_budget = ExecutionBudget(max_api_calls=1, max_total_seconds=10)
with patch("core.llm.create_provider", return_value=fake):
    ask_llm("first call", budget=one_call_budget)
    try:
        ask_llm("second call", budget=one_call_budget)
    except ExecutionLimitError:
        pass
    else:
        raise AssertionError("Second call escaped the API-call budget")

limits = get_execution_limits()
try:
    ask_llm("x" * (limits["max_prompt_chars"] + 1))
except ExecutionLimitError:
    pass
else:
    raise AssertionError("Oversized prompt was accepted")

page = server.render_page(
    {"last_answer": "</pre><script>alert(1)</script>"},
    {},
)
assert "<script>alert(1)</script>" not in page
assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page

provider = OpenAICompatibleProvider(
    api_url="https://provider.example/v1",
    api_key="test-key",
    model="test-model",
    timeout=1,
    max_tokens=10,
    max_response_bytes=1_024,
)
with patch(
    "providers.openai_compatible.urlopen",
    return_value=OversizedResponse(),
):
    try:
        provider.ask("bounded response test")
    except ProviderError as exc:
        assert "byte limit" in str(exc)
    else:
        raise AssertionError("Oversized provider response was accepted")

http_error = HTTPError(
    "https://provider.example/v1/chat/completions",
    401,
    "Unauthorized",
    {},
    io.BytesIO(b"SECRET_PROVIDER_BODY"),
)
with patch(
    "providers.openai_compatible.urlopen",
    side_effect=http_error,
):
    try:
        provider.ask("redaction test")
    except ProviderError as exc:
        assert "SECRET_PROVIDER_BODY" not in str(exc)
        assert "401" in str(exc)
    else:
        raise AssertionError("HTTP error was not raised")

try:
    OpenAICompatibleProvider(
        api_url="http://provider.example/v1",
        api_key="test-key",
        model="test-model",
    )
except ProviderError:
    pass
else:
    raise AssertionError("Insecure external provider URL was accepted")

print("TRIAL SAFETY TEST: PASS")
