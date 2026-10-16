"""Choose one currently listed, zero-priced OpenRouter text model for a live trial.

Fail closed: never route to a paid model; no requests to chat/completions here.
No automatic paid or model fallback after the actual pipeline starts.
"""
import json
import os
import re
import sys
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

BASE = "https://openrouter.ai/api/v1"
MODEL_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*/[a-zA-Z0-9][a-zA-Z0-9._:-]{0,100}:free$")
DETAIL_PATH = re.compile(r"^/api/v1/models/[a-zA-Z0-9][a-zA-Z0-9._-]*/[a-zA-Z0-9][a-zA-Z0-9._:-]{0,125}/endpoints$")
MIN_COMPLETION = 3200
MAX_CANDIDATES = 16


def zero_price(pricing):
    """Require explicit zero token rates; optional charges must be zero if present.

    OpenRouter omits uncharged optional pricing fields, including "request",
    on many real :free entries. Their absence is not evidence of a charge.
    """
    if not isinstance(pricing, dict):
        return False
    if "prompt" not in pricing or "completion" not in pricing:
        return False
    for key in ("prompt", "completion", "request", "internal_reasoning"):
        if key not in pricing:
            continue
        try:
            price = Decimal(str(pricing[key]))
            if not price.is_finite() or price != 0:
                return False
        except (InvalidOperation, TypeError, ValueError):
            return False
    return True


def eligible_models(models):
    """Use only free text-producing chat models with sufficient output room."""
    result = []
    for model in models:
        if not isinstance(model, dict):
            continue
        model_id = model.get("id")
        if not isinstance(model_id, str) or not MODEL_ID.fullmatch(model_id):
            continue
        if not zero_price(model.get("pricing")):
            continue
        arch = model.get("architecture")
        if not isinstance(arch, dict) or "text" not in (arch.get("output_modalities") or []):
            continue
        max_context = model.get("context_length")
        if not isinstance(max_context, int) or max_context < 8192:
            continue
        top = model.get("top_provider")
        if not isinstance(top, dict):
            continue
        max_output = top.get("max_completion_tokens")
        if not isinstance(max_output, int) or max_output < MIN_COMPLETION:
            continue
        params = model.get("supported_parameters")
        params = params if isinstance(params, list) else []
        # Prefer models not explicitly advertised as reasoning-capable; this
        # is only a heuristic and cannot guarantee zero internal reasoning.
        supports_reasoning = "reasoning" in params
        created = model.get("created")
        created = created if type(created) is int else 0
        result.append((supports_reasoning, -created, -max_output, model_id))
    return [item[3] for item in sorted(result)]


def endpoint_url(model):
    """Use a verified, catalog-provided endpoint path (often the canonical slug).

    Never accept an absolute URL or arbitrary path from provider metadata.
    """
    links = model.get("links")
    details = links.get("details") if isinstance(links, dict) else None
    if isinstance(details, str) and DETAIL_PATH.fullmatch(details):
        return BASE + details
    model_id = model["id"]
    author, slug = model_id.split("/", 1)
    return (BASE + "/models/" + quote(author, safe="") + "/" +
            quote(slug, safe=":") + "/endpoints")


def endpoints_present(payload):
    data = payload.get("data") if isinstance(payload, dict) else None
    endpoints = data.get("endpoints") if isinstance(data, dict) else None
    if not isinstance(endpoints, list) or not endpoints:
        return False
    for endpoint in endpoints:
        if not isinstance(endpoint, dict):
            continue
        price = endpoint.get("pricing")
        # When an endpoint supplies a pricing object, require that its
        # text prices are also known to be zero.
        if price is not None and not zero_price(price):
            continue
        return True
    return False


def fetch_json(url, key):
    req = Request(url, headers={"Authorization": "Bearer " + key,
                                "Accept": "application/json"})
    with urlopen(req, timeout=20) as response:
        content = response.read(8 * 1024 * 1024 + 1)
    if len(content) > 8 * 1024 * 1024:
        raise ValueError("API model list exceeded safe size limit")
    return json.loads(content.decode("utf-8"))


def catalog_selection(key, requested=None):
    data = fetch_json(BASE + "/models", key)
    models = data.get("data") if isinstance(data, dict) else None
    if not isinstance(models, list):
        raise ValueError("OpenRouter model catalog has unexpected format")
    candidates = eligible_models(models)
    model_by_id = {item.get("id"): item for item in models
                   if isinstance(item, dict) and isinstance(item.get("id"), str)}
    if requested and requested != "openrouter/free":
        if requested not in candidates:
            raise ValueError(
                "Requested model is absent from the current zero-priced text model list "
                "or lacks adequate output-token metadata"
            )
        candidates = [requested]
    elif not candidates:
        raise ValueError("No zero-priced eligible text model found in current catalog")

    for candidate in candidates[:MAX_CANDIDATES]:
        url = endpoint_url(model_by_id[candidate])
        try:
            result = fetch_json(url, key)
        except HTTPError as exc:
            if exc.code == 404:
                continue  # Catalog can list stale model variants
            raise
        if endpoints_present(result):
            return candidate
    raise ValueError("No currently advertised free text model has a usable endpoint")


def main():
    key = os.getenv("AION_API_KEY", "")
    if not key:
        print("[FAIL] AION_API_KEY is missing from current shell.", file=sys.stderr)
        return 2
    requested = os.getenv("AION_MODEL") or None
    try:
        selected = catalog_selection(key, requested)
    except HTTPError as exc:
        print("[FAIL] OpenRouter model catalog HTTP " + str(exc.code) +
              "; no model was selected.", file=sys.stderr)
        return 1
    except (URLError, TimeoutError, ValueError, KeyError, TypeError) as exc:
        # Never print untrusted API error bodies (could include account data).
        print("[FAIL] No verified available free model: " +
              (str(exc) if isinstance(exc, ValueError) else "catalog network/format error"),
              file=sys.stderr)
        return 1
    print(selected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
