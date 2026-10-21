#!/usr/bin/env bash
# One bounded owner/QA acceptance entry point for Termux and cloud Linux.
set -Eeuo pipefail
umask 077

usage() {
  cat <<'EOF'
Usage: bash scripts/owner_acceptance_test.sh [--offline|--live] [--local-revision]

Default mode validates that the checkout is a clean, current origin/master and
runs the offline acceptance suite in an isolated local clone.

  --offline          Run offline acceptance only (default).
  --live             After offline PASS, run the bounded two-model OpenRouter
                     trial. Requires AION_API_KEY; free-only policy is forced.
  --local-revision   Validate the current clean commit without fetching or
                     claiming that it is current master (intended for CI/dev).
  --help             Show this help.

Optional environment:
  AION_EXPECTED_SHA              Require one exact commit SHA.
  AION_ACCEPTANCE_VENV_DIR       Python venv outside the repository.
  AION_TEST_REPORT_DIR           Persistent report directory.
  AION_MODELS                    Exactly two explicit eligible :free IDs for
                                 live mode; otherwise bounded auto-selection.
EOF
}

LIVE_MODE=0
REVISION_SCOPE="release_master"
while (($#)); do
  case "$1" in
    --offline) LIVE_MODE=0 ;;
    --live) LIVE_MODE=1 ;;
    --local-revision) REVISION_SCOPE="local_revision" ;;
    --help|-h) usage; exit 0 ;;
    *) echo "[FAIL] Unknown argument. Use --help." >&2; exit 2 ;;
  esac
  shift
done

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null)" || {
  echo "[FAIL] Run the tracked launcher from an AION git checkout." >&2
  exit 2
}
cd "$ROOT"

if [[ -n "${AION_ACCEPTANCE_PYTHON:-}" ]]; then
  BOOTSTRAP_PYTHON="$AION_ACCEPTANCE_PYTHON"
elif command -v python3 >/dev/null 2>&1; then
  BOOTSTRAP_PYTHON="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  BOOTSTRAP_PYTHON="$(command -v python)"
else
  echo "[FAIL] Python 3.10+ is required." >&2
  exit 2
fi

REPORT_DIR="$($BOOTSTRAP_PYTHON - "${AION_TEST_REPORT_DIR:-$ROOT/test-reports}" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve())
PY
)"
ROOT_RESOLVED="$($BOOTSTRAP_PYTHON - "$ROOT" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).resolve())
PY
)"
case "$REPORT_DIR/" in
  "$ROOT_RESOLVED/"|"$ROOT_RESOLVED/knowledge/"*|"$ROOT_RESOLVED/audit/"*|"$ROOT_RESOLVED/logs/"*)
    echo "[FAIL] Report directory overlaps protected project data." >&2
    exit 2
    ;;
esac
mkdir -p "$REPORT_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
REPORT="$REPORT_DIR/owner-acceptance-${STAMP}-$$.log"
SUMMARY="$REPORT_DIR/owner-acceptance-${STAMP}-$$.json"
touch "$REPORT"
chmod 600 "$REPORT"
exec > >(tee "$REPORT") 2>&1

CURRENT_STAGE="initialization"
TEMP_ROOT=""
TEMP_BASE=""

cleanup() {
  local status=$?
  set +e
  if [[ -n "$TEMP_ROOT" ]]; then
    if [[ -n "$TEMP_BASE" && "$TEMP_ROOT" == "${TEMP_BASE%/}"/aion-owner-acceptance.* \
          && -f "$TEMP_ROOT/.aion-owner-acceptance" ]]; then
      rm -rf -- "$TEMP_ROOT"
    else
      echo "[WARN] Temporary path was not removed because its safety marker was missing."
    fi
  fi
  exit "$status"
}

on_error() {
  local status=$?
  trap - ERR
  echo "[STAGE FAIL] $CURRENT_STAGE"
  echo "[ACCEPTANCE FAIL] exit=$status line=${BASH_LINENO[0]:-unknown}"
  echo "[REPORT] $REPORT"
  exit "$status"
}

trap cleanup EXIT
trap on_error ERR

pass_stage() {
  echo "[STAGE PASS] $1"
}

fail_stage() {
  echo "[FAIL] $1" >&2
  return 1
}

"$BOOTSTRAP_PYTHON" - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("[FAIL] Python 3.10+ is required")
print("[PYTHON]", sys.version.split()[0])
PY

