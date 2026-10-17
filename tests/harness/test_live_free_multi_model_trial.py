"""Offline end-to-end contract for the two-model live trial.

Uses model/catalog fixtures, verifies provider calls and Truth checks.
Real network model availability is separately tested in Termux.
"""
import io
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from providers.base import ProviderError, ProviderHTTPError, ProviderRateLimitError, ProviderTruncatedError
from tools import live_free_multi_model_trial as multi

ONE = "dots-studio/dots-3-note-preview:free"
TWO = "nvidia/second-test:free"
THREE = "third-org/third-test:free"
FOUR = "fourth-org/fourth-test:free"
FIVE = "fifth-org/fifth-test:free"
FREE = [TWO, ONE, THREE, FOUR, FIVE]


assert multi._candidate_models(FREE) == [ONE, TWO, THREE, FOUR, FIVE]
assert multi._candidate_models(FREE, requested=TWO + "," + ONE) == [TWO, ONE]
for invalid in ("",):  # empty means automatic selection, not an explicit pair
    assert multi._candidate_models(FREE, requested=invalid)[0] == ONE
for invalid in (
    ONE, ONE + "," + ONE, "openrouter/free," + TWO,
    "nvidia/foo:free," + TWO, ONE + "," + "missing/unlisted:free",
    ONE + "," + TWO + "," + THREE,
):
    try:
        multi._candidate_models(FREE, requested=invalid)
    except ValueError:
        pass
    else:
        raise AssertionError("Invalid model pair accepted: " + invalid)

calls = []
def fake_probe(mid):
    calls.append(mid)
    if mid == TWO:
        raise ProviderHTTPError(502, "upstream unavailable")
    return mid
with patch("sys.stdout", new_callable=io.StringIO):
    selected = multi._find_two_responsive([TWO, ONE, THREE, FOUR, FIVE], probe=fake_probe)
assert selected == [ONE, THREE], selected
assert calls == [TWO, ONE, THREE], calls

calls.clear()
def rate_limit_probe(mid):
    calls.append(mid)
    raise ProviderRateLimitError("HTTP 429")
with patch("sys.stdout", new_callable=io.StringIO):
    selected = multi._find_two_responsive(FREE, probe=rate_limit_probe)
assert selected is None and calls == [TWO], calls

calls.clear()
with patch("sys.stdout", new_callable=io.StringIO):
    selected = multi._find_two_responsive([TWO, ONE], explicit=True, probe=fake_probe)
assert selected is None and calls == [TWO], calls

calls.clear()
def truncated(mid):
    calls.append(mid)
    if mid == TWO:
        raise ProviderTruncatedError("length")
    return mid
with patch("sys.stdout", new_callable=io.StringIO):
    selected = multi._find_two_responsive([TWO, ONE, THREE], probe=truncated)
assert selected == [ONE, THREE] and calls == [TWO, ONE, THREE], calls

calls.clear()
def auth_error(mid):
    calls.append(mid)
    raise ProviderHTTPError(403, "access denied")
with patch("sys.stdout", new_callable=io.StringIO):
    selected = multi._find_two_responsive(FREE, probe=auth_error)
assert selected is None and calls == [TWO]


