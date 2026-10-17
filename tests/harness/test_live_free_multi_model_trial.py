"""Offline regression: reuse task-specific, typed raw answers, not 2+2 probes."""
import io
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from tools import live_free_multi_model_trial as multi

ONE = "dots-studio/dots-3-note-preview:free"
TWO = "nvidia/second-test:free"
THREE = "third-org/third-test:free"
FOUR = "fourth-org/fourth-test:free"
FIVE = "fifth-org/fifth-test:free"
FREE = [TWO, ONE, THREE, FOUR, FIVE]

assert multi._candidate_models(FREE) == [ONE, TWO, THREE, FOUR, FIVE]
assert multi._candidate_models(FREE, requested=TWO + "," + ONE) == [TWO, ONE]
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


def collect(outcomes, candidates=None, explicit=False):
    calls = []
    def raw(task, mid):
        calls.append((task, mid))
        return outcomes[mid]
    with patch("sys.stdout", new_callable=io.StringIO) as out:
        selected = multi._collect_two_raw_answers(
            candidates or FREE, explicit=explicit, attempt=raw
        )
        log = out.getvalue()
    assert all(task == multi.TEST_TASK for task, mid in calls)
    return selected, [m for task, m in calls], log


answers, calls, log = collect({
    TWO: {"status": "http_error", "http_status": 502},
    ONE: {"status": "ok", "answer": "First independent response"},
    THREE: {"status": "ok", "answer": "Second independent response"},
})
assert list(answers) == [ONE, THREE] and calls == [TWO, ONE, THREE], (calls, log)
assert "[RAW ERROR]" in log and "HTTP 502" in log

answers, calls, log = collect({
    TWO: {"status": "rate_limited", "http_status": 429},
})
assert answers is None and calls == [TWO] and "HTTP 429" in log

answers, calls, log = collect({
    TWO: {"status": "http_error", "http_status": 401},
})
assert answers is None and calls == [TWO]

answers, calls, log = collect({
    TWO: {"status": "truncated"},
    ONE: {"status": "ok", "answer": "Valid"},
    THREE: {"status": "ok", "answer": "Valid 2"},
})
assert list(answers) == [ONE, THREE] and calls == [TWO, ONE, THREE]

answers, calls, log = collect({
    TWO: {"status": "http_error", "http_status": 404},
    ONE: {"status": "ok", "answer": "Valid"},
}, candidates=[TWO, ONE], explicit=True)
assert answers is None and calls == [TWO]

answers, calls, log = collect({
    TWO: {"status": "ok", "answer": " "},
}, candidates=[TWO], explicit=True)
assert answers is None and calls == [TWO] and "invalid_response" in log


def run_driver(status="ok", *, same_raw=False, bad_model_contract=False):
    seen = []
    def raw(task, mid):
        seen.append(("raw", mid, task))
        return {
            "status": "ok",
            "answer": "Same answer" if same_raw else "Answer of " + mid,
        }
    def pipeline(task, *, initial_raw_answers=None):
        models = os.environ["AION_MODELS"].split(",")
        seen.append(("pipeline", tuple(models), task))
        assert os.environ["AION_FREE_ONLY"] == "1"
        assert os.environ["AION_DISABLE_REASONING"] == "0"
        assert os.environ["AION_MULTI_TEST_ROUNDS"] == "1"
        assert initial_raw_answers == {
            mid: ("Same answer" if same_raw else "Answer of " + mid)
            for mid in models
        }
        return {
            "status": status,
            "mode": "multi_model_role_rotation",
            "independent_model_count": 1 if bad_model_contract else 2,
            "independent_initial_outputs": 2,
            "model_ids_distinct": True,
            "models": models,
            "raw_answers": initial_raw_answers,
            "raw_diagnostics": {mid: {"status": "ok", "reused": True} for mid in models},
            "truth_verified": False,
            "verification_scope": "llm_review_only",
            "final_answer": "Reviewed comparison" if status == "ok" else None,
            "rotations_used": 1,
            "rounds": [{
                "accepted": status == "ok",
                "role_assignment": {
                    "planner": models[0], "analyst": models[1], "critic": models[0],
                    "synthesizer": models[1], "verifier": models[0],
                },
            }],
            "stage": "verifier" if status != "ok" else None,
            "detail": "Verification failed" if status != "ok" else None,
        }
    with patch.dict(os.environ, {
        "AION_API_KEY": "synthetic",
        "AION_MODELS": "",
        "AION_FREE_ONLY": "0",
        "AION_DISABLE_REASONING": "1",
    }):
        with patch.object(multi, "catalog_candidates", lambda key: [ONE, TWO]), \
             patch.object(multi, "_raw_answer_attempt", raw), \
             patch.object(multi, "run_pipeline", pipeline), \
             patch("sys.stdout", new_callable=io.StringIO) as out:
            result = multi.execute()
            log = out.getvalue()
    return result, seen, log


