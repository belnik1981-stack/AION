#!/usr/bin/env bash
# Check Critic with real OpenRouter free model(s), without running all offline trials.
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
  echo "[FAIL] AION_API_KEY is not set in the current Termux session." >&2
  exit 2
fi

PYTHON_BIN="${AION_PROBE_PYTHON:-python3}"
"$PYTHON_BIN" - <<'PY'
import hashlib
import os
import sys
from pathlib import Path

from core.agents import ROLE_BUDGETS, _ceiling, critic

truth_paths = [Path("knowledge/truth/truth.json"), Path("knowledge/truth/system.yaml")]
before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in truth_paths]
print(
    "[PROBE] Critic with free model: ",
    os.environ["AION_MODEL"],
    "; tokens: ",
    ROLE_BUDGETS["critic"](),
    "; retry ceiling: ",
    _ceiling(),
    sep="",
    flush=True,
)
try:
    result = critic(
        "Проверь утверждение 2+2=4.",
        "Сверить арифметику без предположений.",
        "Факт: 2+2=4. Это проверяется сложением двух пар единиц.",
        model=os.environ["AION_MODEL"],
    )
    if result.startswith("[ОШИБКА"):
        print("[FAIL] Critic provider failure:", result[:600], file=sys.stderr)
        raise SystemExit(1)
    if result.strip().upper() != "OK":
        print("[FAIL] Critic did not return the required exact OK verdict.")
        print("[PROBE RESULT]", result[:500])
        raise SystemExit(2)
    print("[PASS] LIVE CRITIC PROBE: OK")
finally:
    after = [hashlib.sha256(p.read_bytes()).hexdigest() for p in truth_paths]
    if before != after:
        print("[FAIL] Truth modified during Critic probe", file=sys.stderr)
        raise SystemExit(3)
    print("[PASS] Truth unchanged")
PY
