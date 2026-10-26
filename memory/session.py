"""Durable operational history, separate from accepted episodic knowledge.

Only explicit, redacted user data enters this store. A recorded model result is
an observation of a run, never a verified fact or a Truth update.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
from typing import Any, Iterator
from uuid import uuid4

from security.redaction import SensitiveDataError, TextSafetyError, redact_sensitive, redact_structure


ROOT = Path(__file__).resolve().parent.parent
DB_FILE = ROOT / "knowledge" / "session" / "session.db"
PROFILE_KEYS = frozenset({
    "AION_MODEL", "AION_MODELS", "AION_TIMEOUT", "AION_MAX_LLM_CALLS",
    "AION_PLANNER_TOKENS", "AION_ANALYST_TOKENS", "AION_CRITIC_TOKENS",
    "AION_SYNTHESIZER_TOKENS", "AION_FINAL_CRITIC_TOKENS",
    "AION_ROLE_TOKEN_CEILING", "AION_TRUNCATION_RETRY",
})
_NUMERIC_KEYS = PROFILE_KEYS - {"AION_MODEL", "AION_MODELS", "AION_TRUNCATION_RETRY"}


class SessionStorageError(RuntimeError):
    """Operational history could not be safely read or committed."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_json(value: Any) -> str:
    try:
        safe, _ = redact_structure(value)
        return json.dumps(safe, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, TextSafetyError) as exc:
        raise SessionStorageError("Невозможно безопасно сохранить результат") from exc


def _safe_text(value: str) -> str:
    try:
        return redact_sensitive(value).text
    except (TypeError, TextSafetyError) as exc:
        raise SessionStorageError("Невозможно безопасно сохранить текст") from exc


def _prepare_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)


@contextmanager
def _connection(*, create: bool = True) -> Iterator[sqlite3.Connection]:
    path = DB_FILE
    if not create and not path.exists():
        raise SessionStorageError("Хранилище сеанса ещё не создано")
    if create:
        _prepare_dir(path.parent)
    existed = path.exists() and path.stat().st_size > 0
    connection = None
    try:
        connection = sqlite3.connect(path, timeout=10, isolation_level=None)
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA foreign_keys=ON")
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise SessionStorageError("Проверка целостности памяти не пройдена")
        if create:
            if existed:
                tables = {row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )}
                if "metadata" not in tables:
                    raise SessionStorageError("Неизвестный формат существующей памяти")
                version = connection.execute(
                    "SELECT value FROM metadata WHERE key='schema_version'"
                ).fetchone()
                if version is None or version[0] != "1":
                    raise SessionStorageError("Неизвестная версия хранилища сеанса")
            os.chmod(path, 0o600)
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS profile (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, parent_id TEXT, kind TEXT NOT NULL,
                    prompt TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL,
                    finished_at TEXT, owner_pid INTEGER NOT NULL,
                    settings_json TEXT NOT NULL, result_json TEXT,
                    FOREIGN KEY(parent_id) REFERENCES tasks(id)
                );
                CREATE TABLE IF NOT EXISTS decisions (
                    id TEXT PRIMARY KEY, task_id TEXT, text TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(id)
                );
                CREATE TABLE IF NOT EXISTS checkpoints (
                    id TEXT PRIMARY KEY, label TEXT NOT NULL, backup_name TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)
            if not existed:
                connection.execute("INSERT INTO metadata VALUES ('schema_version', '1')")
        yield connection
    except (sqlite3.Error, OSError) as exc:
        raise SessionStorageError("Хранилище сеанса недоступно; данные не заменены") from exc
    finally:
        if connection is not None:
            connection.close()


@contextmanager
def _transaction(connection: sqlite3.Connection) -> Iterator[None]:
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    else:
        connection.execute("COMMIT")


