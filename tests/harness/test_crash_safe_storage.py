"""Offline fault-injection tests for runtime JSON persistence."""

import json
import multiprocessing
from pathlib import Path
from tempfile import TemporaryDirectory
import warnings
from unittest.mock import patch

from core import engine
from core import pipeline
from memory import store
import server
from storage.atomic_json import (
    JsonCorruptionError,
    JsonRecoveryWarning,
    atomic_write_json,
    append_jsonl_record,
    backup_path,
    load_json,
    JsonStorageError,
    update_json,
)


def append_from_process(path: str, value: int) -> None:
    def append(items: list) -> list:
        items.append(value)
        return items

    update_json(
        path,
        default_factory=list,
        expected_type=list,
        updater=append,
    )


with TemporaryDirectory() as temp_dir:
    root = Path(temp_dir)
    target = root / "state.json"

    atomic_write_json(target, {"version": 1}, expected_type=dict)
    assert load_json(target, default_factory=dict, expected_type=dict) == {"version": 1}
    assert target.stat().st_mode & 0o077 == 0, oct(target.stat().st_mode)

    atomic_write_json(target, {"version": 2}, expected_type=dict)
    assert load_json(target, default_factory=dict, expected_type=dict) == {"version": 2}
    assert json.loads(backup_path(target).read_text(encoding="utf-8")) == {"version": 1}

    # Primary corruption never becomes an empty state. A validated backup is
    # used explicitly and the damaged bytes remain available for diagnosis.
    target.write_text("{broken", encoding="utf-8")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        recovered = load_json(target, default_factory=dict, expected_type=dict)
    assert recovered == {"version": 1}, recovered
    assert any(issubclass(item.category, JsonRecoveryWarning) for item in caught)

    atomic_write_json(target, {"version": 3}, expected_type=dict)
    assert load_json(target, default_factory=dict, expected_type=dict) == {"version": 3}
    archives = list(root.glob("state.json.corrupt-*"))
    assert len(archives) == 1 and archives[0].read_text(encoding="utf-8") == "{broken"

    # If both copies are invalid, fail without replacing either one.
    target.write_text("broken-primary", encoding="utf-8")
    backup_path(target).write_text("broken-backup", encoding="utf-8")
    try:
        load_json(target, default_factory=dict, expected_type=dict)
    except JsonCorruptionError:
        pass
    else:
        raise AssertionError("Double corruption must not silently reset state")
    try:
        atomic_write_json(target, {"replacement": True}, expected_type=dict)
    except JsonCorruptionError:
        pass
    else:
        raise AssertionError("Double corruption must not be overwritten")
    assert target.read_text(encoding="utf-8") == "broken-primary"
    assert backup_path(target).read_text(encoding="utf-8") == "broken-backup"

    # An interrupted final replace leaves the previous primary readable.
    stable = root / "stable.json"
    atomic_write_json(stable, {"stable": 1}, expected_type=dict)
    real_replace = __import__("os").replace
    calls = []

    def fail_final_replace(source, destination):
        calls.append((Path(source), Path(destination)))
        if Path(destination) == stable:
            raise OSError("synthetic interruption")
        return real_replace(source, destination)

    with patch("storage.atomic_json.os.replace", side_effect=fail_final_replace):
        try:
            atomic_write_json(stable, {"stable": 2}, expected_type=dict)
        except Exception:
            pass
        else:
            raise AssertionError("Synthetic replace failure must surface")
    assert load_json(stable, default_factory=dict, expected_type=dict) == {"stable": 1}

    # The read-modify-write primitive holds an OS-level lock, so independent
    # Termux/cloud processes cannot silently lose each other's updates.
    concurrent = root / "concurrent.json"
    context = multiprocessing.get_context("fork")
    processes = [
        context.Process(target=append_from_process, args=(str(concurrent), value))
        for value in range(6)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0, process.exitcode
    concurrent_values = load_json(concurrent, default_factory=list, expected_type=list)
    assert sorted(concurrent_values) == list(range(6)), concurrent_values

    # A partial JSONL tail is preserved and blocks later audit appends.
    audit_log = root / "audit.jsonl"
    audit_log.write_text('{"event":"valid"}\n{"event":', encoding="utf-8")
    damaged_audit = audit_log.read_bytes()
    try:
        append_jsonl_record(audit_log, {"event": "new"})
    except JsonCorruptionError:
        pass
    else:
        raise AssertionError("Corrupt audit tail must block append")
    assert audit_log.read_bytes() == damaged_audit

    # A syntactically complete final record without a newline is still an
    # interrupted JSONL append: appending directly would concatenate objects.
    missing_newline = root / "missing-newline.jsonl"
    missing_newline.write_text('{"event":"complete-but-not-committed"}', encoding="utf-8")
    original_missing_newline = missing_newline.read_bytes()
    try:
        append_jsonl_record(missing_newline, {"event": "new"})
    except JsonCorruptionError:
        pass
    else:
        raise AssertionError("JSONL tail without newline must block append")
    assert missing_newline.read_bytes() == original_missing_newline

    # Idempotent replay is allowed only for the identical audit event.
    collision_log = root / "collision.jsonl"
    original_event = {"event_id": "same-id", "state": "prepared"}
    assert append_jsonl_record(collision_log, original_event, unique_field="event_id")
    assert not append_jsonl_record(collision_log, original_event, unique_field="event_id")
    before_collision = collision_log.read_bytes()
    try:
        append_jsonl_record(
            collision_log, {"event_id": "same-id", "state": "committed"},
            unique_field="event_id",
        )
    except JsonStorageError:
        pass
    else:
        raise AssertionError("Conflicting audit event ID must fail closed")
    assert collision_log.read_bytes() == before_collision
    numeric_collision = root / "numeric-collision.jsonl"
    assert append_jsonl_record(
        numeric_collision, {"event_id": "typed", "value": True}, unique_field="event_id"
    )
    try:
        append_jsonl_record(
            numeric_collision, {"event_id": "typed", "value": 1}, unique_field="event_id"
        )
    except JsonStorageError:
        pass
    else:
        raise AssertionError("JSON boolean and number must not be treated as one event")

    # Existing AION state consumers use the same storage contract.
    history = root / "history.json"
    knowledge = root / "knowledge.json"
    state_file = root / "engine-state.json"
    pipeline_file = root / "pipeline-state.json"
    with patch.object(store, "HISTORY_FILE", history), patch.object(
        store, "LONG_TERM_FILE", knowledge
    ), patch.object(engine, "STATE_FILE", state_file), patch.object(
        server, "PIPELINE_STATE_FILE", pipeline_file
    ):
        store.add_episodic_event("question", "accepted answer")
        store.add_episodic_event("question", "accepted answer")
        saved_history = load_json(history, default_factory=list, expected_type=list)
        assert len(saved_history) == 1, saved_history
        assert len(saved_history[0]["fingerprint"]) == 64

        try:
            store.add_long_term_lesson("verified lesson")
        except store.DirectPromotionBlocked:
            pass
        else:
            raise AssertionError("Direct long-term promotion must be blocked")
        store.stage_long_term_lesson("verified lesson", "test-promotion")
        assert store.get_long_term_knowledge() == "Уроки отсутствуют."
        store.commit_staged_long_term_lesson("verified lesson", "test-promotion")
        store.commit_staged_long_term_lesson("verified lesson", "test-promotion")
        assert store.get_long_term_knowledge() == "- verified lesson"

        engine.save_state({"status": "idle"})
        assert engine.load_state() == {"status": "idle"}
        server.save_pipeline_state({"status": "ok"})
        assert server.load_pipeline_state() == {"status": "ok"}

    # A verified candidate is not reported as a successful complete pipeline
    # when persistence fails; the candidate remains visible for recovery.
    with patch.object(pipeline, "planner", return_value="plan"), patch.object(
        pipeline, "analyst", return_value="analysis"
    ), patch.object(pipeline, "critic", return_value="critique"), patch.object(
        pipeline, "synthesizer", return_value="candidate"
    ), patch.object(
        pipeline, "final_critic_check", return_value=(True, "OK")
    ), patch.object(
        pipeline, "add_episodic_event", side_effect=JsonStorageError("private detail")
    ):
        persistence_failure = pipeline._legacy_pipeline("task", "general", 1, {})
    assert persistence_failure["status"] == "error", persistence_failure
    assert persistence_failure["stage"] == "memory_persistence", persistence_failure
    assert persistence_failure["final_answer"] == "candidate", persistence_failure
    assert "private detail" not in persistence_failure["detail"], persistence_failure

print("CRASH-SAFE JSON STORAGE: PASS")
