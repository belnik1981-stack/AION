"""Episodic memory stays bounded without deleting accepted history."""

import hashlib
import json
import multiprocessing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from memory import store
from storage.atomic_json import JsonCorruptionError, JsonStorageError, load_json


def _archive_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _event_fingerprints(active: list[dict], archive: list[dict]) -> set[str]:
    return {
        *(item["fingerprint"] for item in active),
        *(item["fingerprint"] for item in archive),
    }


def _add_from_process(history: str, archive: str, value: int) -> None:
    store.HISTORY_FILE = Path(history)
    store.EPISODIC_ARCHIVE_FILE = Path(archive)
    store.MAX_ACTIVE_EPISODIC_EVENTS = 3
    store.add_episodic_event(f"question-{value}", f"answer-{value}")


with TemporaryDirectory() as temp_dir:
    root = Path(temp_dir)
    history = root / "history.json"
    archive = root / "archive.jsonl"
    with patch.object(store, "HISTORY_FILE", history), patch.object(
        store, "EPISODIC_ARCHIVE_FILE", archive
    ), patch.object(store, "MAX_ACTIVE_EPISODIC_EVENTS", 3):
        for value in range(5):
            store.add_episodic_event(f"question-{value}", f"answer-{value}")

        active = load_json(history, default_factory=list, expected_type=list)
        archived = _archive_records(archive)
        assert [item["user"] for item in active] == [
            "question-2",
            "question-3",
            "question-4",
        ]
        assert [item["event"]["user"] for item in archived] == [
            "question-0",
            "question-1",
        ]
        assert len(_event_fingerprints(active, archived)) == 5
        assert all(item["schema_version"] == "aion-episodic-archive-v1" for item in archived)
        assert all(
            item["event_digest"]
            == hashlib.sha256(
                json.dumps(
                    item["event"],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest()
            for item in archived
        )
        assert history.stat().st_mode & 0o077 == 0
        assert archive.stat().st_mode & 0o077 == 0

        status = store.get_episodic_archive_status()
        assert status["status"] == "ok"
        assert status["records"] == 2
        assert status["integrity_checked"] is True
        memory_status = store.get_episodic_memory_status()
        assert memory_status["status"] == "ok"
        assert memory_status["total_unique_records"] == 5

        # An event already present in active memory or the archive is not
        # reintroduced, so deduplication covers the full retained history.
        before_history = history.read_bytes()
        before_archive = archive.read_bytes()
        store.add_episodic_event("question-4", "answer-4")
        store.add_episodic_event("question-0", "answer-0")
        assert history.read_bytes() == before_history
        assert archive.read_bytes() == before_archive

        # App-specific digest validation detects content tampering even when
        # the JSONL syntax itself remains valid.
        tampered = _archive_records(archive)
        tampered[0]["event"]["ai"] = "changed after archival"
        archive.write_text(
            "".join(
                json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n"
                for item in tampered
            ),
            encoding="utf-8",
        )
        try:
            store.get_episodic_archive_status()
        except JsonCorruptionError:
            pass
        else:
            raise AssertionError("Archive event tampering must be detected")
        archive.write_bytes(before_archive)

        # Corruption blocks all new memory writes without replacing either
        # active history or the damaged archive.
        archive.write_bytes(before_archive + b'{"partial":')
        damaged_archive = archive.read_bytes()
        try:
            store.add_episodic_event("new-question", "new-answer")
        except JsonCorruptionError:
            pass
        else:
            raise AssertionError("Corrupt archive must block episodic writes")
        assert history.read_bytes() == before_history
        assert archive.read_bytes() == damaged_archive


# If the active-history replace fails after an archive append, the old active
# file remains readable. A retry deduplicates the archive and completes the
# rotation without losing or duplicating an event.
with TemporaryDirectory() as temp_dir:
    root = Path(temp_dir)
    history = root / "history.json"
    archive = root / "archive.jsonl"
    with patch.object(store, "HISTORY_FILE", history), patch.object(
        store, "EPISODIC_ARCHIVE_FILE", archive
    ), patch.object(store, "MAX_ACTIVE_EPISODIC_EVENTS", 2):
        store.add_episodic_event("question-0", "answer-0")
        store.add_episodic_event("question-1", "answer-1")
        old_active = history.read_bytes()
        real_replace = __import__("os").replace

        def fail_history_replace(source, destination):
            if Path(destination) == history:
                raise OSError("synthetic active-history replace failure")
            return real_replace(source, destination)

        with patch("storage.atomic_json.os.replace", side_effect=fail_history_replace):
            try:
                store.add_episodic_event("question-2", "answer-2")
            except JsonStorageError:
                pass
            else:
                raise AssertionError("Synthetic history failure must surface")
        assert history.read_bytes() == old_active
        assert len(_archive_records(archive)) == 1
        interrupted = store.get_episodic_memory_status()
        assert interrupted["status"] == "recovery_needed"
        assert interrupted["recovery_overlap_records"] == 1

        store.add_episodic_event("question-2", "answer-2")
        active = load_json(history, default_factory=list, expected_type=list)
        archived = _archive_records(archive)
        assert [item["user"] for item in active] == ["question-1", "question-2"]
        assert len(archived) == 1
        assert len(_event_fingerprints(active, archived)) == 3
        assert store.get_episodic_memory_status()["status"] == "ok"


# Independent Termux/cloud processes share the history lock; concurrent writes
# cannot silently discard records while rotation is occurring.
with TemporaryDirectory() as temp_dir:
    root = Path(temp_dir)
    history = root / "history.json"
    archive = root / "archive.jsonl"
    context = multiprocessing.get_context("fork")
    processes = [
        context.Process(
            target=_add_from_process,
            args=(str(history), str(archive), value),
        )
        for value in range(8)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0, process.exitcode

    active = load_json(history, default_factory=list, expected_type=list)
    archived = _archive_records(archive)
    assert len(active) == 3
    assert len(archived) == 5
    assert len(_event_fingerprints(active, archived)) == 8


# Secret-bearing text is redacted before it reaches either active memory or
# the archive, and an oversized record is rejected before creating storage.
with TemporaryDirectory() as temp_dir:
    root = Path(temp_dir)
    history = root / "history.json"
    archive = root / "archive.jsonl"
    fake_key = "sk-proj-" + "S" * 32
    with patch.object(store, "HISTORY_FILE", history), patch.object(
        store, "EPISODIC_ARCHIVE_FILE", archive
    ), patch.object(store, "MAX_ACTIVE_EPISODIC_EVENTS", 1):
        store.add_episodic_event(f"question {fake_key}", "safe answer")
        store.add_episodic_event("next question", "next answer")
        raw_archive = archive.read_text(encoding="utf-8")
        assert fake_key not in raw_archive
        assert "[REDACTED_SECRET]" in raw_archive

with TemporaryDirectory() as temp_dir:
    root = Path(temp_dir)
    history = root / "history.json"
    archive = root / "archive.jsonl"
    with patch.object(store, "HISTORY_FILE", history), patch.object(
        store, "EPISODIC_ARCHIVE_FILE", archive
    ):
        try:
            store.add_episodic_event(
                "oversized",
                "x" * (store.MAX_EPISODIC_EVENT_BYTES + 1),
            )
        except JsonStorageError:
            pass
        else:
            raise AssertionError("Oversized episodic event must be rejected")
        assert not history.exists()
        assert not archive.exists()


print("BOUNDED EPISODIC MEMORY ARCHIVE: PASS")