def run_driver(status="ok", *, same_raw=False):
    seen = []
    def probe(mid):
        seen.append(("preflight", mid))
        return mid
    def pipeline(task):
        models = os.environ["AION_MODELS"].split(",")
        seen.append(("pipeline", tuple(models), os.environ["AION_MULTI_TEST_ROUNDS"]))
        assert os.environ["AION_FREE_ONLY"] == "1"
        assert os.environ["AION_DISABLE_REASONING"] == "0"
        return {
            "status": status,
            "mode": "multi_model_role_rotation",
            "independent_model_count": 2,
            "independent_initial_outputs": 2,
            "model_ids_distinct": True,
            "models": models,
            "raw_answers": {
                ONE: "yes" if not same_raw else "same",
                TWO: "no" if not same_raw else "same",
            },
            "truth_verified": False,
            "verification_scope": "llm_review_only",
            "final_answer": "The sources disagree; this is not proof" if status == "ok" else None,
            "rotations_used": 1,
            "rounds": [{
                "accepted": status == "ok",
                "role_assignment": {
                    "planner": ONE, "analyst": TWO, "critic": ONE,
                    "synthesizer": TWO, "verifier": ONE,
                },
            }],
            "stage": "verifier" if status != "ok" else None,
        }
    with patch.dict(os.environ, {
        "AION_API_KEY": "fake-key",
        "AION_MODELS": "",
        "AION_FREE_ONLY": "0",
        "AION_DISABLE_REASONING": "1",
    }):
        with patch.object(multi, "catalog_candidates", lambda key: [ONE, TWO]), \
             patch.object(multi, "_probe", probe), \
             patch.object(multi, "run_pipeline", pipeline), \
             patch("sys.stdout", new_callable=io.StringIO) as out:
            result = multi.execute()
            log = out.getvalue()
    return result, seen, log


status, seen, log = run_driver()
assert status == 0 and seen == [
    ("preflight", ONE), ("preflight", TWO), ("pipeline", (ONE, TWO), "1")
], (status, seen, log)
assert "[PASS] MULTI MODEL PIPELINE" in log and "[TRUTH VERIFIED] False" in log
assert "[ROLES]" in log and "planner=" in log and "verifier=" in log
assert "[PASS] Truth unchanged" in log

status, seen, log = run_driver(same_raw=True)
assert status == 0 and "[RAW TEXTS IDENTICAL] True" in log
assert "[TRUTH VERIFIED] False" in log

status, seen, log = run_driver(status="rotations_exhausted")
assert status == 1 and "[FAIL] MULTI MODEL PIPELINE" in log and "[PASS] Truth unchanged" in log

# Missing model responses must not be treated as a passing comparison.
def broken_pipeline(task):
    models = os.environ["AION_MODELS"].split(",")
    return {
        "status": "ok", "mode": "multi_model_role_rotation",
        "models": models, "independent_model_count": 1,
        "raw_answers": {models[0]: "some answer"},
        "truth_verified": False, "verification_scope": "llm_review_only",
        "final_answer": "OK",
    }
with patch.dict(os.environ, {"AION_API_KEY": "fake-key", "AION_MODELS": ""}), \
     patch.object(multi, "catalog_candidates", lambda key: [ONE, TWO]), \
     patch.object(multi, "_probe", lambda m: m), \
     patch.object(multi, "run_pipeline", broken_pipeline), \
     patch("sys.stdout", new_callable=io.StringIO) as out:
    failed = multi.execute()
assert failed == 1 and "[FAIL] Model independence contract not met." in out.getvalue()

with tempfile.TemporaryDirectory() as td:
    truth = Path(td) / "truth.json"
    system = Path(td) / "system.yaml"
    truth.write_text("original")
    system.write_text("original")
    def malicious_pipeline(task):
        truth.write_text("altered")
        return broken_pipeline(task)
    with patch.dict(os.environ, {"AION_API_KEY": "fake-key", "AION_MODELS": ""}), \
         patch.object(multi, "_hash_truth", lambda: tuple(
             __import__("hashlib").sha256(p.read_bytes()).hexdigest() for p in (truth, system)
         )), \
         patch.object(multi, "catalog_candidates", lambda key: [ONE, TWO]), \
         patch.object(multi, "_probe", lambda m: m), \
         patch.object(multi, "run_pipeline", malicious_pipeline), \
         patch("sys.stdout", new_callable=io.StringIO):
        try:
            multi.execute()
        except SystemExit as exc:
            assert exc.code == 3
        else:
            raise AssertionError("Truth mutation must fail closed")

print("TWO-MODEL BOUNDED LIVE REGRESSION: PASS")
