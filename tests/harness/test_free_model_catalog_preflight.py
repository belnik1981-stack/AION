"""Catalog schema regression, based on real OpenRouter /api/v1/models fields.

No network. This intentionally models free variants whose links.details can
return 404/empty, so the launcher must not depend on the endpoints API.
"""
from datetime import date
from urllib.error import HTTPError
from tools import select_free_openrouter_model as picker


def entry(mid, *, prompt="0", completion="0", request=None, created=100,
          mandatory=False, default_enabled=False, expires=None,
          text=True, max_output=32768):
    prices = {"prompt": prompt, "completion": completion}
    if request is not None:
        prices["request"] = request
    return {
        "id": mid,
        "canonical_slug": mid.removesuffix(":free") + "-20261001",
        "architecture": {
            "input_modalities": ["text"],
            "output_modalities": ["text"] if text else ["image"],
        },
        "pricing": prices,
        "context_length": 262144,
        "top_provider": {"max_completion_tokens": max_output},
        "reasoning": {"mandatory": mandatory, "default_enabled": default_enabled},
        "links": {"details": "/api/v1/models/example/not-public-free-variant/endpoints"},
        "expiration_date": expires,
        "created": created,
    }


# Shape mirrors the October 2026 public catalog entry:
# apodex/apodex-1.1-mini:free has 0/0 prompt/completion prices,
# no 'request' price, canonical_slug and links.details (not chat status).
real_shape = entry("apodex/apodex-1.1-mini:free", created=1790875335,
                   max_output=235929)
real_shape["canonical_slug"] = "apodex/apodex-1.1-mini-20261001"
real_shape["links"] = {
    "details": "/api/v1/models/apodex/apodex-1.1-mini-20261001/endpoints"
}
assert picker.zero_price(real_shape["pricing"])
assert picker.eligible_models([real_shape], today=date(2026, 10, 17)) == [
    "apodex/apodex-1.1-mini:free"
]

bad_paid = entry("vendor/paid:free", completion="0.0002")
bad_surcharge = entry("vendor/surcharge:free", request="0.001")
bad_reasoning_cost = entry("vendor/reasoning-paid:free")
bad_reasoning_cost["pricing"]["internal_reasoning"] = "0.01"
bad_cache_cost = entry("vendor/cache-paid:free")
bad_cache_cost["pricing"]["input_cache_read"] = "0.01"
bad_override = entry("vendor/override-paid:free")
bad_override["pricing"]["overrides"] = [{"min_prompt_tokens": 999, "completion": "0.03"}]
bad_old = entry("vendor/expired:free", expires="2026-10-01")
bad_nonfree = entry("vendor/paid", prompt="0")
bad_nontext = entry("vendor/image:free", text=False)
bad_small = entry("vendor/small:free", max_output=512)
valid_nonreasoning = entry("vendor/nonreasoning:free", created=10)
valid_reasoning = entry("vendor/mandatory:free", mandatory=True, created=300)
valid_free = [real_shape, valid_nonreasoning, valid_reasoning]

candidates = picker.eligible_models(valid_free + [
    bad_paid, bad_surcharge, bad_reasoning_cost, bad_cache_cost,
    bad_override, bad_old, bad_nonfree, bad_nontext, bad_small
], today=date(2026, 10, 17))
assert candidates == [
    "apodex/apodex-1.1-mini:free",
    "vendor/nonreasoning:free",
    "vendor/mandatory:free",
], candidates
assert not picker.zero_price({"prompt": "0"})
assert not picker.zero_price({"prompt": "NaN", "completion": "0"})
assert not picker.zero_price({"prompt": "-0.1", "completion": "0"})
assert picker.zero_price({"prompt": "0", "completion": "0"})
assert picker.zero_price({"prompt": "0", "completion": "0", "request": "0"})
assert not picker.zero_price({"prompt": "0", "completion": "0", "overrides": "bad"})


calls = []
def mock_fetch(url, key):
    calls.append(url)
    assert key == "synthetic-test-key"
    if url == picker.BASE + "/models/user":
        return {"data": valid_free}
    raise AssertionError("Endpoint lookup must never determine model availability: " + url)


selected = picker.catalog_selection("synthetic-test-key", fetcher=mock_fetch)
assert selected == "apodex/apodex-1.1-mini:free", selected
assert calls == [picker.BASE + "/models/user"], calls

calls.clear()
selected = picker.catalog_selection(
    "synthetic-test-key", requested="vendor/mandatory:free",
    fetcher=mock_fetch
)
assert selected == "vendor/mandatory:free"
assert calls == [picker.BASE + "/models/user"], calls

# Authenticated catalog reflects model restrictions. Only unsupported route
# (HTTP 404) permits a fallback to the global public model catalog.
fallback_calls = []
def fallback_fetch(url, key):
    fallback_calls.append(url)
    if url == picker.BASE + "/models/user":
        raise HTTPError(url, 404, "not available", {}, None)
    if url == picker.BASE + "/models":
        return {"data": valid_free}
    raise AssertionError(url)
assert picker.catalog_selection("synthetic-test-key", fetcher=fallback_fetch) == "apodex/apodex-1.1-mini:free"
assert fallback_calls == [picker.BASE + "/models/user", picker.BASE + "/models"]

for code in (401, 403, 429):
    calls_for_failure = []
    def denied(url, key):
        calls_for_failure.append(url)
        raise HTTPError(url, code, "auth/limit error", {}, None)
    try:
        picker.catalog_selection("synthetic-test-key", fetcher=denied)
    except HTTPError as exc:
        assert exc.code == code
    else:
        raise AssertionError("Account errors must not select a public model")
    assert calls_for_failure == [picker.BASE + "/models/user"], calls_for_failure

for wrong in ("vendor/paid", "vendor/missing:free", "openai/gpt-6-luna"):
    try:
        picker.catalog_selection("synthetic-test-key", requested=wrong, fetcher=mock_fetch)
    except ValueError:
        pass
    else:
        raise AssertionError("Explicit paid or unavailable model accepted: " + wrong)

try:
    picker.catalog_selection("synthetic-test-key", fetcher=lambda url, key: {"data": []})
except ValueError:
    pass
else:
    raise AssertionError("Empty catalog must fail closed")

print("FREE MODEL CATALOG PREFLIGHT: PASS")
