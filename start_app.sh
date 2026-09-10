#!/bin/sh
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