runtime_digest() {
  "$BOOTSTRAP_PYTHON" - "$ROOT" <<'PY'
import hashlib
import os
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
targets = [
    root / "state.json",
    root / "pipeline_state.json",
    root / "knowledge" / "episodic",
    root / "knowledge" / "long_term",
    root / "knowledge" / "adaptive",
    root / "knowledge" / "candidates",
    root / "audit",
    root / "logs",
]
digest = hashlib.sha256()

def add_path(path: Path) -> None:
    relative = path.relative_to(root).as_posix().encode("utf-8", "surrogateescape")
    digest.update(len(relative).to_bytes(8, "big"))
    digest.update(relative)
    if path.is_symlink():
        digest.update(b"L" + os.readlink(path).encode("utf-8", "surrogateescape"))
        return
    if not path.exists():
        digest.update(b"A")
        return
    if path.is_dir():
        digest.update(b"D")
        return
    digest.update(b"F")
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)

for target in targets:
    add_path(target)
    if target.is_dir() and not target.is_symlink():
        for child in sorted(target.rglob("*"), key=lambda item: item.as_posix()):
            add_path(child)
print(digest.hexdigest())
PY
}

truth_digest() {
  "$BOOTSTRAP_PYTHON" - "$ROOT" <<'PY'
import hashlib
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
digest = hashlib.sha256()
for name in ("truth.json", "system.yaml"):
    path = root / "knowledge" / "truth" / name
    if not path.is_file():
        raise SystemExit("[FAIL] Truth file is missing")
    digest.update(name.encode("utf-8"))
    digest.update(path.read_bytes())
print(digest.hexdigest())
PY
}

CURRENT_STAGE="revision"
REVISION="$(git rev-parse HEAD)"
BRANCH="$(git branch --show-current)"
git diff --quiet --ignore-submodules -- || fail_stage "Tracked working tree is modified."
git diff --cached --quiet --ignore-submodules -- || fail_stage "Index contains uncommitted changes."

if [[ -n "${AION_EXPECTED_SHA:-}" ]]; then
  [[ "$AION_EXPECTED_SHA" =~ ^[0-9a-fA-F]{7,40}$ ]] \
    || fail_stage "AION_EXPECTED_SHA is not a hexadecimal commit ID."
  EXPECTED="$(git rev-parse --verify "${AION_EXPECTED_SHA}^{commit}")" \
    || fail_stage "AION_EXPECTED_SHA is not present in this checkout."
  [[ "$REVISION" == "$EXPECTED" ]] || fail_stage "Checkout does not match AION_EXPECTED_SHA."
fi

if [[ "$REVISION_SCOPE" == "release_master" ]]; then
  [[ "$BRANCH" == "master" ]] || fail_stage "Release acceptance requires branch master."
  ORIGIN_URL="$(git remote get-url origin 2>/dev/null)" \
    || fail_stage "Remote origin is unavailable."
  [[ "$ORIGIN_URL" == *"belnik1981-stack/AION"* ]] \
    || fail_stage "Remote origin is not the authorised AION repository."
  git fetch --quiet origin master
  REMOTE_MASTER="$(git rev-parse --verify refs/remotes/origin/master)"
  [[ "$REVISION" == "$REMOTE_MASTER" ]] \
    || fail_stage "Checkout is not the current origin/master; update with ff-only first."
else
  echo "[SCOPE] Local clean revision; current-master claim is intentionally disabled."
fi
echo "[REVISION] $REVISION"
echo "[BRANCH] ${BRANCH:-detached}"
echo "[SCOPE] $REVISION_SCOPE"
pass_stage "$CURRENT_STAGE"

CURRENT_STAGE="primary_integrity_baseline"
PRIMARY_RUNTIME_BEFORE="$(runtime_digest)"
PRIMARY_TRUTH_BEFORE="$(truth_digest)"
pass_stage "$CURRENT_STAGE"

CURRENT_STAGE="isolated_checkout"
TEMP_BASE="$($BOOTSTRAP_PYTHON - "${TMPDIR:-/tmp}" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve())
PY
)"
[[ "$TEMP_BASE/" != "$ROOT_RESOLVED/"* ]] \
  || fail_stage "TMPDIR must be outside the repository."
mkdir -p "$TEMP_BASE"
TEMP_ROOT="$(mktemp -d "${TEMP_BASE%/}/aion-owner-acceptance.XXXXXX")"
touch "$TEMP_ROOT/.aion-owner-acceptance"
SANDBOX="$TEMP_ROOT/repository"
git clone --quiet --no-hardlinks --no-checkout "$ROOT" "$SANDBOX"
git -C "$SANDBOX" checkout --quiet --detach "$REVISION"
[[ "$(git -C "$SANDBOX" rev-parse HEAD)" == "$REVISION" ]] \
  || fail_stage "Isolated checkout revision mismatch."
