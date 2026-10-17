"""Keyless contract check against the ACTUAL public OpenRouter model catalog.

No chat/completions calls, no user credentials, and no cost.
Verifies real model/pricing/architecture schema—not only artificial fixtures.
"""
import json
from tools.select_free_openrouter_model import BASE, catalog_candidates, fetch_json, zero_price

data = fetch_json(BASE + "/models", "")
models = data.get("data") if isinstance(data, dict) else None
assert isinstance(models, list) and models, "Real OpenRouter /models must return a populated data list"

candidates = catalog_candidates("", fetcher=lambda url, key: data)
assert candidates, "No zero-priced text-capable free models in the public catalog"
by_id = {m.get("id"): m for m in models if isinstance(m, dict) and isinstance(m.get("id"), str)}
for model_id in candidates:
    assert model_id.endswith(":free"), model_id
    assert model_id in by_id and zero_price(by_id[model_id]["pricing"]), model_id

print("[PASS] REAL OPENROUTER PUBLIC CATALOG CONTRACT")
print("[CATALOG] records:", len(models), "eligible free text models:", len(candidates))
print("[CATALOG] first declared-free model:", candidates[0])
