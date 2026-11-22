"""Offline restart and recovery contract for AION operational memory."""

import json
import multiprocessing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

from core import engine, pipeline
from memory import session


def _decision_from_process(db: str, number: int) -> None:
    session.DB_FILE = Path(db)
    session.record_decision(f"decision {number}")


with TemporaryDirectory() as temporary:
    root = Path(temporary)
    db = root / "private" / "session.db"
    secret = "sk-proj-" + "A" * 32

    with patch.object(session, "DB_FILE", db):
        session.set_setting("AION_MODEL", "example/model:free")
        session.set_setting("AION_MAX_LLM_CALLS", "4")
        try:
            session.set_setting("AION_API_KEY", secret)
        except ValueError:
            pass
        else:
            raise AssertionError("API key must not enter the profile")

        with patch.dict(os.environ, {"AION_MODEL": "explicit/model:free"}):
            assert session.effective_settings()["AION_MODEL"] == "explicit/model:free"

        # Exercise the real pipeline wrapper with an offline result.
        with patch.object(pipeline, "_run_pipeline", return_value={
            "status": "ok", "final_answer": f"answer {secret}",
            "truth_verified": False,
        }):
            result = pipeline.run_pipeline("question " + secret)
        assert result["status"] == "ok"
        assert result["task_id"]
        saved = session.snapshot()
        assert saved["tasks"][0]["status"] == "completed"
        assert saved["tasks"][0]["prompt"].endswith("[REDACTED_SECRET]")
        assert saved["tasks"][0]["result"]["final_answer"].endswith("[REDACTED_SECRET]")
        assert secret.encode() not in db.read_bytes()

        # Single-cycle results use the same journal while old state is retained.
        with patch.object(engine, "STATE_FILE", root / "engine.json"), patch.object(
            engine, "ask_llm", return_value="single answer"
        ):
            cycle = engine.run_cycle("single question")
        assert cycle["status"] == "idle"
        assert any(item["kind"] == "cycle" and item["status"] == "completed"
                   for item in session.snapshot()["tasks"])

        # A new process must actually put the previous question and answer
        # into the next model prompt, rather than merely displaying old JSON.
        continuation_code = """
import sys
from pathlib import Path
from core import engine
from memory import session
session.DB_FILE = Path(sys.argv[1])
engine.STATE_FILE = Path(sys.argv[2])
def fake_llm(prompt):
    Path(sys.argv[3]).write_text(prompt, encoding='utf-8')
    return 'continued answer'
engine.ask_llm = fake_llm
engine.run_cycle('What was my previous question?')
"""
        prompt_file = root / "continued-prompt.txt"
        subprocess.run(
            [sys.executable, "-c", continuation_code, str(db),
             str(root / "engine.json"), str(prompt_file)],
            check=True, text=True, capture_output=True,
        )
        continued_prompt = prompt_file.read_text(encoding="utf-8")
        assert "single question" in continued_prompt
        assert "single answer" in continued_prompt
        assert "What was my previous question?" in continued_prompt

        decision_id = session.record_decision("Owner keeps existing Truth boundary")
        checkpoint_id = session.create_checkpoint("before restart")
        assert decision_id and checkpoint_id
        backup_name = session.snapshot()["checkpoints"][0]["backup_name"]
        assert (db.parent / "backups" / backup_name).is_file()
        assert db.stat().st_mode & 0o077 == 0
        assert db.parent.stat().st_mode & 0o077 == 0

    # This child commits an unfinished task, then exits without cleanup.
    code = """
import os, sys
from pathlib import Path
from memory import session
session.DB_FILE = Path(sys.argv[1])
task_id = session.begin_task('unfinished test task', 'pipeline')
print(task_id, flush=True)
os._exit(0)
"""
    child = subprocess.run(
        [sys.executable, "-c", code, str(db)], check=True,
        text=True, capture_output=True,
    )
    interrupted_id = child.stdout.strip()

    # A different Python process performs startup recovery and reads the state.
    restart_code = """
import json, sys
from pathlib import Path
from memory import session
session.DB_FILE = Path(sys.argv[1])
session.recover_interrupted()
print(json.dumps(session.snapshot(), ensure_ascii=False))
"""
    restarted = subprocess.run(
        [sys.executable, "-c", restart_code, str(db)], check=True,
        text=True, capture_output=True,
    )
    restarted_state = json.loads(restarted.stdout)
    assert restarted_state["tasks"][0]["id"] == interrupted_id
    assert restarted_state["tasks"][0]["status"] == "interrupted"

    with patch.object(session, "DB_FILE", db):
        assert session.recover_interrupted() == 0
        restored = session.snapshot()
        assert restored["profile"]["AION_MODEL"] == "example/model:free"
        assert restored["tasks"][0]["id"] == interrupted_id
        assert restored["tasks"][0]["status"] == "interrupted"
        assert restored["tasks"][0]["prompt"] == "unfinished test task"
        assert any(item["id"] == result["task_id"] for item in restored["tasks"])
        assert restored["decisions"][0]["text"] == "Owner keeps existing Truth boundary"
        assert restored["checkpoints"][0]["id"] == checkpoint_id

        # A fresh manual attempt refers to its interrupted parent.
        new_id = session.begin_task("unfinished test task", "pipeline", parent_id=interrupted_id)
        session.finish_task(new_id, {"status": "error", "stage": "offline_test"})
        assert session.snapshot()["tasks"][0]["parent_id"] == interrupted_id

        # Concurrent processes must not overwrite each other's decisions.
        context = multiprocessing.get_context("fork")
        processes = [context.Process(target=_decision_from_process, args=(str(db), n))
                     for n in range(4)]
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=10)
            assert process.exitcode == 0
        assert len(session.snapshot()["decisions"]) == 5

        # Never call a model if the initial task commit fails.
        with patch.object(pipeline, "begin_task", side_effect=session.SessionStorageError("offline")):
            with patch.object(pipeline, "_run_pipeline") as provider_path:
                failed = pipeline.run_pipeline("blocked")
                provider_path.assert_not_called()
        assert failed["status"] == "error" and failed["stage"] == "session_persistence"

        # Corruption is visible; the owner-selected backup can be restored.
        db.write_bytes(b"damaged database")
        try:
            session.snapshot()
        except session.SessionStorageError:
            pass
        else:
            raise AssertionError("Corruption must not become empty memory")
        session.restore_backup(backup_name)
        recovered = session.snapshot()
        assert recovered["profile"]["AION_MODEL"] == "example/model:free"
        assert recovered["decisions"][0]["id"] == decision_id
        assert list(db.parent.glob("session.db.before-restore-*"))
        assert sqlite3.connect(db).execute("PRAGMA integrity_check").fetchone()[0] == "ok"

print("OPERATIONAL SESSION PERSISTENCE: PASS")
