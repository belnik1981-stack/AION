#!/bin/sh
cd ~/AION || exit 1
export PYTHONPATH=.

# Secrets must be supplied explicitly through the environment.
# AION intentionally does not scan the home directory for API keys.
if [ -z "$AION_API_KEY" ]; then
    echo "[AION] ERROR: AION_API_KEY is not set"
    echo "[AION] Export it in the current shell before starting AION."
    exit 2
fi

export AION_PROVIDER="${AION_PROVIDER:-openai_compatible}"
export AION_API_URL="${AION_API_URL:-https://openrouter.ai/api/v1}"
export AION_MODEL="${AION_MODEL:-google/gemini-2.5-flash}"
export AION_MAX_TOKENS="${AION_MAX_TOKENS:-1000}"

echo "[AION] API Key Loaded: YES"
echo "[AION] Provider: $AION_PROVIDER"
echo "[AION] Model: $AION_MODEL"
echo "[AION] Web UI: http://localhost:8080"

~/testenv/bin/python server.py
