"""End-to-end offline regression of the bounded free-only Termux live driver."""
import io
import os
import tempfile
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from providers.base import ProviderError, ProviderHTTPError, ProviderRateLimitError, ProviderTruncatedError
from tools import live_free_pipeline_trial as trial


CANDIDATES = ["a/first:free", "b/second:free", "c/third:free"]


def simulate(effects, requested="openrouter/free", pipeline_status="ok"):
    """The fake gateway asserts every live call uses a catalog-vetted ID."""
    calls, catalog, pipeline_calls = [], [], []
    def catalog_candidates(key, requested=None):
        assert key == "fake-key" and requested in ("openrouter/free", "a/first:free")
        catalog.append(requested)
        return [CANDIDATES[0]] if requested == CANDIDATES[0] else list(CANDIDATES)
    def health():
        return {"status": "ok", "free_only": True}
    def llm(prompt, max_tokens, model=None):
        m = os.environ["AION_MODEL"]
        calls.append(m)
        effect = effects[len(calls)-1]
        if isinstance(effect, BaseException):
            raise effect
        return effect
    def pipeline(task):
        pipeline_calls.append(os.environ["AION_MODEL"])
        return {"status": pipeline_status, "mode": "single_model",
                "final_answer": "This is the reviewed answer" if pipeline_status == "ok" else None,
                "stage": "critic" if pipeline_status != "ok" else None,
                "detail": "[ОШИБКА:critic] finite token budget" if pipeline_status != "ok" else None}
    with patch.dict(os.environ, {"AION_API_KEY": "fake-key",
                                 "AION_MODEL": requested,
                                 "AION_DISABLE_REASONING": "0"}):
        with patch.object(trial, "catalog_candidates", catalog_candidates), \
             patch.object(trial, "llm_status", health), \
             patch.object(trial, "ask_llm", llm), \
             patch.object(trial, "run_pipeline", pipeline), \
             patch("sys.stdout", new_callable=io.StringIO) as output:
            status = trial.execute()
            log = output.getvalue()
    return status, calls, pipeline_calls, log


status, calls, pipeline, log = simulate([
    ProviderHTTPError(404, "model not found"),
    "4",
])
assert status == 0 and calls == CANDIDATES[:2] and pipeline == [CANDIDATES[1]], (
    status, calls, pipeline, log
)
assert "[PASS] LIVE PINNED SINGLE-MODEL PIPELINE" in log
assert "[PASS] Truth unchanged" in log

status, calls, pipeline, log = simulate([
    ProviderHTTPError(400, "unsupported parameter"),
    "4",
])
assert status == 0 and calls == CANDIDATES[:2] and pipeline == [CANDIDATES[1]]

status, calls, pipeline, log = simulate([
    ProviderTruncatedError("length"),
    "4",
])
assert status == 0 and calls == CANDIDATES[:2] and pipeline == [CANDIDATES[1]]

status, calls, pipeline, log = simulate([
    ProviderRateLimitError("HTTP 429"),
])
assert status == 4 and calls == [CANDIDATES[0]] and not pipeline
assert "RATE LIMIT" in log

status, calls, pipeline, log = simulate([
    ProviderHTTPError(401, "auth error"),
])
assert status == 4 and calls == [CANDIDATES[0]] and not pipeline

status, calls, pipeline, log = simulate([
    ProviderHTTPError(404, "model not found"),
], requested=CANDIDATES[0])
assert status == 4 and calls == [CANDIDATES[0]] and not pipeline

status, calls, pipeline, log = simulate([
    ProviderHTTPError(404, "model not found"),
    ProviderHTTPError(503, "provider unavailable"),
])
assert status == 4 and calls == CANDIDATES[:2] and not pipeline
assert CANDIDATES[2] not in calls

status, calls, pipeline, log = simulate(["4"], pipeline_status="error")
assert status == 1 and calls == [CANDIDATES[0]] and pipeline == [CANDIDATES[0]]
assert "[STAGE] critic" in log

# Even if a mocked pipeline modifies its temporary Truth fixture, the
# always-finally guard must refuse to report a successful trial.
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    truth = root / "truth.json"
    system = root / "system.yaml"
    truth.write_text("original")
    system.write_text("original")
    def unsafe_pipeline(_task):
        truth.write_text("modified")
        return {"status": "ok", "mode": "single_model", "final_answer": "OK"}
    with patch.dict(os.environ, {"AION_API_KEY": "fake-key",
                                 "AION_MODEL": "a/first:free"}), \
         patch.object(trial, "TRUTH_PATHS", (truth, system)), \
         patch.object(trial, "catalog_candidates", lambda *a, **kw: [CANDIDATES[0]]), \
         patch.object(trial, "llm_status", lambda: {"status": "ok", "free_only": True}), \
         patch.object(trial, "ask_llm", lambda *a, **kw: "4"), \
         patch.object(trial, "run_pipeline", unsafe_pipeline), \
         patch("sys.stdout", new_callable=io.StringIO), \
         patch("sys.stderr", new_callable=io.StringIO) as error_output:
        try:
            trial.execute()
        except SystemExit as exc:
            assert exc.code == 3, exc.code
        else:
            raise AssertionError("Truth change did not abort trial")
    assert "[FAIL] Truth changed during live test" in error_output.getvalue()

print("BOUNDED LIVE FREE PIPELINE REGRESSION: PASS")
