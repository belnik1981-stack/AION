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


# A dynamic free router can pick a model that rejects reasoning.effort="none".
# If no effort is required, omit reasoning entirely rather than sending "none".
class FakeResponse:
    def __init__(self, result):
        self.result = result
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        return False
    def read(self):
        return json.dumps(self.result).encode("utf-8")


sent = []
def capture(req, timeout):
    payload = json.loads(req.data.decode("utf-8"))
    sent.append(payload)
    if payload.get("reasoning", {}).get("effort") == "none":
        error = {"error": {"message": "SENSITIVE-PROMPT", "metadata": {"error_type": "invalid_request"}}}
        raise HTTPError(req.full_url, 400, "Bad Request", {}, io.BytesIO(json.dumps(error).encode()))
    return FakeResponse(response(content="OK"))

with patch("providers.openai_compatible.urlopen", capture):
    with patch.dict(os.environ, {"AION_REASONING_EFFORT": "none"}):
        dynamic = OpenAICompatibleProvider(api_key="fixture", model="openrouter/free", free_only=True)
        assert dynamic.health()["reasoning_sent"] is False
        assert dynamic.ask("safe test", max_tokens=512) == "OK"
        assert "reasoning" not in sent[-1], sent[-1]
        named = OpenAICompatibleProvider(api_key="fixture", model="specific:free", free_only=True)
        assert named.ask("safe test", max_tokens=512) == "OK"
        assert "reasoning" not in sent[-1], sent[-1]
    with patch.dict(os.environ, {"AION_REASONING_EFFORT": "low"}):
        explicit = OpenAICompatibleProvider(api_key="fixture", model="specific:free", free_only=True)
        assert explicit.health()["reasoning_sent"] is True
        assert explicit.ask("safe test", max_tokens=512) == "OK"
        assert sent[-1]["reasoning"]["effort"] == "low", sent[-1]


def check_error400(error_type, expected):
    sensitive = "SENSITIVE-PROVIDER-USER-REFERENCE"
    payload = {"error": {"message": sensitive, "metadata": {
        "error_type": error_type, "provider_name": sensitive, "raw": sensitive}}}
    seen = []
    def fail(req, timeout):
        seen.append(True)
        raise HTTPError(req.full_url, 400, "Bad Request", {}, io.BytesIO(json.dumps(payload).encode()))
    with patch.dict(os.environ, {"AION_REASONING_EFFORT": "none"}):
        with patch("providers.openai_compatible.urlopen", fail):
            try:
                provider().ask("test", max_tokens=512)
            except ProviderError as exc:
                assert expected in str(exc), str(exc)
                assert sensitive not in str(exc)
                assert str(error_type) not in str(exc) if expected == "(unknown)" else True
            else:
                raise AssertionError("HTTP400 must fail closed")
    assert len(seen) == 1, "Never silently retry HTTP 400"


check_error400("invalid_request", "(invalid_request)")
check_error400("SENSITIVE-PROVIDER-USER-REFERENCE", "(unknown)")


# The live Critic was seen consuming its 450/900 token budgets on a dynamic
# free-router reasoning model. Verify the fixed bounded per-role configuration.
with patch.dict(os.environ, {}, clear=True):
    assert agents.ROLE_BUDGETS["critic"]() == 1600
    assert agents.ROLE_BUDGETS["verifier"]() == 1200
    assert agents.ROLE_BUDGETS["synthesizer"]() == 1400
    assert agents._ceiling() == 4096

def verify_critic_retry(effects, *, retry="1", ceiling="4096"):
    requests = []
    def fake_llm(prompt, max_tokens, model):
        requests.append((max_tokens, model))
        answer = effects.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer
    with patch.dict(os.environ, {
        "AION_ROLE_TOKEN_CEILING": ceiling,
        "AION_CRITIC_TOKENS": "1600",
        "AION_TRUNCATION_RETRY": retry,
    }):
        with patch.object(agents, "ask_llm", fake_llm), patch.object(
            agents, "governance_context", lambda: "test governance"
        ):
            answer = agents.critic("2 + 2 = 4", "Check arithmetic",
                                    "The result is 4", model="free-model:free")
    return answer, requests

answer, requests = verify_critic_retry([ProviderTruncatedError("max_tokens"), "OK"])
assert answer == "OK", answer
assert requests == [(1600, "free-model:free"), (3200, "free-model:free")], requests

answer, requests = verify_critic_retry([
    ProviderTruncatedError("max_tokens"), ProviderTruncatedError("max_tokens")
])
assert answer.startswith("[ОШИБКА:critic]") and len(requests) == 2, (answer, requests)

answer, requests = verify_critic_retry([ProviderRateLimitError("HTTP 429")])
assert "HTTP 429" in answer and len(requests) == 1, (answer, requests)

answer, requests = verify_critic_retry([ProviderTruncatedError("length"), ProviderTruncatedError("length")], ceiling="1800",
                                       retry="1")
assert answer.startswith("[ОШИБКА:critic]"), answer
assert requests[-1][0] == 1800 and len(requests) == 2, requests

print("PROVIDER RESILIENCE REGRESSION: PASS")
