#!/bin/sh
set -eu

umask 077
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR="${AION_PROJECT_DIR:-$SCRIPT_DIR}"
PYTHON_BIN="${AION_PYTHON:-$PROJECT_DIR/.venv/bin/python}"

cd "$PROJECT_DIR"
export PYTHONPATH="$PROJECT_DIR${PYTHONPATH:+:$PYTHONPATH}"
export AION_RUNTIME_DIR="${AION_RUNTIME_DIR:-$PROJECT_DIR/runtime}"
export AION_PROVIDER="${AION_PROVIDER:-openai_compatible}"
export AION_API_URL="${AION_API_URL:-https://openrouter.ai/api/v1}"
export AION_MODEL="${AION_MODEL:-openrouter/free}"
export AION_MAX_TOKENS="${AION_MAX_TOKENS:-800}"
export AION_BIND="${AION_BIND:-127.0.0.1}"
export AION_PORT="${AION_PORT:-8080}"

mkdir -p "$AION_RUNTIME_DIR"
chmod 700 "$AION_RUNTIME_DIR" 2>/dev/null || true

if [ "$AION_PROVIDER" != "mock" ] && [ -z "${AION_API_KEY:-}" ]; then
    echo "[AION][ERROR] AION_API_KEY is not set." >&2
    echo "Load it from a protected environment file before starting." >&2
    exit 1
fi

if [ ! -x "$PYTHON_BIN" ]; then
    echo "[AION][ERROR] Python executable not found: $PYTHON_BIN" >&2
    echo "Create .venv as described in docs/TRIAL_RUNBOOK_CLOUD_TERMUX.md." >&2
    exit 1
fi

echo "[AION] Running preflight checks..."
"$PYTHON_BIN" -m core.diagnostics
echo "[AION] Provider: $AION_PROVIDER"
echo "[AION] Model: $AION_MODEL"
echo "[AION] Loopback UI: http://127.0.0.1:$AION_PORT"

exec "$PYTHON_BIN" server.py
