#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
export PYTHONPATH="$ROOT"

REPORT_DIR="${AION_TEST_REPORT_DIR:-$ROOT/test-reports}"
mkdir -p "$REPORT_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
REPORT="$REPORT_DIR/life-trial-$STAMP.log"

exec > >(tee "$REPORT") 2>&1

echo "[AION] Full life trial"
echo "[AION] UTC: $(date -u +%FT%TZ)"
echo "[AION] Commit: $(git rev-parse HEAD)"
echo "[AION] Branch: $(git branch --show-current || true)"
python --version

truth_before="$(sha256sum knowledge/truth/truth.json knowledge/truth/system.yaml)"

echo "[1/4] Compile"
python -m compileall -q core providers memory trials tests tools server.py pipeline_cli.py

echo "[2/4] Offline architecture and safety tests"
for test_file in \
  tests/harness/test_current_architecture.py \
  tests/harness/test_repository_hygiene.py \
  tests/harness/test_information_cleaning_trial.py \
  tests/harness/test_evidence_objects_v2.py \
  tests/harness/test_evidence_bridge_runtime.py \
  tests/harness/test_multi_model_runtime_regression.py \
  tests/harness/test_role_error_sanitization.py \
  tests/harness/test_provider_resilience.py \
  tests/harness/test_runtime_budget.py \
  tests/harness/test_crash_safe_storage.py \
  tests/harness/test_session_persistence.py \
  tests/harness/test_stable_runtime_data.py \
  tests/harness/test_episodic_memory_archive.py \
  tests/harness/test_owner_acceptance_launcher.py \
  tests/harness/test_termux_widget_installer.py \
  tests/harness/test_sensitive_data_redaction.py \
  tests/harness/test_claim_registry.py \
  tests/harness/test_commercial_parallel_bridge.py \
  tests/harness/test_free_model_catalog_preflight.py \
  tests/harness/test_live_free_pipeline_trial.py \
  tests/harness/test_live_free_multi_model_trial.py \
  tests/harness/test_agents_runtime_adapter.py \
  tests/harness/test_agents_sdk_import_contract.py \
  tests/harness/test_chat_ingestion.py \
  tests/harness/test_verification_pipeline.py \
  tests/harness/test_verification_integrity.py \
  tests/harness/test_evidence_collector.py \
  tests/harness/test_evidence_candidate_bundle.py \
  tests/harness/test_adaptive_learning.py \
  tests/harness/test_trust_quarantine.py \
  tests/harness/test_trust_policy_engine.py \
  tests/harness/test_commercial_dependency_layer.py \
  tests/harness/test_cycle_guard.py \
  tests/harness/test_pipeline_cycle_regression.py \
  tests/harness/test_server_safety.py \
  tests/harness/test_server_http_smoke.py
do
  echo "[TEST] $test_file"
  python "$test_file"
done

echo "[3/4] Reproducible offline trials"
python -m trials.information_cleaning_v1.run_trial
python -m trials.evidence_objects_v2.run_trial

truth_after_offline="$(sha256sum knowledge/truth/truth.json knowledge/truth/system.yaml)"
if [[ "$truth_before" != "$truth_after_offline" ]]; then
  echo "[FAIL] Truth changed during offline tests"
  exit 20
fi
echo "[PASS] Truth unchanged after offline tests"

if [[ "${AION_LIVE_TEST:-0}" != "1" ]]; then
  echo "[SKIP] Live provider test. Set AION_LIVE_TEST=1 to enable it."
  echo "[PASS] OFFLINE LIFE TRIAL"
  echo "[REPORT] $REPORT"
  exit 0
fi

echo "[4/4] Bounded live provider test"
: "${AION_API_KEY:?AION_API_KEY is required for live test}"
export AION_PROVIDER="${AION_PROVIDER:-openai_compatible}"
export AION_API_URL="${AION_API_URL:-https://openrouter.ai/api/v1}"
export AION_MODEL="${AION_MODEL:-openrouter/free}"
export AION_FREE_ONLY="${AION_FREE_ONLY:-1}"
export AION_TIMEOUT="${AION_TIMEOUT:-30}"
export AION_MAX_TOKENS="${AION_MAX_TOKENS:-900}"
export AION_REASONING_EFFORT="${AION_REASONING_EFFORT:-none}"
export AION_EXCLUDE_REASONING="${AION_EXCLUDE_REASONING:-1}"

env -u AION_MODELS python - <<'PY'
import json
from core.llm import llm_status
from core.pipeline import run_pipeline

health = llm_status()
print("[LIVE SINGLE HEALTH]", json.dumps(health, ensure_ascii=False))
if health.get("status") != "ok":
    raise SystemExit("Single-model health failed")

result = run_pipeline(
    "Кратко раздели факт, гипотезу и неизвестное: вода при нормальном атмосферном давлении замерзает примерно при 0 °C."
)
print("[LIVE SINGLE RESULT]", json.dumps(result, ensure_ascii=False))
if result.get("status") != "ok" or not result.get("final_answer"):
    raise SystemExit("Single-model pipeline failed")
PY

if [[ -n "${AION_MODELS:-}" ]]; then
  python - <<'PY'
import json
import os
from core.pipeline import run_pipeline

models = [x.strip() for x in os.environ.get("AION_MODELS", "").split(",") if x.strip()]
if len(dict.fromkeys(models)) < 2:
    raise SystemExit("AION_MODELS must contain at least two distinct model IDs")

result = run_pipeline(
    "Сравни два объяснения и сохрани неопределённость: почему наблюдаемое совпадение само по себе не доказывает причинную связь?"
)
print("[LIVE MULTI RESULT]", json.dumps(result, ensure_ascii=False))
if result.get("status") != "ok":
    raise SystemExit("Multi-model pipeline did not reach an accepted answer")
if result.get("mode") != "multi_model_role_rotation":
    raise SystemExit("Multi-model mode was not activated")
if result.get("independent_model_count", 0) < 2:
    raise SystemExit("Fewer than two model responses succeeded")
if not result.get("final_answer"):
    raise SystemExit("Multi-model result has no final answer")
PY
else
  echo "[SKIP] Multi-model live test: AION_MODELS is not set."
fi

truth_after_live="$(sha256sum knowledge/truth/truth.json knowledge/truth/system.yaml)"
if [[ "$truth_before" != "$truth_after_live" ]]; then
  echo "[FAIL] Truth changed during live test"
  exit 21
fi

echo "[PASS] FULL LIFE TRIAL"
echo "[REPORT] $REPORT"
