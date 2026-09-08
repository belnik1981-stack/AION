#!/bin/sh
set -eu

PROJECT_DIR="${AION_PROJECT_DIR:-$HOME/AION}"
PYTHON_BIN="${AION_PYTHON:-$HOME/testenv/bin/python}"

cd "$PROJECT_DIR"
export PYTHONPATH="${PYTHONPATH:-.}"

if [ -z "${AION_API_KEY:-}" ]; then
    echo "[AION][ERROR] AION_API_KEY is not set." >&2
    echo "Export the provider API key before starting AION." >&2
    exit 1
fi

export AION_PROVIDER="${AION_PROVIDER:-openai_compatible}"
export AION_API_URL="${AION_API_URL:-https://openrouter.ai/api/v1}"
export AION_MODEL="${AION_MODEL:-openrouter/free}"
export AION_MAX_TOKENS="${AION_MAX_TOKENS:-1000}"

if [ ! -x "$PYTHON_BIN" ]; then
    echo "[AION][ERROR] Python executable not found: $PYTHON_BIN" >&2
    echo "Set AION_PYTHON or create the expected virtual environment." >&2
    exit 1
fi

echo "[AION] Running local preflight checks..."
"$PYTHON_BIN" -m core.diagnostics

echo "[AION] API key configured: YES"
echo "[AION] Provider: $AION_PROVIDER"
echo "[AION] Model: $AION_MODEL"
echo "[AION] Web UI: http://127.0.0.1:${AION_PORT:-8080}"

exec "$PYTHON_BIN" server.py
