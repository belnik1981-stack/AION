"""Atomic JSON persistence with a validated last-known-good backup.

The module never converts an existing malformed store into an empty value.
If the primary file is damaged, a valid backup is returned with an explicit
warning.  If neither copy is valid, callers receive a stable exception and the
original bytes remain untouched.
"""

from __future__ import annotations

import copy
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Type
import warnings

try:
    import fcntl
except ImportError:  # pragma: no cover - AION targets Linux/Termux.
    fcntl = None


class JsonStorageError(RuntimeError):
    """Base class for safe JSON storage failures."""


class JsonCorruptionError(JsonStorageError):
    """Neither the primary JSON file nor its backup can be trusted."""


class JsonRecoveryWarning(RuntimeWarning):
    """A valid backup was used because the primary store was unavailable."""


_PROCESS_LOCK = threading.RLock()
MAX_JSONL_RECORD_BYTES = 1024 * 1024


def backup_path(path: str | Path) -> Path:
    target = Path(path)
    return target.with_name(target.name + ".bak")


@contextmanager
def _storage_lock(target: Path):
    """Serialize one store across threads and, on Linux/Termux, processes."""

    with _PROCESS_LOCK:
        lock_path = target.with_name(target.name + ".lock")
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(descriptor, "a+b") as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _decode(raw: bytes, *, expected_type: Type[Any] | tuple[Type[Any], ...] | None) -> Any:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise JsonCorruptionError("JSON-хранилище повреждено") from exc
    if expected_type is not None and not isinstance(value, expected_type):
        raise JsonCorruptionError("JSON-хранилище имеет неверный тип корневого значения")
    return value


def _read_validated(path: Path, *, expected_type: Type[Any] | tuple[Type[Any], ...] | None) -> Any:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise JsonStorageError("Не удалось прочитать JSON-хранилище") from exc
    return _decode(raw, expected_type=expected_type)


def _load_json_unlocked(
    target: Path,
    *,
    default_factory: Callable[[], Any],
    expected_type: Type[Any] | tuple[Type[Any], ...] | None = None,
) -> Any:
    backup = backup_path(target)
    if target.exists():
        try:
            return _read_validated(target, expected_type=expected_type)
        except JsonStorageError:
            pass
    elif not backup.exists():
        value = default_factory()
        if expected_type is not None and not isinstance(value, expected_type):
            raise TypeError("default_factory вернул значение неверного типа")
        return copy.deepcopy(value)

    if backup.exists():
        try:
            recovered = _read_validated(backup, expected_type=expected_type)
        except JsonStorageError:
            pass
        else:
            warnings.warn(
                f"Основное JSON-хранилище недоступно; использована резервная копия {target.name}.",
                JsonRecoveryWarning,
                stacklevel=3,
            )
            return recovered

    raise JsonCorruptionError(
        f"Не удалось восстановить JSON-хранилище {target.name}; исходные файлы сохранены."
    )


def load_json(
    path: str | Path,
    *,
    default_factory: Callable[[], Any],
    expected_type: Type[Any] | tuple[Type[Any], ...] | None = None,
) -> Any:
    """Load primary JSON, recover from `.bak`, or fail without data loss."""

    target = Path(path)
    backup = backup_path(target)
    if not target.exists() and not backup.exists() and not target.parent.exists():
        value = default_factory()
        if expected_type is not None and not isinstance(value, expected_type):
            raise TypeError("default_factory вернул значение неверного типа")
        return copy.deepcopy(value)
    target.parent.mkdir(parents=True, exist_ok=True)
    with _storage_lock(target):
        return _load_json_unlocked(
            target,
            default_factory=default_factory,
            expected_type=expected_type,
        )


