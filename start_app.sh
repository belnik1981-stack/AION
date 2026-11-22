#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || exit 1
cd "$SCRIPT_DIR" || exit 1
export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"

# API keys are passed explicitly through the environment; never search files.
if [ -z "${AION_API_KEY:-}" ]; then
    echo "[AION] ERROR: AION_API_KEY is not set"
    echo "[AION] Export the key in the current shell before starting."
    exit 2
fi

export AION_PROVIDER="${AION_PROVIDER:-openai_compatible}"
export AION_API_URL="${AION_API_URL:-https://openrouter.ai/api/v1}"
export AION_MAX_TOKENS="${AION_MAX_TOKENS:-256}"
export AION_FREE_ONLY="${AION_FREE_ONLY:-1}"

if [ -n "${AION_PYTHON:-}" ]; then
    PYTHON_BIN="$AION_PYTHON"
elif [ -x "$HOME/testenv/bin/python" ]; then
    PYTHON_BIN="$HOME/testenv/bin/python"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN=$(command -v python)
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN=$(command -v python3)
else
    echo "[AION] ERROR: Python interpreter not found"
    exit 3
fi

# Check provider configuration locally without making a paid or live API call.
"$PYTHON_BIN" - <<'PY'
from core.llm import llm_status
status = llm_status()
print("[AION] LLM status:", status)
if status.get("status") != "ok":
    raise SystemExit(2)
PY

echo "[AION] API Key Loaded: YES"
echo "[AION] Free-only mode: $AION_FREE_ONLY"
echo "[AION] Model: ${AION_MODEL:-stored profile or openrouter/free}"
echo "[AION] Python: $PYTHON_BIN"
echo "[AION] Web UI: http://localhost:8080"

exec "$PYTHON_BIN" server.py
