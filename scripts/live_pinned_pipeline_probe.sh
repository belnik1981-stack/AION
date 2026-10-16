#!/usr/bin/env bash
# Real single-model pipeline smoke without replaying all offline fixtures.
# Free-only, one selected model for every role, no paid fallback.
set -Eeuo pipefail
umask 077
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT"
export AION_PROVIDER=openai_compatible
export AION_API_URL=https://openrouter.ai/api/v1
export AION_FREE_ONLY=1
export AION_REASONING_EFFORT=none
export AION_EXCLUDE_REASONING=1
unset AION_MODELS
if [[ -z "${AION_API_KEY:-}" ]]; then
  echo "[FAIL] AION_API_KEY missing in this Termux session; enter it privately." >&2
  exit 2
fi

PYTHON_BIN="${AION_PROBE_PYTHON:-python3}"
# Catalog metadata verifies declared free pricing, NOT current availability.
# One tiny real provider call below verifies reachability before the full
# pipeline. Never fall back to a paid model or automatically retry HTTP 429.
# AION_MODEL=...:free remains a user-requested exact choice; openrouter/free
# or unset asks the catalog selector to pin one declared-free candidate.
SELECTED_MODEL="$("$PYTHON_BIN" tools/select_free_openrouter_model.py)" || {
  echo "[FAIL] Catalog selection failed; no live requests were made." >&2
  exit 2
}
export AION_MODEL="$SELECTED_MODEL"
# Only the documented Grok model may receive reasoning.enabled=false.
# Other chosen models keep provider defaults; avoiding auto-router randomness
# does not ensure they can finish within a particular output budget.
if [[ "$AION_MODEL" == "x-ai/grok-4-fast:free" ]]; then
  export AION_DISABLE_REASONING=1
else
  export AION_DISABLE_REASONING=0
fi
echo "[CATALOG] Declared-free model selected (availability not yet checked): $AION_MODEL"
"$PYTHON_BIN" - <<'PY'
import hashlib
import os
import sys
from pathlib import Path

from core.llm import ask_llm, llm_status
from core.pipeline import run_pipeline
from providers.base import ProviderError

paths = [Path("knowledge/truth/truth.json"), Path("knowledge/truth/system.yaml")]
before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
model = os.environ["AION_MODEL"]
print("[MODEL] Pinned free model:", model, flush=True)
print("[MODEL] Explicit non-reasoning requested:", os.environ["AION_DISABLE_REASONING"], flush=True)
result = None
try:
    config = llm_status()
    if config.get("status") != "ok" or not config.get("free_only"):
        print("[FAIL] Free-only model configuration not accepted.", flush=True)
        raise SystemExit(2)
    # An actual one-call readiness test; catalog metadata is not availability.
    print("[LIVE PREFLIGHT] One free-only request before full pipeline.", flush=True)
    try:
        reply = ask_llm("Вычисли 2+2. Ответь кратко.", max_tokens=1024)
    except ProviderError as exc:
        print("[FAIL] LIVE PREFLIGHT: provider rejected the selected model.", flush=True)
        print("[DETAIL]", str(exc)[:900], flush=True)
        raise SystemExit(4)
    if not isinstance(reply, str) or not reply.strip():
        print("[FAIL] LIVE PREFLIGHT: empty provider response.", flush=True)
        raise SystemExit(4)
    print("[PASS] LIVE PREFLIGHT: model returned a complete response.", flush=True)
    result = run_pipeline(
        "Кратко раздели факт, гипотезу и неизвестное: "
        "вода при нормальном атмосферном давлении замерзает примерно при 0 °C."
    )
    status = result.get("status")
    if status != "ok" or result.get("mode") != "single_model" or not (result.get("final_answer") or "").strip():
        print("[FAIL] LIVE PINNED PIPELINE", flush=True)
        print("[STATUS]", status, flush=True)
        if result.get("stage"):
            print("[STAGE]", result["stage"], flush=True)
        if result.get("detail"):
            # Provider errors have already been sanitized; avoid exposing prompts.
            print("[DETAIL]", str(result["detail"])[:1000], flush=True)
        raise SystemExit(1)
    print("[PASS] LIVE PINNED SINGLE-MODEL PIPELINE", flush=True)
    print("[STATUS] ok; accepted answer is nonempty.", flush=True)
finally:
    after = [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
    if before != after:
        print("[FAIL] Truth modified during live pipeline", file=sys.stderr)
        raise SystemExit(3)
    print("[PASS] Truth unchanged", flush=True)
PY