def _validate_setting(key: str, value: str) -> str:
    if key not in PROFILE_KEYS or not isinstance(value, str):
        raise ValueError("Настройка не разрешена для постоянного профиля")
    if len(value) > 512 or redact_sensitive(value).count:
        raise SensitiveDataError("Секреты и длинные значения запрещены в профиле")
    if key in _NUMERIC_KEYS:
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value):
            raise ValueError("Ожидается положительное число")
        number = float(value)
        ceiling = (32 if key == "AION_MAX_LLM_CALLS" else
                   120 if key == "AION_TIMEOUT" else 8192)
        minimum = 128 if key == "AION_ROLE_TOKEN_CEILING" else 1
        if not minimum <= number <= ceiling or (
            key != "AION_TIMEOUT" and not number.is_integer()
        ):
            raise ValueError("Настройка вне безопасного диапазона")
    elif key == "AION_TRUNCATION_RETRY":
        if value not in {"0", "1"}:
            raise ValueError("Допустимы только 0 или 1")
    elif not re.fullmatch(r"[A-Za-z0-9_./:,\-]+", value):
        raise ValueError("Недопустимое имя модели")
    return value


def set_setting(key: str, value: str) -> None:
    value = _validate_setting(key, value)
    with _connection() as connection, _transaction(connection):
        connection.execute(
            "INSERT INTO profile(key,value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value)
        )


def get_profile() -> dict[str, str]:
    if not DB_FILE.exists():
        return {}
    with _connection(create=False) as connection:
        rows = connection.execute("SELECT key,value FROM profile").fetchall()
    profile = dict(rows)
    for key, value in profile.items():
        _validate_setting(key, value)
    return profile


def effective_settings() -> dict[str, str]:
    profile = get_profile()
    return {key: os.environ.get(key, profile.get(key, "")) for key in sorted(PROFILE_KEYS)
            if key in os.environ or key in profile}


def apply_profile() -> None:
    for key, value in get_profile().items():
        os.environ.setdefault(key, value)


def begin_task(prompt: str, kind: str, *, parent_id: str | None = None) -> str:
    if kind not in {"pipeline", "cycle"}:
        raise ValueError("Неизвестный тип задачи")
    recover_interrupted()
    task_id = uuid4().hex
    with _connection() as connection, _transaction(connection):
        connection.execute(
            "INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?)",
            (task_id, parent_id, kind, _safe_text(prompt), "running", _now(),
             None, os.getpid(), _safe_json(effective_settings()), None)
        )
    return task_id


def finish_task(task_id: str, result: dict[str, Any]) -> None:
    payload = _safe_json(result)
    status = "completed" if result.get("status") in {"ok", "idle"} else "error"
    with _connection() as connection, _transaction(connection):
        cursor = connection.execute(
            "UPDATE tasks SET status=?, finished_at=?, result_json=? "
            "WHERE id=? AND status='running'",
            (status, _now(), payload, task_id),
        )
        if cursor.rowcount != 1:
            raise SessionStorageError("Задача не найдена или уже завершена")


def record_decision(text: str, *, task_id: str | None = None) -> str:
    decision_id = uuid4().hex
    with _connection() as connection, _transaction(connection):
        connection.execute(
            "INSERT INTO decisions VALUES (?,?,?,?)",
            (decision_id, task_id, _safe_text(text), _now()),
        )
    return decision_id


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def recover_interrupted() -> int:
    with _connection() as connection, _transaction(connection):
        running = connection.execute(
            "SELECT id,owner_pid FROM tasks WHERE status='running'"
        ).fetchall()
        stale = [task_id for task_id, pid in running if not _pid_alive(pid)]
        for task_id in stale:
            connection.execute(
                "UPDATE tasks SET status='interrupted', finished_at=? WHERE id=?",
                (_now(), task_id),
            )
    return len(stale)


