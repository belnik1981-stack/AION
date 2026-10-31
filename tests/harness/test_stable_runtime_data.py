"""A widget checkout change must not reset or overwrite the owner's memory."""

import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[2]
MIGRATOR = ROOT / "scripts" / "migrate_stage1_data.py"


def run_migration(source: Path, destination: Path):
    environment = dict(os.environ, AION_DATA_DIR=str(destination))
    return subprocess.run([sys.executable, str(source / "scripts" / MIGRATOR.name)],
                          env=environment, capture_output=True, text=True)


with TemporaryDirectory() as temporary:
    root = Path(temporary)
    old = root / "old-checkout"
    new = root / "new-checkout"
    stable = root / "stable-data"
    for checkout in (old, new):
        (checkout / "scripts").mkdir(parents=True)
        shutil.copyfile(MIGRATOR, checkout / "scripts" / MIGRATOR.name)
    (old / "state.json").write_text(json.dumps({"last_answer": "remembered"}), encoding="utf-8")
    db = old / "knowledge" / "session" / "session.db"
    db.parent.mkdir(parents=True)
    connection = sqlite3.connect(db)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE remembered (value TEXT)")
    connection.execute("INSERT INTO remembered VALUES ('old task')")
    connection.commit()
    first = run_migration(old, stable)
    connection.close()
    assert first.returncode == 0, first.stderr
    assert json.loads((stable / "state.json").read_text())["last_answer"] == "remembered"
    with sqlite3.connect(stable / "knowledge" / "session" / "session.db") as connection:
        assert connection.execute("SELECT value FROM remembered").fetchone()[0] == "old task"
    assert (old / "state.json").is_file() and db.is_file()
    assert (stable / ".stage1-import-done.json").is_file()
    assert stable.stat().st_mode & 0o077 == 0

    second = run_migration(new, stable)
    assert second.returncode == 0, second.stderr
    assert json.loads((stable / "state.json").read_text())["last_answer"] == "remembered"

    conflict = root / "conflict"
    conflict.mkdir()
    (conflict / "state.json").write_text('{"last_answer":"newer"}', encoding="utf-8")
    refused = run_migration(old, conflict)
    assert refused.returncode != 0
    assert json.loads((conflict / "state.json").read_text())["last_answer"] == "newer"
    assert json.loads((old / "state.json").read_text())["last_answer"] == "remembered"

    environment = dict(os.environ, AION_DATA_DIR=str(stable))
    paths = subprocess.run(
        [sys.executable, "-c", "from core.engine import STATE_FILE; "
         "from memory.session import DB_FILE; "
         "from memory.store import HISTORY_FILE; "
         "print(STATE_FILE); print(DB_FILE); print(HISTORY_FILE)"],
        cwd=ROOT, env=environment, capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    assert paths == [str(stable / "state.json"),
                     str(stable / "knowledge" / "session" / "session.db"),
                     str(stable / "knowledge" / "episodic" / "history.json")]

print("STABLE RUNTIME DATA: PASS")
