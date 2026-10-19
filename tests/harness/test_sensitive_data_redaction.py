"""Offline checks that secrets do not cross API, memory or state boundaries."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from core import engine, pipeline
from memory import store
from security.redaction import REDACTION_MARKER, SensitiveDataError, redact_sensitive


secret = "sk-" + "proj-" + ("A" * 32)
bearer = "Bearer " + ("b" * 40)
password = "password=" + ("p" * 20)
sample = f"credentials {secret} {bearer} {password}"
redacted = redact_sensitive(sample)
assert redacted.count == 3, redacted
assert secret not in redacted.text and bearer not in redacted.text
assert redacted.text.count(REDACTION_MARKER) == 3


with TemporaryDirectory() as temp_dir:
    root = Path(temp_dir)
    history = root / "history.json"
    knowledge = root / "knowledge.json"
    state_file = root / "state.json"

    with patch.object(store, "HISTORY_FILE", history), patch.object(
        store, "LONG_TERM_FILE", knowledge
    ):
        store.add_episodic_event(f"question {secret}", f"answer {bearer}")
        raw_history = history.read_text(encoding="utf-8")
        assert secret not in raw_history and bearer not in raw_history, raw_history
        assert raw_history.count(REDACTION_MARKER) == 2, raw_history
        assert secret not in store.get_recent_history()

        try:
            store.add_long_term_lesson(f"claim {secret}")
        except SensitiveDataError:
            pass
        else:
            raise AssertionError("Secret-bearing long-term promotion must be blocked")
        assert not knowledge.exists(), "Rejected long-term claim must not be persisted"

    observed_prompts = []

    def fake_llm(prompt, max_tokens=None, model=None):
        observed_prompts.append(prompt)
        return f"safe answer accidentally echoed {secret}"

    with patch.object(engine, "STATE_FILE", state_file), patch.object(
        engine, "ask_llm", fake_llm
    ):
        state = engine.run_cycle(f"user task {secret}")
    assert secret not in observed_prompts[0], observed_prompts[0]
    assert secret not in state_file.read_text(encoding="utf-8")
    assert secret not in str(state)
    assert state["last_answer"].endswith(REDACTION_MARKER)


captured = []


def fake_pipeline(task, *, initial_raw_answers, max_iterations):
    captured.append((task, initial_raw_answers))
    return {"status": "ok", "final_answer": f"echo {secret}", "truth_verified": False}


prepared = {"a:free": f"answer {secret}", "b:free": "clean"}
with patch.object(pipeline, "_run_pipeline_with_budget", fake_pipeline):
    result = pipeline.run_pipeline(f"compare {secret}", initial_raw_answers=prepared)
assert secret not in captured[0][0], captured
assert secret not in str(captured[0][1]), captured
assert secret not in str(result), result
assert result["redaction"]["input"] == 1, result
assert result["redaction"]["prepared_answers"] == 1, result
assert result["redaction"]["output"] == 1, result

print("SENSITIVE DATA REDACTION: PASS")
