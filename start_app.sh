#!/bin/sh
cd ~/AION
export PYTHONPATH=.

if [ -z "$AION_API_KEY" ]; then
    KEY_FOUND=$(grep -rohE "sk-or-v1-[A-Za-z0-9_-]+" ~ 2>/dev/null | head -n 1)
    if [ -n "$KEY_FOUND" ]; then
        export AION_API_KEY="$KEY_FOUND"
    fi
fi

export AION_PROVIDER="openai_compatible"
export AION_API_URL="https://openrouter.ai/api/v1"
export AION_MODEL="google/gemini-2.5-flash"
export AION_MAX_TOKENS=1000

echo "[AION] API Key Loaded: $( [ -n "$AION_API_KEY" ] && echo 'YES' || echo 'NO' )"
echo "[AION] Web UI: http://localhost:8080"

~/testenv/bin/python server.py
