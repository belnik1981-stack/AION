"""One-time, non-destructive import from the active checkout to AION_DATA_DIR.

Run before starting the server.  Existing destination files are never replaced;
an in-progress marker lets a crash resume missing copies safely.
"""

import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
from tempfile import NamedTemporaryFile


SOURCE = Path(__file__).resolve().parent.parent
raw_destination = os.environ.get("AION_DATA_DIR", "")
if not raw_destination or not Path(raw_destination).is_absolute():
    raise SystemExit("[AION] AION_DATA_DIR не задан абсолютным путём")
DESTINATION = Path(raw_destination).resolve()
if DESTINATION == SOURCE:
    raise SystemExit("[AION] Каталог данных совпадает с каталогом кода")

DATA_FILES = (
    "state.json", "pipeline_state.json",
    "knowledge/session/session.db",
    "knowledge/episodic/history.json",
    "knowledge/episodic/archive.jsonl",
    "knowledge/long_term/knowledge.json",
)
JSON_FILES = ("state.json", "pipeline_state.json",
              "knowledge/episodic/history.json", "knowledge/long_term/knowledge.json")
FILES = DATA_FILES + tuple(path + ".bak" for path in JSON_FILES)
DONE = DESTINATION / ".stage1-import-done.json"
IN_PROGRESS = DESTINATION / ".stage1-import-in-progress.json"


def write_marker(path: Path, data: dict) -> None:
    with NamedTemporaryFile("w", encoding="utf-8", dir=DESTINATION,
                            prefix=".stage1-import-", delete=False) as handle:
        temporary = Path(handle.name)
        os.chmod(temporary, 0o600)
        json.dump(data, handle, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(destination.parent, 0o700)
    with NamedTemporaryFile("wb", dir=destination.parent,
                            prefix=".aion-import-", delete=False) as handle:
        temporary = Path(handle.name)
        os.chmod(temporary, 0o600)
        with source.open("rb") as original:
            shutil.copyfileobj(original, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, destination)


def copy_database(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(destination.parent, 0o700)
    with NamedTemporaryFile(dir=destination.parent,
                            prefix=".aion-db-import-", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as origin:
            if origin.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("исходная SQLite-память повреждена")
            with sqlite3.connect(temporary) as target:
                origin.backup(target)
                if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("копия SQLite-памяти повреждена")
        os.chmod(temporary, 0o600)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    os.umask(0o077)
    DESTINATION.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(DESTINATION, 0o700)
    if DONE.exists():
        print(f"[AION] Постоянная память: {DESTINATION}")
        return
    if IN_PROGRESS.exists():
        previous = json.loads(IN_PROGRESS.read_text(encoding="utf-8"))
        if previous.get("source") != str(SOURCE):
            raise SystemExit("[AION] Импорт начат из другой копии AION; данные не изменены")
    else:
        conflicts = [name for name in FILES if (SOURCE / name).is_file()
                     and (DESTINATION / name).exists()]
        if conflicts:
            raise SystemExit("[AION] Данные есть в обеих папках; автоматическое объединение "
                             "остановлено: " + ", ".join(conflicts))
        write_marker(IN_PROGRESS, {"source": str(SOURCE)})
    copied = []
    for name in FILES:
        source = SOURCE / name
        destination = DESTINATION / name
        if not source.is_file() or destination.exists():
            continue
        if name == "knowledge/session/session.db":
            copy_database(source, destination)
        else:
            copy_file(source, destination)
        copied.append(name)
    write_marker(DONE, {"source": str(SOURCE), "copied_on_last_attempt": copied})
    IN_PROGRESS.unlink(missing_ok=True)
    print(f"[AION] Постоянная память: {DESTINATION}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
        print(f"[AION] Импорт остановлен без удаления исходных данных: {exc}", file=sys.stderr)
        raise SystemExit(1)
