#!/usr/bin/env bash
# One-request free-only probe. No automated retries and no changes to Truth.
set -Eeuo pipefail
umask 077
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT"
export AION_PROVIDER=openai_compatible
export AION_API_URL=https://openrouter.ai/api/v1
export AION_FREE_ONLY=1
export AION_MODEL="${AION_MODEL:-openrouter/free}"
export AION_REASONING_EFFORT="${AION_REASONING_EFFORT:-none}"
export AION_EXCLUDE_REASONING=1

if [[ -z "${AION_API_KEY:-}" ]]; then
  echo "[FAIL] No AION_API_KEY. Enter your own key with: read -r -s AION_API_KEY; export AION_API_KEY" >&2
  exit 2
fi
PYTHON_BIN="${AION_PROBE_PYTHON:-python3}"
"$PYTHON_BIN" - <<'PY'
from pathlib import Path
import hashlib
import os
import sys

from core.llm import ask_llm, llm_status
from providers.base import ProviderError, ProviderRateLimitError, ProviderTruncatedError

truth_paths = [Path("knowledge/truth/truth.json"), Path("knowledge/truth/system.yaml")]
before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in truth_paths]
model = os.environ["AION_MODEL"]
tokens = int(os.environ.get("AION_PROBE_TOKENS", "1024"))
if not 128 <= tokens <= 2048:
    raise SystemExit("[FAIL] AION_PROBE_TOKENS should be 128..2048")
print("[PROBE] Single free-only request (no retries). Model:", model, flush=True)
health = llm_status()
if health["status"] != "ok":
    raise SystemExit("[FAIL] Configuration rejected: " + health["status"])
try:
    answer = ask_llm("Вычисли 2+2. Ответь одним символом: 4.", max_tokens=tokens)
except ProviderRateLimitError as exc:
    print("[RATE LIMITED]", str(exc), file=sys.stderr)
    raise SystemExit(29)
except ProviderTruncatedError as exc:
    print("[TRUNCATED]", str(exc), file=sys.stderr)
    raise SystemExit(28)
except ProviderError as exc:
    print("[PROVIDER ERROR]", str(exc), file=sys.stderr)
    raise SystemExit(27)
if answer.strip() != "4":
    print("[FAIL] Provider returned a non-matching or overly verbose answer; not accepted.")
    raise SystemExit(26)
after = [hashlib.sha256(p.read_bytes()).hexdigest() for p in truth_paths]
if before != after:
    raise SystemExit("[FAIL] Truth files changed during the probe")
print("[PASS] LIVE SINGLE-REQUEST PROBE: 4")
print("[PASS] Truth unchanged")
PY
