"""Bounded two-model live comparison on explicitly selected, free-only models.

Reuse the proven single-model readiness probe and catalog selector. Never
interpret a model's verdict or agreement as independently verified truth.
"""
import hashlib
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError

from core.pipeline import run_pipeline
from providers.base import ProviderError, ProviderHTTPError, ProviderRateLimitError, ProviderTruncatedError
from tools.live_free_pipeline_trial import _probe, _hash_truth
from tools.select_free_openrouter_model import catalog_candidates


MAX_PREFLIGHT_CANDIDATES = 5
PREFLIGHT_RECOVERABLE = frozenset({400, 404, 502, 503})
TEST_TASK = (
    "Сравни два объяснения и сохрани неопределённость: "
    "почему наблюдаемое совпадение само по себе не доказывает причинную связь?"
)


def _author(model_id):
    return model_id.split("/", 1)[0]


def _candidate_models(catalog, requested=None):
    """Preserve explicit IDs. For automatic selection prefer different authors.

    Catalog eligibility is necessary, but different publisher names and IDs
    alone do not prove truly independent training or external factual support.
    """
    if requested:
        named = [part.strip() for part in requested.split(",")]
        if (len(named) != 2 or any(not m or m == "openrouter/free" for m in named)
                or len(set(named)) != 2 or len({_author(m) for m in named}) != 2):
            raise ValueError("Specify exactly two distinct explicit :free model IDs from different authors")
        missing = [m for m in named if m not in catalog]
        if missing:
            raise ValueError("At least one requested model fails current free-model catalog eligibility")
        return named

    # Use prior successful live ID if still eligible, not regardless of catalog.
    known_success = "dots-studio/dots-3-note-preview:free"
    ordering = [known_success] + [m for m in catalog if m != known_success] if known_success in catalog else list(catalog)
    return ordering[:MAX_PREFLIGHT_CANDIDATES]


def _find_two_responsive(candidates, explicit=False, probe=None):
    probe = probe or _probe
    selected = []
    for mid in candidates:
        if len(selected) == 2:
            break
        if _author(mid) in {_author(other) for other in selected}:
            continue
        print("[PREFLIGHT]", mid, flush=True)
        try:
            probe(mid)
        except ProviderRateLimitError:
            print("[FAIL] HTTP 429: stop without additional model requests.", flush=True)
            return None
        except ProviderTruncatedError:
            print("[PREFLIGHT] Incomplete response rejected.", flush=True)
            if explicit:
                return None
            continue
        except ProviderHTTPError as exc:
            print("[PREFLIGHT] Provider HTTP", exc.status_code, flush=True)
            if explicit or exc.status_code not in PREFLIGHT_RECOVERABLE:
                return None
            continue
        except ProviderError:
            print("[FAIL] Provider rejected preflight; no further requests.", flush=True)
            return None
        selected.append(mid)
        print("[PASS] Model returned complete preflight:", mid, flush=True)

    if len(selected) != 2:
        print("[FAIL] Two distinct responsive free models not established.", flush=True)
        return None
    return selected


def _safe_preview(value):
    # The trial uses a fixed public prompt, but don't disclose more than a
    # brief response excerpt. Control chars and log delimiters are escaped.
    compact = " ".join(str(value).split())
    return compact[:350]


def execute():
    before = _hash_truth()
    try:
        key = os.getenv("AION_API_KEY", "")
        if not key:
            print("[FAIL] Provider credentials absent.", flush=True)
            return 2
        requested = os.getenv("AION_MODELS", "").strip()
        if requested == "openrouter/free":
            requested = ""
        # Hard restrictions apply even if the launcher environment is changed.
        os.environ["AION_FREE_ONLY"] = "1"
        os.environ["AION_PROVIDER"] = "openai_compatible"
        os.environ["AION_API_URL"] = "https://openrouter.ai/api/v1"
        os.environ["AION_REASONING_EFFORT"] = "none"
        os.environ["AION_MULTI_TEST_ROUNDS"] = "1"
        print("[CATALOG] Verifying two free models before role execution.", flush=True)
        try:
            catalog = catalog_candidates(key)
            candidates = _candidate_models(catalog, requested=requested)
        except HTTPError as exc:
            print("[FAIL] Catalog HTTP", exc.code, flush=True)
            return 2
        except (URLError, TimeoutError, ValueError, KeyError, TypeError):
            print("[FAIL] Two free models cannot be verified from catalog.", flush=True)
            return 2
        print("[CATALOG] Eligible free models:", len(catalog), flush=True)
        two = _find_two_responsive(candidates, explicit=bool(requested))
        if two is None:
            print("[FAIL] MULTI PREFLIGHT; pipeline not started.", flush=True)
            return 4
        # The isolated preflight can set AION_MODEL and model-specific reasoning
        # flags. Clear them before model-explicit multi-role calls.
        os.environ["AION_MODEL"] = two[0]
        os.environ["AION_DISABLE_REASONING"] = "0"
        os.environ["AION_MODELS"] = ",".join(two)
        print("[PASS] TWO DISTINCT MODEL IDS:", ", ".join(two), flush=True)
        print("[MODE] Separate initial answers; one maximum comparison round.", flush=True)
        result = run_pipeline(TEST_TASK)
        if not isinstance(result, dict):
            print("[FAIL] Pipeline returned invalid result.", flush=True)
            return 1
        if (result.get("mode") != "multi_model_role_rotation"
                or result.get("independent_model_count") != 2
                or result.get("models") != two
                or result.get("model_ids_distinct") is not True
                or len(result.get("raw_answers", {})) != 2):
            print("[FAIL] Model independence contract not met.", flush=True)
            print("[STATUS]", result.get("status", "unknown"), flush=True)
            print("[STAGE]", result.get("stage", "model_contract"), flush=True)
            return 1
        raw = result["raw_answers"]
        if any(not isinstance(raw.get(mid), str) or raw[mid].startswith("[ОШИБКА")
               or not raw[mid].strip() for mid in two):
            print("[FAIL] One initial answer is missing or rejected.", flush=True)
            return 1
        for i, mid in enumerate(two, 1):
            print("[RAW MODEL", i, "]", mid, flush=True)
            print("[RAW EXCERPT]", _safe_preview(raw[mid]), flush=True)
        print("[RAW TEXTS IDENTICAL]", raw[two[0]].strip() == raw[two[1]].strip(), flush=True)
        print("[VERIFICATION]", result.get("verification_scope"), flush=True)
        print("[TRUTH VERIFIED]", result.get("truth_verified"), flush=True)
        if (result.get("status") != "ok"
                or not isinstance(result.get("final_answer"), str)
                or not result["final_answer"].strip()
                or result.get("truth_verified") is not False
                or result.get("verification_scope") != "llm_review_only"):
            print("[FAIL] MULTI MODEL PIPELINE", flush=True)
            print("[STATUS]", result.get("status", "missing"), flush=True)
            print("[STAGE]", result.get("stage", "verification_or_rotation"), flush=True)
            print("[ROUNDS]", result.get("rotations_used", 0), flush=True)
            return 1
        print("[PASS] MULTI MODEL PIPELINE", flush=True)
        print("[NOTE] This confirms LLM review, NOT objective truth.", flush=True)
        return 0
    finally:
        after = _hash_truth()
        if before != after:
            print("[FAIL] Truth modified during multi-model live test.", file=sys.stderr)
            raise SystemExit(3)
        print("[PASS] Truth unchanged", flush=True)


if __name__ == "__main__":
    raise SystemExit(execute())