def _fsync_directory(path: Path) -> None:
    flags = getattr(os, "O_DIRECTORY", 0) | os.O_RDONLY
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _write_temp(parent: Path, name: str, payload: bytes) -> Path:
    descriptor, raw_path = tempfile.mkstemp(
        dir=parent,
        prefix=f".{name}.",
        suffix=".tmp",
    )
    temp_path = Path(raw_path)
    try:
        os.chmod(temp_path, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        return temp_path
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise


def _atomic_replace_bytes(path: Path, payload: bytes) -> None:
    temp_path = _write_temp(path.parent, path.name, payload)
    try:
        os.replace(temp_path, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        _fsync_directory(path.parent)
    except Exception:
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise


def _corrupt_archive_path(path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return path.with_name(f"{path.name}.corrupt-{stamp}")


def _atomic_write_json_unlocked(
    target: Path,
    data: Any,
    *,
    expected_type: Type[Any] | tuple[Type[Any], ...] | None = None,
) -> None:
    if expected_type is not None and not isinstance(data, expected_type):
        raise TypeError("Попытка записать JSON с неверным типом корневого значения")
    try:
        payload = (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise JsonStorageError("Значение не сериализуется в JSON") from exc

    backup = backup_path(target)
    replacement = _write_temp(target.parent, target.name, payload)
    try:
        if target.exists():
            try:
                current = target.read_bytes()
                _decode(current, expected_type=expected_type)
            except (OSError, JsonStorageError):
                # Never overwrite the last known good backup with damaged
                # bytes. Recovery is permitted only if that backup validates.
                if not backup.exists():
                    raise JsonCorruptionError(
                        f"Запись {target.name} остановлена: повреждён оригинал и нет резервной копии."
                    )
                _read_validated(backup, expected_type=expected_type)
                os.replace(target, _corrupt_archive_path(target))
                _fsync_directory(target.parent)
            else:
                _atomic_replace_bytes(backup, current)

        os.replace(replacement, target)
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
        _fsync_directory(target.parent)
    except Exception as exc:
        try:
            replacement.unlink()
        except OSError:
            pass
        if isinstance(exc, JsonStorageError):
            raise
        raise JsonStorageError("Атомарная запись JSON не завершена") from exc


def atomic_write_json(
    path: str | Path,
    data: Any,
    *,
    expected_type: Type[Any] | tuple[Type[Any], ...] | None = None,
) -> None:
    """Atomically replace JSON while retaining a validated previous version."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with _storage_lock(target):
        _atomic_write_json_unlocked(target, data, expected_type=expected_type)


def update_json(
    path: str | Path,
    *,
    default_factory: Callable[[], Any],
    expected_type: Type[Any] | tuple[Type[Any], ...],
    updater: Callable[[Any], Any],
) -> Any:
    """Atomically perform a locked read-modify-write transaction."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with _storage_lock(target):
        current = _load_json_unlocked(
            target,
            default_factory=default_factory,
            expected_type=expected_type,
        )
        updated = updater(copy.deepcopy(current))
        if not isinstance(updated, expected_type):
            raise TypeError("updater вернул значение неверного типа")
        if updated != current:
            _atomic_write_json_unlocked(target, updated, expected_type=expected_type)
        return copy.deepcopy(updated)


def append_jsonl_record(
    path: str | Path,
    record: dict[str, Any],
    *,
    unique_field: str | None = None,
) -> bool:
    """Append one fsynced JSONL record after validating the existing log.

    Returns False when a record with the same `unique_field` value is already
    present. A partial/corrupt existing line blocks the append without modifying
    the log, making interrupted audit writes visible instead of silently skipped.
    """

    if not isinstance(record, dict):
        raise TypeError("JSONL record должен быть объектом")
    if unique_field is not None:
        unique_value = record.get(unique_field)
        if not isinstance(unique_value, str) or not unique_value:
            raise ValueError("Уникальный идентификатор JSONL record отсутствует")
    else:
        unique_value = None

    try:
        payload = (json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise JsonStorageError("Audit record не сериализуется в JSON") from exc
    if len(payload) > MAX_JSONL_RECORD_BYTES:
        raise JsonStorageError("Audit record превышает безопасный лимит размера")

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with _storage_lock(target):
        duplicate = False
        conflict = False

        def find_duplicate(existing: dict[str, Any], _line_number: int) -> None:
            nonlocal duplicate, conflict
            if unique_field is not None and existing.get(unique_field) == unique_value:
                # JSON booleans and numbers must remain distinct: Python treats
                # True == 1, but these are conflicting audit event contents.
                existing_payload = (
                    json.dumps(existing, ensure_ascii=False, sort_keys=True) + "\n"
                ).encode("utf-8")
                if existing_payload == payload:
                    duplicate = True
                else:
                    conflict = True

        _scan_jsonl_unlocked(target, find_duplicate)
        if conflict:
            raise JsonStorageError("Audit ID already exists with different content")
        if duplicate:
            return False

        descriptor = os.open(target, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        try:
            view = memoryview(payload)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("zero-length audit write")
                view = view[written:]
            os.fsync(descriptor)
        except OSError as exc:
            raise JsonStorageError("Audit append не завершён") from exc
        finally:
            os.close(descriptor)
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
        _fsync_directory(target.parent)
        return True


def _scan_jsonl_unlocked(
    target: Path,
    visitor: Callable[[dict[str, Any], int], None],
) -> int:
    if not target.exists():
        return 0
    count = 0
    try:
        with target.open("rb") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                if len(raw_line) > MAX_JSONL_RECORD_BYTES or not raw_line.endswith(b"\n"):
                    raise JsonCorruptionError(
                        f"JSONL log повреждён в строке {line_number}"
                    )
                stripped = raw_line.strip()
                if not stripped:
                    continue
                try:
                    existing = json.loads(stripped.decode("utf-8"))
                except (UnicodeError, json.JSONDecodeError) as exc:
                    raise JsonCorruptionError(
                        f"JSONL log повреждён в строке {line_number}"
                    ) from exc
                if not isinstance(existing, dict):
                    raise JsonCorruptionError(
                        f"JSONL log содержит не-объект в строке {line_number}"
                    )
                visitor(existing, line_number)
                count += 1
    except JsonStorageError:
        raise
    except OSError as exc:
        raise JsonStorageError("Не удалось проверить JSONL log") from exc
    return count


def scan_jsonl_records(
    path: str | Path,
    visitor: Callable[[dict[str, Any], int], None],
) -> int:
    """Validate and inspect a JSONL log while holding its process/file lock."""

    if not callable(visitor):
        raise TypeError("visitor JSONL log должен быть callable")
    target = Path(path)
    if not target.parent.exists() and not target.exists():
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    with _storage_lock(target):
        return _scan_jsonl_unlocked(target, visitor)
