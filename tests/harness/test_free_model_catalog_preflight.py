"""OpenRouter live-model selector: deterministic offline regression with no network."""
from unittest.mock import patch
from urllib.error import HTTPError

from tools import select_free_openrouter_model as picker


def model(identifier, *, prompt="0", completion="0", request="0",
          text=True, max_tokens=8192, created=100):
    return {
        "id": identifier,
        "pricing": {"prompt": prompt, "completion": completion, "request": request},
        "architecture": {"output_modalities": ["text"] if text else ["image"]},
        "context_length": 32000,
        "top_provider": {"max_completion_tokens": max_tokens},
        "supported_parameters": ["max_tokens"],
        "created": created,
    }


valid = model("supplier/active-model:free", created=50)
valid["links"] = {"details": "/api/v1/models/supplier/active-model-revision/endpoints"}
stale = model("supplier/stale-model:free", created=100)
paid = model("supplier/charged-model:free", completion="0.01")
nonfree = model("supplier/paid-model", prompt="0")
no_request_pricing = model("supplier/unspecified:free")
del no_request_pricing["pricing"]["request"]
nontext = model("supplier/image-model:free", text=False)
too_small = model("supplier/small-model:free", max_tokens=1000)

catalog = [paid, nonfree, nontext, too_small, valid, stale]
candidates = picker.eligible_models(catalog)
assert candidates == ["supplier/stale-model:free", "supplier/active-model:free"], candidates
assert picker.zero_price(valid["pricing"])
assert not picker.zero_price(paid["pricing"])
assert picker.zero_price(no_request_pricing["pricing"])
assert picker.eligible_models([no_request_pricing]) == ["supplier/unspecified:free"]
assert not picker.zero_price({"prompt": "0", "completion": "0", "request": "0.0001"})
assert not picker.zero_price({"prompt": "0", "completion": "0", "internal_reasoning": "0.001"})
assert not picker.zero_price({"prompt": "0"})
assert picker.endpoint_url(valid) == picker.BASE + "/models/supplier/active-model-revision/endpoints"
invalid_link = model("supplier/active-model:free")
invalid_link["links"] = {"details": "https://evil.example/api/v1/models/anything/endpoints"}
assert picker.endpoint_url(invalid_link) == picker.BASE + "/models/supplier/active-model:free/endpoints"
assert not picker.zero_price({"prompt": "NaN", "completion": "0", "request": "0"})
assert not picker.zero_price({"prompt": "-0.01", "completion": "0", "request": "0"})

calls = []
def mock_fetch(url, key):
    calls.append(url)
    assert key == "mock-private-key"
    if url.endswith("/models"):
        return {"data": catalog}
    if "stale-model" in url:
        raise HTTPError(url, 404, "Not Found", {}, None)
    if "active-model-revision" in url:
        return {"data": {"endpoints": [{"name": "free endpoint",
                                        "pricing": {"prompt": "0", "completion": "0"}}]}}
    raise AssertionError("No other model may be considered: " + url)

with patch.object(picker, "fetch_json", mock_fetch):
    chosen = picker.catalog_selection("mock-private-key")
assert chosen == "supplier/active-model:free", chosen
assert len(calls) == 3, calls
assert not any("/chat/" in call for call in calls)

with patch.object(picker, "fetch_json", mock_fetch):
    chosen = picker.catalog_selection("mock-private-key", "supplier/active-model:free")
assert chosen == "supplier/active-model:free"
try:
    with patch.object(picker, "fetch_json", mock_fetch):
        picker.catalog_selection("mock-private-key", "supplier/charged-model:free")
except ValueError:
    pass
else:
    raise AssertionError("Must reject paid or unlisted explicit model")
try:
    with patch.object(picker, "fetch_json", mock_fetch):
        picker.catalog_selection("mock-private-key", "x-ai/grok-4-fast:free")
except ValueError:
    pass
else:
    raise AssertionError("Must reject stale explicit ID absent from current catalog")

assert not picker.endpoints_present({"data": {"endpoints": []}})
assert not picker.endpoints_present({"data": {"endpoints": [{"pricing": {
    "prompt": "0", "completion": "0.12", "request": "0"}}]}})
assert picker.endpoints_present({"data": {"endpoints": [{"name": "endpoint"}]}})
assert not picker.endpoints_present({"unexpected": True})
assert picker.endpoints_present({"data": {"endpoints": [{"pricing": {"prompt": "0", "completion": "0"}}]}})
assert not picker.endpoints_present({"data": {"endpoints": [{"pricing": {
    "prompt": "0", "completion": "0", "internal_reasoning": "1"}}]}})

print("FREE MODEL CATALOG PREFLIGHT: PASS")
