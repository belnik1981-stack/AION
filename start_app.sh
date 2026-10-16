#!/bin/sh

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || exit 1
cd "$SCRIPT_DIR" || exit 1
export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"

if [ -z "$AION_API_KEY" ]; then
    echo "[AION] ERROR: AION_API_KEY is not set"
    echo "[AION] Export it in the current shell before starting AION."
    exit 2
set -eu
cd ~/AION
export PYTHONPATH=.

# Не ищем API-ключ по домашней папке. Он должен быть явно передан
# через окружение текущей сессии Termux.
if [ -z "${AION_API_KEY:-}" ]; then
    echo "[AION] ERROR: AION_API_KEY is not set"
    echo "[AION] Run: export AION_API_KEY=\"\$OPENROUTER_API_KEY\""
    exit 1
fi

export AION_PROVIDER="${AION_PROVIDER:-openai_compatible}"
export AION_API_URL="${AION_API_URL:-https://openrouter.ai/api/v1}"
export AION_MODEL="${AION_MODEL:-google/gemini-2.5-flash}"
export AION_MAX_TOKENS="${AION_MAX_TOKENS:-1000}"

if [ -n "$AION_PYTHON" ]; then
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

echo "[AION] API Key Loaded: YES"
echo "[AION] Provider: $AION_PROVIDER"
echo "[AION] Model: $AION_MODEL"
echo "[AION] Python: $PYTHON_BIN"
echo "[AION] Web UI: http://localhost:8080"

exec "$PYTHON_BIN" server.py
export AION_MODEL="${AION_MODEL:-openrouter/free}"
export AION_MAX_TOKENS="${AION_MAX_TOKENS:-256}"
export AION_FREE_ONLY="${AION_FREE_ONLY:-1}"

# Предполётная проверка: ключ есть, модель разрешена политикой free-only.
python - <<'PY'
from core.llm import llm_status
s = llm_status()
print("[AION] LLM status:", s)
if s.get("status") != "ok":
    raise SystemExit(2)
PY

echo "[AION] API Key Loaded: YES"
echo "[AION] Free-only mode: ${AION_FREE_ONLY}"
echo "[AION] Model: ${AION_MODEL}"
echo "[AION] Web UI: http://localhost:8080"

if [ -x "$HOME/testenv/bin/python" ]; then
    exec "$HOME/testenv/bin/python" server.py
else
    exec python server.py
fi
