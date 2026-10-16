"""Offline regression: rate limits, truncated content and bounded role retries."""
import io
import json
import os
from unittest.mock import patch
from urllib.error import HTTPError

from core import agents
from providers.base import ProviderError, ProviderRateLimitError, ProviderTruncatedError
from providers.openai_compatible import OpenAICompatibleProvider


def response(*, content="4", finish_reason="stop", native_finish_reason="stop"):
    return {"choices": [{"message": {"content": content},
                         "finish_reason": finish_reason,
                         "native_finish_reason": native_finish_reason}]}


def provider():
    return OpenAICompatibleProvider(
        api_key="synthetic-fixture-not-a-key",
        model="test-model:free",
        api_url="https://openrouter.ai/api/v1",
        free_only=True,
    )


with patch.dict(os.environ, {"AION_REASONING_EFFORT": "none"}, clear=False):
    p = provider()
    assert p.health()["status"] == "ok"
    assert p.health()["connection_verified"] is False, p.health()
    assert OpenAICompatibleProvider._extract_content(response()) == "4"

    for reason_field in ("finish_reason", "native_finish_reason"):
        kwargs = {reason_field: "length"}
        try:
            p._extract_content(response(**kwargs))
        except ProviderTruncatedError as exc:
            assert "обрезан" in str(exc)
        else:
            raise AssertionError("Partial model output must be rejected")

    try:
        p._extract_content(response(content="   "))
    except ProviderError:
        pass
    else:
        raise AssertionError("Empty model content must be rejected")

    # Upstream errors can contain user IDs, prompts and account metadata.
    marker = "SENSITIVE-UPSTREAM-CONTENT"
    upstream = json.dumps({"error": {"message": marker, "metadata": {"user_id": marker}}})
    def ratelimited(req, timeout):
        raise HTTPError(req.full_url, 429, "Too Many Requests", {}, io.BytesIO(upstream.encode()))
    with patch("providers.openai_compatible.urlopen", ratelimited):
        try:
            p.ask("2+2", max_tokens=128)
        except ProviderRateLimitError as exc:
            assert "HTTP 429" in str(exc)
            assert marker not in str(exc), str(exc)
            assert "позднее" in str(exc)
        else:
            raise AssertionError("HTTP 429 must fail closed")
    # The free-only guard must still reject paid model IDs.
    with patch.dict(os.environ, {"AION_MODEL": "test-model-paid"}):
        paid = OpenAICompatibleProvider(api_key="fixture", model="model-paid", free_only=True)
        try:
            paid.ask("hello")
        except ProviderError as exc:
            assert "блокирует" in str(exc)
        else:
            raise AssertionError("Free-only must block paid IDs")


def retry_case(effects, *, setting="1", cap="1800"):
    seen = []
    def fake_llm(prompt, max_tokens, model):
        seen.append((max_tokens, model))
        item = effects.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item
    with patch.dict(os.environ, {
        "AION_ROLE_TOKEN_CEILING": cap,
        "AION_TRUNCATION_RETRY": setting,
        "AION_PLANNER_TOKENS": "512",
    }):
        with patch.object(agents, "ask_llm", fake_llm), patch.object(
            agents, "governance_context", lambda: "governance"
        ):
            return agents.planner("Short task", model="model:free"), seen


got, seen = retry_case([ProviderTruncatedError("length"), "Valid final result"])
assert got == "Valid final result", got
assert seen == [(512, "model:free"), (1024, "model:free")], seen

got, seen = retry_case([ProviderTruncatedError("length"), ProviderTruncatedError("length")])
assert got.startswith("[ОШИБКА:planner]"), got
assert len(seen) == 2, seen

got, seen = retry_case([ProviderRateLimitError("HTTP 429")])
assert "HTTP 429" in got and len(seen) == 1, (got, seen)

got, seen = retry_case([ProviderTruncatedError("length")], setting="0")
assert got.startswith("[ОШИБКА:planner]") and len(seen) == 1, (got, seen)

got, seen = retry_case([ProviderTruncatedError("length"), "Final answer"], cap="600")
assert got == "Final answer" and seen[-1][0] == 600, (got, seen)

got, seen = retry_case(["Done"])
assert got == "Done" and len(seen) == 1 and seen[0][0] == 512

print("PROVIDER RESILIENCE REGRESSION: PASS")