def snapshot(*, limit: int = 20, offset: int = 0) -> dict[str, Any]:
    if not 1 <= limit <= 100 or offset < 0:
        raise ValueError("limit должен быть 1..100, offset неотрицательным")
    if not DB_FILE.exists():
        return {"status": "empty", "profile": {}, "tasks": [], "decisions": [], "checkpoints": []}
    with _connection(create=False) as connection:
        tasks = connection.execute(
            "SELECT id,parent_id,kind,prompt,status,started_at,finished_at,settings_json,result_json "
            "FROM tasks ORDER BY started_at DESC, rowid DESC LIMIT ? OFFSET ?", (limit, offset)
        ).fetchall()
        decisions = connection.execute(
            "SELECT id,task_id,text,created_at FROM decisions ORDER BY rowid DESC LIMIT ? OFFSET ?",
            (limit, offset)
        ).fetchall()
        checkpoints = connection.execute(
            "SELECT id,label,backup_name,created_at FROM checkpoints ORDER BY rowid DESC LIMIT ? OFFSET ?",
            (limit, offset)
        ).fetchall()
    return {
        "status": "ok", "profile": get_profile(),
        "tasks": [dict(zip(("id", "parent_id", "kind", "prompt", "status", "started_at",
                            "finished_at", "settings", "result"),
                           (*row[:7], json.loads(row[7]), json.loads(row[8]) if row[8] else None)))
                  for row in tasks],
        "decisions": [dict(zip(("id", "task_id", "text", "created_at"), row))
                      for row in decisions],
        "checkpoints": [dict(zip(("id", "label", "backup_name", "created_at"), row))
                        for row in checkpoints],
    }


def create_checkpoint(label: str) -> str:
    safe_label = _safe_text(label)
    checkpoint_id = uuid4().hex
    backup_dir = DB_FILE.parent / "backups"
    _prepare_dir(backup_dir)
    backup_name = f"checkpoint-{checkpoint_id}.db"
    temporary = backup_dir / f".{backup_name}.tmp"
    final = backup_dir / backup_name
    try:
        with _connection() as source:
            with sqlite3.connect(temporary) as destination:
                source.backup(destination)
                if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise SessionStorageError("Резервная копия повреждена")
            os.chmod(temporary, 0o600)
            with temporary.open("rb") as handle:
                os.fsync(handle.fileno())
            os.replace(temporary, final)
            with _transaction(source):
                source.execute(
                    "INSERT INTO checkpoints VALUES (?,?,?,?)",
                    (checkpoint_id, safe_label, backup_name, _now()),
                )
    except (sqlite3.Error, OSError) as exc:
        raise SessionStorageError("Не удалось создать контрольную точку") from exc
    finally:
        temporary.unlink(missing_ok=True)
    return checkpoint_id


def restore_backup(backup_name: str) -> None:
    """Explicit owner action; keep every original SQLite file for inspection."""
    if not re.fullmatch(r"checkpoint-[0-9a-f]{32}\.db", backup_name):
        raise ValueError("Недопустимое имя резервной копии")
    backup = DB_FILE.parent / "backups" / backup_name
    if not backup.is_file():
        raise SessionStorageError("Резервная копия не найдена")
    try:
        with sqlite3.connect(f"file:{backup}?mode=ro", uri=True) as source:
            if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise SessionStorageError("Резервная копия повреждена")
        # Do not silently discard a newer WAL or a corrupt primary.
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        for path in (DB_FILE, Path(str(DB_FILE) + "-wal"), Path(str(DB_FILE) + "-shm")):
            if path.exists():
                os.replace(path, path.with_name(path.name + f".before-restore-{stamp}"))
        temporary = DB_FILE.with_name(f".{DB_FILE.name}.{stamp}.tmp")
        try:
            shutil.copyfile(backup, temporary)
            os.chmod(temporary, 0o600)
            with temporary.open("rb") as handle:
                os.fsync(handle.fileno())
            os.replace(temporary, DB_FILE)
        finally:
            temporary.unlink(missing_ok=True)
    except (sqlite3.Error, OSError) as exc:
        raise SessionStorageError("Восстановление не завершено; исходные файлы сохранены") from exc
