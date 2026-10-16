"""Choose a zero-priced OpenRouter text model advertised in the current catalog.

Model catalog metadata can establish declared pricing, but NOT live provider
availability. Never treat /models/{author}/{slug}/endpoints as a required
preflight: this separate API may be empty, restricted or 404 while the model
is listed. A real lightweight chat call checks availability in the launcher.
"""
import json
import os
import re
import sys
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE = "https://openrouter.ai/api/v1"
MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._:-]{0,100}:free$")
MIN_COMPLETION = 3200


def zero_price(pricing):
    """Require zero input/output cost and reject any declared relevant charge.

    Additional charges are optional fields in actual /models responses.
    Treat omitted fields as not charged, never a nonzero charge as free.
    """
    if not isinstance(pricing, dict):
        return False
    if "prompt" not in pricing or "completion" not in pricing:
        return False
    relevant = {
        "prompt", "completion", "request", "internal_reasoning",
        "input_cache_read", "input_cache_write", "input_cache_write_1h",
    }
    def is_zero(value):
        try:
            n = Decimal(str(value))
            return n.is_finite() and n == 0
        except (InvalidOperation, TypeError, ValueError):
            return False
    for key in relevant:
        if key in pricing and not is_zero(pricing[key]):
            return False
    overrides = pricing.get("overrides", [])
    if not isinstance(overrides, list):
        return False
    for item in overrides:
        if not isinstance(item, dict):
            return False
        for key in relevant:
            if key in item and not is_zero(item[key]):
                return False
    return True


def eligible_models(models, today=None):
    """Filter true :free text models, then prefer those not requiring reasoning."""
    today = today or date.today()
    choices = []
    for entry in models:
        if not isinstance(entry, dict):
            continue
        mid = entry.get("id")
        if not isinstance(mid, str) or not MODEL_ID.fullmatch(mid):
            continue
        if not zero_price(entry.get("pricing")):
            continue
        arch = entry.get("architecture")
        if not isinstance(arch, dict) or "text" not in (arch.get("output_modalities") or []):
            continue
        if "text" not in (arch.get("input_modalities") or []):
            continue
        context = entry.get("context_length")
        if type(context) is not int or context < 8192:
            continue
        top = entry.get("top_provider")
        completion = top.get("max_completion_tokens") if isinstance(top, dict) else None
        if type(completion) is not int or completion < MIN_COMPLETION:
            continue
        expiry = entry.get("expiration_date")
        if expiry:
            try:
                if date.fromisoformat(expiry) < today:
                    continue
            except (TypeError, ValueError):
                continue
        reasoning = entry.get("reasoning")
        reasoning = reasoning if isinstance(reasoning, dict) else {}
        mandatory = reasoning.get("mandatory") is True
        default_enabled = reasoning.get("default_enabled") is True
        created = entry.get("created")
        created = created if type(created) is int else 0
        choices.append((mandatory, default_enabled, -created, -completion, mid))
    return [item[4] for item in sorted(choices)]


def fetch_json(url, api_key):
    req = Request(url, headers={
        "Authorization": "Bearer " + api_key,
        "Accept": "application/json",
    })
    with urlopen(req, timeout=20) as response:
        raw = response.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("OpenRouter catalog response exceeded size limit")
    return json.loads(raw.decode("utf-8"))


def catalog_selection(key, requested=None, fetcher=None):
    fetcher = fetcher or fetch_json
    payload = fetcher(BASE + "/models", key)
    entries = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        raise ValueError("OpenRouter model catalog has unexpected format")
    candidates = eligible_models(entries)
    if requested and requested != "openrouter/free":
        if requested not in candidates:
            raise ValueError("Requested model is not an eligible zero-priced text model")
        return requested
    if not candidates:
        raise ValueError("No eligible zero-priced text model found in current catalog")
    return candidates[0]


def main():
    key = os.getenv("AION_API_KEY", "")
    if not key:
        print("[FAIL] AION_API_KEY is missing from current shell.", file=sys.stderr)
        return 2
    try:
        choice = catalog_selection(key, os.getenv("AION_MODEL") or None)
    except HTTPError as exc:
        print(f"[FAIL] Catalog HTTP {exc.code}; model could not be selected.", file=sys.stderr)
        return 1
    except (URLError, TimeoutError, ValueError, KeyError, TypeError):
        print("[FAIL] Catalog could not establish an eligible free model. No LLM called.",
              file=sys.stderr)
        return 1
    print(choice)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
