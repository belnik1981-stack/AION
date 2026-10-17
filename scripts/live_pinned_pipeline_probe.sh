#!/usr/bin/env bash
# Bounded, free-only real-provider life trial. Python driver is regression tested.
set -Eeuo pipefail
umask 077
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT"
export AION_PROVIDER=openai_compatible
export AION_API_URL=https://openrouter.ai/api/v1
export AION_FREE_ONLY=1
export AION_REASONING_EFFORT=none
unset AION_MODELS
PYTHON_BIN="${AION_PROBE_PYTHON:-python3}"
exec "$PYTHON_BIN" -m tools.live_free_pipeline_trial
