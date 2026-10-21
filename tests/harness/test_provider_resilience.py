"""Offline regression: rate limits, truncated content and bounded role retries."""
import io
import json
import os
from unittest.mock import patch
from urllib.error import HTTPError

from core import agents
from providers.base import (
    ProviderError,
    ProviderHTTPError,
    ProviderRateLimitError,
    ProviderResponseTooLargeError,
    ProviderTruncatedError,
)
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

hostile_empty = response(content="   ", finish_reason="PRIVATE-FINISH-DETAIL")
hostile_empty["usage"] = {"completion_tokens": "PRIVATE-TOKEN-DETAIL"}
try:
    p._extract_content(hostile_empty)
except ProviderError as exc:
    assert "PRIVATE" not in str(exc), str(exc)
    assert "finish_reason=unknown" in str(exc), str(exc)
else:
    raise AssertionError("Empty model content must fail safely")

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
            assert exc.scope == "unknown", exc.scope
            assert exc.retry_after_seconds is None
        else:
            raise AssertionError("HTTP 429 must fail closed")

    provider_limited = json.dumps({
        "error": {"message": marker, "metadata": {
            "error_type": "rate_limit_exceeded",
            "provider_code": 429,
            "provider_name": marker,
        }}
    })
    def upstream_429(req, timeout):
        raise HTTPError(
            req.full_url, 429, "Too Many Requests", {"Retry-After": "7"},
            io.BytesIO(provider_limited.encode()),
        )
    with patch("providers.openai_compatible.urlopen", upstream_429):
        try:
            p.ask("2+2", max_tokens=128)
        except ProviderRateLimitError as exc:
            assert exc.scope == "upstream_provider", exc.scope
            assert exc.retry_after_seconds == 7
            assert marker not in str(exc)
        else:
            raise AssertionError("Provider 429 must stay typed")

    platform_limited = json.dumps({
        "error": {"message": marker, "metadata": {
            "error_type": "rate_limit_exceeded",
        }}
    })
    def platform_429(req, timeout):
        raise HTTPError(
            req.full_url, 429, "Too Many Requests",
            {"X-RateLimit-Remaining": "0", "Retry-After": "60"},
            io.BytesIO(platform_limited.encode()),
        )
    with patch("providers.openai_compatible.urlopen", platform_429):
        try:
            p.ask("2+2", max_tokens=128)
        except ProviderRateLimitError as exc:
            assert exc.scope == "platform", exc.scope
            assert exc.retry_after_seconds == 60
            assert marker not in str(exc)
        else:
            raise AssertionError("Platform 429 must stop globally")

    def unauthorized(req, timeout):
        raise HTTPError(
            req.full_url, 401, "Unauthorized", {},
            io.BytesIO(json.dumps({"error": {"message": marker}}).encode()),
        )
    with patch("providers.openai_compatible.urlopen", unauthorized):
        try:
            p.ask("2+2", max_tokens=128)
        except ProviderHTTPError as exc:
            assert exc.status_code == 401
            assert marker not in str(exc)
        else:
            raise AssertionError("Unauthorized response must be typed")
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
assert got == "[ОШИБКА:planner] provider_rate_limited" and len(seen) == 1, (got, seen)

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
    def read(self, size=-1):
        return json.dumps(self.result).encode("utf-8")[:size]


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


# Successful responses are bounded before decoding, and unexpected exception
# text is never copied into a ProviderError visible to callers.
class OversizedResponse(FakeResponse):
    def read(self, size=-1):
        return b"x" * size


with patch.dict(os.environ, {"AION_MAX_RESPONSE_BYTES": "1024"}, clear=False):
    bounded = provider()
    with patch("providers.openai_compatible.urlopen", lambda req, timeout: OversizedResponse({})):
        try:
            bounded.ask("safe test", max_tokens=128)
        except ProviderResponseTooLargeError:
            pass
        else:
            raise AssertionError("Oversized provider response must fail closed")

secret_marker = "PRIVATE-EXCEPTION-METADATA"
with patch("providers.openai_compatible.urlopen", lambda req, timeout: (_ for _ in ()).throw(RuntimeError(secret_marker))):
    try:
        provider().ask("safe test", max_tokens=128)
    except ProviderError as exc:
        assert secret_marker not in str(exc), str(exc)
        assert "подробности скрыты" in str(exc), str(exc)
    else:
        raise AssertionError("Unexpected transport errors must fail closed")

