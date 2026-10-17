"""Bounded live AION trial: catalog eligibility, provider reachability, pipeline.

The first preflight is one actual LLM request; if it fails with a model-specific
404/400, truncated output, or temporary 502/503, try at most one other vetted
:free catalog model. Never retry 429, auth failures, or pipeline stage failures.
Do not use the OpenRouter SDK's automatic retry machinery here: AION's 429
and free-only policies have different semantics.
"""
import hashlib
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError

from core.llm import ask_llm, llm_status
from core.pipeline import run_pipeline
from providers.base import ProviderError, ProviderHTTPError, ProviderRateLimitError, ProviderTruncatedError
from tools.select_free_openrouter_model import catalog_candidates


TRUTH_PATHS = (
    Path("knowledge/truth/truth.json"),
    Path("knowledge/truth/system.yaml"),
)
MAX_LIVE_PREFLIGHT_MODELS = 2
PREFLIGHT_REPLACEABLE_HTTP = frozenset({400, 404, 502, 503})


def _hash_truth():
    return tuple(hashlib.sha256(p.read_bytes()).hexdigest() for p in TRUTH_PATHS)


def _probe(model):
    """Check actual single-model reachability, never assume catalog == availability."""
    os.environ["AION_MODEL"] = model
    os.environ["AION_DISABLE_REASONING"] = (
        "1" if model == "x-ai/grok-4-fast:free" else "0"
    )
    status = llm_status()
    if status.get("status") != "ok" or status.get("free_only") is not True:
        raise ProviderError("Selected model did not pass the free-only configuration check")
    reply = ask_llm("Вычисли 2+2, ответь кратко.", max_tokens=1024)
    if not isinstance(reply, str) or not reply.strip():
        raise ProviderError("Free model returned an empty response")
    return model


def _select_live_model(candidates, explicit=False):
    checked = 0
    allowed = candidates[:1] if explicit else candidates[:MAX_LIVE_PREFLIGHT_MODELS]
    for mid in allowed:
        checked += 1
        print("[PREFLIGHT]", mid, flush=True)
        try:
            return _probe(mid)
        except ProviderRateLimitError as exc:
            print("[FAIL] RATE LIMIT; no automatic retry:", str(exc)[:350], flush=True)
            return None
        except ProviderTruncatedError:
            # Retry *a different catalog-verified model*, never same model.
            print("[PREFLIGHT] Truncated output rejected.", flush=True)
        except ProviderHTTPError as exc:
            print("[PREFLIGHT] Provider HTTP", exc.status_code, flush=True)
            if exc.status_code not in PREFLIGHT_REPLACEABLE_HTTP:
                return None
        except ProviderError:
            # Do not guess whether other errors concern access, billing or security.
            print("[FAIL] Provider rejected preflight; no further retries.", flush=True)
            return None
    print("[FAIL] No responsive model among", checked, "verified free candidates.", flush=True)
    return None


def execute():
    before = _hash_truth()
    try:
        if not os.environ.get("AION_API_KEY"):
            print("[FAIL] Provider credentials absent.", flush=True)
            return 2
        requested = os.environ.get("AION_MODEL", "openrouter/free")
        print("[CATALOG] Checking currently eligible zero-priced models.", flush=True)
        try:
            candidates = catalog_candidates(os.environ["AION_API_KEY"], requested=requested)
        except HTTPError as exc:
            print("[FAIL] Catalog HTTP", exc.code, flush=True)
            return 2
        except (URLError, TimeoutError, ValueError, KeyError, TypeError):
            print("[FAIL] Catalog cannot verify free-model eligibility.", flush=True)
            return 2
        print("[CATALOG] Verified free candidates:", len(candidates), flush=True)
        explicit = requested not in ("openrouter/free", "")
        chosen = _select_live_model(candidates, explicit=explicit)
        if chosen is None:
            print("[FAIL] LIVE PREFLIGHT; full pipeline not started.", flush=True)
            return 4
        print("[PASS] LIVE PREFLIGHT; pinned model:", chosen, flush=True)
        result = run_pipeline(
            "Кратко раздели факт, гипотезу и неизвестное: "
            "вода при нормальном атмосферном давлении замерзает примерно при 0 °C."
        )
        if not isinstance(result, dict):
            print("[FAIL] Invalid pipeline result.", flush=True)
            return 1
        if (result.get("status") != "ok" or result.get("mode") != "single_model"
                or not isinstance(result.get("final_answer"), str)
                or not result["final_answer"].strip()):
            print("[FAIL] LIVE PINNED PIPELINE", flush=True)
            print("[STATUS]", result.get("status", "missing"), flush=True)
            if result.get("stage"):
                print("[STAGE]", result["stage"], flush=True)
            if result.get("detail"):
                print("[DETAIL]", str(result["detail"])[:700], flush=True)
            return 1
        print("[PASS] LIVE PINNED SINGLE-MODEL PIPELINE", flush=True)
        return 0
    finally:
        try:
            after = _hash_truth()
            if before != after:
                print("[FAIL] Truth changed during live test", file=sys.stderr)
                raise SystemExit(3)
            print("[PASS] Truth unchanged", flush=True)
        except OSError:
            print("[FAIL] Truth is unreadable after test", file=sys.stderr)
            raise SystemExit(3)


if __name__ == "__main__":
    raise SystemExit(execute())