pass_stage "$CURRENT_STAGE"

CURRENT_STAGE="offline_life_trial"
DEFAULT_CACHE_ROOT="${XDG_CACHE_HOME:-${HOME:?HOME is required}/.cache}"
ACCEPTANCE_VENV="${AION_ACCEPTANCE_VENV_DIR:-$DEFAULT_CACHE_ROOT/aion-owner-acceptance-venv}"
VENV_PATH="$($BOOTSTRAP_PYTHON - "$ACCEPTANCE_VENV" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve())
PY
)"
ROOT_PATH="$($BOOTSTRAP_PYTHON - "$ROOT" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).resolve())
PY
)"
[[ "$VENV_PATH/" != "$ROOT_PATH/"* ]] \
  || fail_stage "Acceptance venv must be outside the repository."
(
  cd "$SANDBOX"
  export AION_TEST_VENV_DIR="$VENV_PATH"
  export AION_TEST_REPORT_DIR="$TEMP_ROOT/full-life-reports"
  export AION_LIVE_TEST=0
  unset AION_API_KEY AION_MODELS AION_MODEL AION_EXPECTED_SHA
  bash scripts/cloud_check.sh
)
pass_stage "$CURRENT_STAGE"

LIVE_RESULT="SKIP"
if ((LIVE_MODE)); then
  CURRENT_STAGE="live_two_model_trial"
  [[ -n "${AION_API_KEY:-}" ]] \
    || fail_stage "--live requires AION_API_KEY in the environment."
  [[ -x "$VENV_PATH/bin/python" ]] \
    || fail_stage "Acceptance Python environment is unavailable."
  (
    cd "$SANDBOX"
    export AION_PROBE_PYTHON="$VENV_PATH/bin/python"
    export AION_FREE_ONLY=1
    bash scripts/live_two_model_probe.sh
  )
  LIVE_RESULT="PASS"
  pass_stage "$CURRENT_STAGE"
else
  echo "[STAGE SKIP] live_two_model_trial (use --live to opt in)"
fi

CURRENT_STAGE="primary_integrity_final"
PRIMARY_RUNTIME_AFTER="$(runtime_digest)"
PRIMARY_TRUTH_AFTER="$(truth_digest)"
[[ "$PRIMARY_RUNTIME_BEFORE" == "$PRIMARY_RUNTIME_AFTER" ]] \
  || fail_stage "Primary runtime or memory files changed during isolated acceptance."
[[ "$PRIMARY_TRUTH_BEFORE" == "$PRIMARY_TRUTH_AFTER" ]] \
  || fail_stage "Primary Truth files changed during isolated acceptance."
git diff --quiet --ignore-submodules -- \
  || fail_stage "Tracked files changed during acceptance."
git diff --cached --quiet --ignore-submodules -- \
  || fail_stage "Index changed during acceptance."
pass_stage "$CURRENT_STAGE"

CURRENT_STAGE="summary"
ACCEPTANCE_REVISION="$REVISION" \
ACCEPTANCE_SCOPE="$REVISION_SCOPE" \
ACCEPTANCE_LIVE_RESULT="$LIVE_RESULT" \
ACCEPTANCE_SUMMARY="$SUMMARY" \
"$BOOTSTRAP_PYTHON" - <<'PY'
import json
import os
from pathlib import Path

summary = {
    "schema_version": "aion-owner-acceptance-v1",
    "revision": os.environ["ACCEPTANCE_REVISION"],
    "revision_scope": os.environ["ACCEPTANCE_SCOPE"],
    "offline_life_trial": "PASS",
    "live_two_model_trial": os.environ["ACCEPTANCE_LIVE_RESULT"],
    "primary_runtime_unchanged": True,
    "truth_unchanged": True,
    "result": "PASS",
}
path = Path(os.environ["ACCEPTANCE_SUMMARY"])
path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
path.chmod(0o600)
PY
pass_stage "$CURRENT_STAGE"

echo "[PASS] Primary runtime and memory unchanged"
echo "[PASS] Truth unchanged"
echo "[ACCEPTANCE PASS] scope=$REVISION_SCOPE revision=$REVISION live=$LIVE_RESULT"
echo "[REPORT] $REPORT"
echo "[SUMMARY] $SUMMARY"