with patch.dict(os.environ, {"AION_TIMEOUT": "90"}, clear=False):
    capped_timeout = OpenAICompatibleProvider(
        api_key="synthetic", model="test-model:free",
        api_url="https://openrouter.ai/api/v1", free_only=True,
        timeout_cap=1.5,
    )
    assert capped_timeout.timeout == 1.5, capped_timeout.timeout


# The live Critic was seen consuming its 450/900 token budgets on a dynamic
# free-router reasoning model. Verify the fixed bounded per-role configuration.
with patch.dict(os.environ, {}, clear=True):
    assert agents.ROLE_BUDGETS["planner"]() == 1600
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
assert answer == "[ОШИБКА:critic] provider_rate_limited" and len(requests) == 1, (answer, requests)

answer, requests = verify_critic_retry([ProviderTruncatedError("length"), ProviderTruncatedError("length")], ceiling="1800",
                                       retry="1")
assert answer.startswith("[ОШИБКА:critic]"), answer
assert requests[-1][0] == 1800 and len(requests) == 2, requests


# When openrouter/free changes upstream models, log only safely filtered
# model identity and numeric token usage, never arbitrary response text.
truncated_payload = response(content="private sample", finish_reason="length")
truncated_payload["model"] = "x-ai/grok-4-fast:free"
truncated_payload["usage"] = {
    "completion_tokens": 3200,
    "completion_tokens_details": {"reasoning_tokens": 3100},
}
try:
    OpenAICompatibleProvider._extract_content(truncated_payload, requested_max_tokens=3200)
except ProviderTruncatedError as exc:
    msg = str(exc)
    assert "response_model=x-ai/grok-4-fast:free" in msg, msg
    assert "budget=3200" in msg and "reasoning_tokens=3100" in msg, msg
    assert "private sample" not in msg
else:
    raise AssertionError("truncation must be rejected")

truncated_payload["model"] = "SENSITIVE user_id=123 >"
try:
    OpenAICompatibleProvider._extract_content(truncated_payload, requested_max_tokens=3200)
except ProviderTruncatedError as exc:
    msg = str(exc)
    assert "response_model=unknown" in msg and "user_id" not in msg, msg
else:
    raise AssertionError("truncation must be rejected")

# Explicit reasoning.disable is allowed only for an externally confirmed model.
with patch.dict(os.environ, {
    "AION_REASONING_EFFORT": "none",
    "AION_DISABLE_REASONING": "1",
}):
    with patch("providers.openai_compatible.urlopen", capture):
        fixed = OpenAICompatibleProvider(
            api_key="synthetic", model="x-ai/grok-4-fast:free", free_only=True
        )
        assert fixed.health()["status"] == "ok", fixed.health()
        assert fixed.health()["reasoning_disabled_requested"] is True
        assert fixed.ask("2+2", max_tokens=512) == "OK"
        assert sent[-1]["model"] == "x-ai/grok-4-fast:free", sent[-1]
        assert sent[-1]["reasoning"] == {"enabled": False}, sent[-1]

        dynamic = OpenAICompatibleProvider(
            api_key="synthetic", model="openrouter/free", free_only=True
        )
        assert dynamic.health()["status"] == "blocked_model"
        try:
            dynamic.ask("2+2", max_tokens=512)
        except ProviderError as exc:
            assert "AION_DISABLE_REASONING" in str(exc)
        else:
            raise AssertionError("Unverified free router must not be force-disabled")

        different = OpenAICompatibleProvider(
            api_key="synthetic", model="cohere/north-mini-code:free", free_only=True
        )
        assert different.health()["status"] == "blocked_model"

with patch.dict(os.environ, {
    "AION_REASONING_EFFORT": "high",
    "AION_DISABLE_REASONING": "1",
}):
    incompatible = OpenAICompatibleProvider(
        api_key="synthetic", model="x-ai/grok-4-fast:free", free_only=True
    )
    assert incompatible.health()["status"] == "blocked_model"

print("PROVIDER RESILIENCE REGRESSION: PASS")