code, calls, log = run_driver()
assert code == 0, log
assert calls == [
    ("raw", ONE, multi.TEST_TASK), ("raw", TWO, multi.TEST_TASK),
    ("pipeline", (ONE, TWO), multi.TEST_TASK)
], calls
assert "[PASS] MULTI MODEL PIPELINE" in log and "[TRUTH VERIFIED] False" in log
assert "[ROLES]" in log and "planner=" in log and "verifier=" in log
assert "[PASS] Truth unchanged" in log

code, calls, log = run_driver(same_raw=True)
assert code == 0 and "[RAW TEXTS IDENTICAL] True" in log and "[TRUTH VERIFIED] False" in log

code, calls, log = run_driver(status="error")
assert code == 1 and "[FAIL] MULTI MODEL PIPELINE" in log
assert "[STAGE] verifier" in log and "[DETAIL] Verification failed" in log

code, calls, log = run_driver(bad_model_contract=True)
assert code == 1 and "[FAIL] Model independence contract not met." in log


# A claimed "OK" with a bad or missing initial raw result must be rejected.
def bad_pipeline(task, *, initial_raw_answers=None):
    return {
        "status": "error", "stage": "raw_multi_model",
        "detail": "One initial answer failed",
        "raw_diagnostics": {ONE: {"status": "truncated"}},
    }
with patch.dict(os.environ, {"AION_API_KEY": "synthetic", "AION_MODELS": ""}), \
     patch.object(multi, "catalog_candidates", lambda key: [ONE, TWO]), \
     patch.object(multi, "_raw_answer_attempt", lambda task, m: {"status": "ok", "answer": "OK"}), \
     patch.object(multi, "run_pipeline", bad_pipeline), \
     patch("sys.stdout", new_callable=io.StringIO) as out:
    result = multi.execute()
assert result == 1
assert "[STAGE] raw_multi_model" in out.getvalue()
assert "[RAW DIAG]" in out.getvalue()

with tempfile.TemporaryDirectory() as td:
    truth = Path(td) / "truth.json"
    system = Path(td) / "system.yaml"
    truth.write_text("original")
    system.write_text("original")
    def modify_truth(task, *, initial_raw_answers=None):
        truth.write_text("altered")
        return bad_pipeline(task, initial_raw_answers=initial_raw_answers)
    with patch.dict(os.environ, {"AION_API_KEY": "synthetic", "AION_MODELS": ""}), \
         patch.object(multi, "_hash_truth", lambda: tuple(
             __import__("hashlib").sha256(p.read_bytes()).hexdigest()
             for p in (truth, system)
         )), \
         patch.object(multi, "catalog_candidates", lambda key: [ONE, TWO]), \
         patch.object(multi, "_raw_answer_attempt", lambda task, m: {"status": "ok", "answer": "OK"}), \
         patch.object(multi, "run_pipeline", modify_truth), \
         patch("sys.stdout", new_callable=io.StringIO):
        try:
            multi.execute()
        except SystemExit as exc:
            assert exc.code == 3
        else:
            raise AssertionError("Truth modification must fail closed")

print("TWO-MODEL TASK-SPECIFIC RAW REGRESSION: PASS")
