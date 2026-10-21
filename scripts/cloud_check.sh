#!/usr/bin/env bash
# AION cloud validation entry point. Run from a checked-out AION repository.
set -Eeuo pipefail
umask 077

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "[FAIL] Run this script from a git checkout of AION" >&2
  exit 2
}
cd "$ROOT"

if [[ -n "${AION_BOOTSTRAP_PYTHON:-}" ]]; then
  BOOTSTRAP_PYTHON="$AION_BOOTSTRAP_PYTHON"
elif command -v python3 >/dev/null 2>&1; then
  BOOTSTRAP_PYTHON="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  BOOTSTRAP_PYTHON="$(command -v python)"
else
  echo "[FAIL] Python 3 is missing. Install Python 3.10+ and venv support." >&2
  exit 2
fi

"$BOOTSTRAP_PYTHON" - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("[FAIL] AION requires Python 3.10+")
PY

# Keep the environment outside the repository so hygiene checks scan only source.
VENV_ROOT="${AION_TEST_VENV_DIR:-${HOME}/.cache/aion-cloud-check-venv}"
if [[ ! -x "$VENV_ROOT/bin/python" ]]; then
  mkdir -p "$(dirname "$VENV_ROOT")"
  "$BOOTSTRAP_PYTHON" -m venv "$VENV_ROOT" || {
    echo "[FAIL] Could not create venv. On Ubuntu/Debian install python3-venv." >&2
    exit 2
  }
fi

# Termux may create a venv without pip even when ensurepip wheels are installed.
# Repair only the dedicated test venv; never install into the system Python.
if ! "$VENV_ROOT/bin/python" -m pip --version >/dev/null 2>&1; then
  echo "[AION] Bootstrapping pip in the test environment"
  "$VENV_ROOT/bin/python" -m ensurepip --upgrade || {
    echo "[FAIL] Cannot bootstrap pip in the test venv. On Termux install python-ensurepip-wheels." >&2
    exit 2
  }
fi

"$VENV_ROOT/bin/python" -m pip install --disable-pip-version-check -q -r requirements-core.txt

export PATH="$VENV_ROOT/bin:$PATH"
echo "[AION] Validating checked-out revision: $(git rev-parse HEAD)"
if [[ "${AION_LIVE_TEST:-0}" == "1" && -z "${AION_API_KEY:-}" ]]; then
  echo "[FAIL] Live test requires AION_API_KEY in the environment; do not put it in a file." >&2
  exit 2
fi
bash scripts/full_life_test.sh
