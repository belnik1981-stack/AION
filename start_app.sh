#!/bin/sh
cd ~/AION
export PYTHONPATH=.
export AION_PROVIDER="${AION_PROVIDER:-openai_compatible}"
export AION_API_URL="${AION_API_URL:-https://api.openai.com/v1}"
export AION_MODEL="${AION_MODEL:-gpt-4o-mini}"

echo "[AION LAUNCHER] Provider: $AION_PROVIDER | Model: $AION_MODEL"
echo "[AION LAUNCHER] Web UI available at: http://localhost:8080"
~/testenv/bin/python server.py
