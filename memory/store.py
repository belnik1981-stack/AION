import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from storage.atomic_json import (
    JsonCorruptionError,
    JsonStorageError,
    append_jsonl_record,
    atomic_write_json,
    load_json,
    scan_jsonl_records,
    update_json,
)
from security.redaction import (
    SensitiveDataError,
    TextSafetyError,
    redact_sensitive,
    redact_structure,
)
from storage.runtime_paths import runtime_root


class DirectPromotionBlocked(PermissionError):
    """Long-term knowledge may only be committed by verified transaction."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = runtime_root(ROOT)
HISTORY_FILE = DATA_ROOT / "knowledge" / "episodic" / "history.json"
EPISODIC_ARCHIVE_FILE = DATA_ROOT / "knowledge" / "episodic" / "archive.jsonl"
LONG_TERM_FILE = DATA_ROOT / "knowledge" / "long_term" / "knowledge.json"
MAX_ACTIVE_EPISODIC_EVENTS = 128
MAX_ACTIVE_EPISODIC_BYTES = 8 * 1024 * 1024
MAX_EPISODIC_EVENT_BYTES = 512 * 1024
MAX_EPISODIC_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024
MAX_EPISODIC_ARCHIVE_RECORDS = 100_000
ARCHIVE_SCHEMA_VERSION = "aion-episodic-archive-v1"


def _valid_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not 1 <= len(value) <= 80:
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _load_json(file_path: Path) -> list | dict:
    is_history = file_path == HISTORY_FILE or "history" in file_path.name
    expected = list if is_history else dict
    return load_json(file_path, default_factory=expected, expected_type=expected)


def _save_json(file_path: Path, data: list | dict) -> None:
    expected = list if isinstance(data, list) else dict
    atomic_write_json(file_path, data, expected_type=expected)


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise JsonCorruptionError("Эпизодическая память содержит неверные данные") from exc


def _fingerprint(user_prompt: str, answer: str) -> str:
    return hashlib.sha256(f"user:{user_prompt}\nai:{answer}".encode("utf-8")).hexdigest()


def _event_size(event: dict[str, Any]) -> int:
    return len(_canonical(event))


def _active_history_size(history: list[dict[str, Any]]) -> int:
    try:
        return len(
            (json.dumps(history, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode(
                "utf-8"
            )
        )
    except (TypeError, ValueError, UnicodeError) as exc:
        raise JsonCorruptionError("Эпизодическая память не сериализуется") from exc


def _normalise_event(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict) or not all(isinstance(key, str) for key in item):
        raise JsonCorruptionError("Эпизодическая память содержит неверную запись")
    if any(redact_sensitive(key).count for key in item):
        raise JsonCorruptionError("Эпизодическая память содержит чувствительный ключ")
    try:
        safe, detected_redactions = redact_structure(item)
    except (TypeError, TextSafetyError) as exc:
        raise JsonCorruptionError("Эпизодическая запись превышает безопасный лимит") from exc
    if not isinstance(safe, dict):
        raise JsonCorruptionError("Эпизодическая память содержит неверную запись")

    user_prompt = safe.get("user", safe.get("prompt"))
    answer = safe.get("ai", safe.get("answer"))
    if not isinstance(user_prompt, str) or not isinstance(answer, str):
        raise JsonCorruptionError("Эпизодическая запись не содержит текст обмена")
    expected_fingerprint = _fingerprint(user_prompt, answer)
    existing_fingerprint = safe.get("fingerprint")
    if existing_fingerprint is not None and existing_fingerprint != expected_fingerprint:
        raise JsonCorruptionError("Fingerprint эпизодической записи не совпадает")

    existing_redactions = safe.get("redactions", 0)
    if (
        isinstance(existing_redactions, bool)
        or not isinstance(existing_redactions, int)
        or existing_redactions < 0
    ):
        raise JsonCorruptionError("Счётчик redaction эпизодической записи неверен")
    recorded_at = safe.get("recorded_at")
    if recorded_at is not None and not _valid_timestamp(recorded_at):
        raise JsonCorruptionError("Время эпизодической записи неверно")

    safe["user"] = user_prompt
    safe["ai"] = answer
    safe["fingerprint"] = expected_fingerprint
    safe["redactions"] = existing_redactions + detected_redactions
    if _event_size(safe) > MAX_EPISODIC_EVENT_BYTES:
        raise JsonStorageError("Эпизодическая запись превышает безопасный лимит")
    return safe


def _normalise_history(history: list[Any]) -> list[dict[str, Any]]:
    normalised = [_normalise_event(item) for item in history]
    fingerprints = [item["fingerprint"] for item in normalised]
    if len(fingerprints) != len(set(fingerprints)):
        raise JsonCorruptionError("Эпизодическая память содержит дубликаты fingerprint")
    return normalised


def _new_event(user_prompt: str, answer: str) -> dict[str, Any]:
    safe_user = redact_sensitive(user_prompt)
    safe_answer = redact_sensitive(answer)
    event = {
        "user": safe_user.text,
        "ai": safe_answer.text,
        "fingerprint": _fingerprint(safe_user.text, safe_answer.text),
        "redactions": safe_user.count + safe_answer.count,
        "recorded_at": _now(),
    }
    if _event_size(event) > MAX_EPISODIC_EVENT_BYTES:
        raise JsonStorageError("Эпизодическая запись превышает безопасный лимит")
    return event


def _archive_record(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": ARCHIVE_SCHEMA_VERSION,
        "fingerprint": event["fingerprint"],
        "archived_at": _now(),
        "event_digest": hashlib.sha256(_canonical(event)).hexdigest(),
        "event": event,
    }


def _scan_archive(target_fingerprint: str | None = None) -> dict[str, Any]:
    path = EPISODIC_ARCHIVE_FILE
    if not path.exists():
        return {
            "found": False,
            "records": 0,
            "bytes": 0,
            "last_fingerprint": None,
            "fingerprints": set(),
        }
    try:
        file_size = path.stat().st_size
    except OSError as exc:
        raise JsonStorageError("Не удалось проверить архив эпизодической памяти") from exc
    if file_size > MAX_EPISODIC_ARCHIVE_BYTES:
        raise JsonStorageError("Архив эпизодической памяти достиг жёсткого лимита")

    found = False
    record_count = 0
    last_fingerprint = None
    fingerprints: set[str] = set()
    required_keys = {
        "schema_version",
        "fingerprint",
        "archived_at",
        "event_digest",
        "event",
    }

    def inspect(record: dict[str, Any], line_number: int) -> None:
        nonlocal found, record_count, last_fingerprint
        if set(record) != required_keys:
            raise JsonCorruptionError(
                f"Архив эпизодической памяти имеет неверную строку {line_number}"
            )
        if record["schema_version"] != ARCHIVE_SCHEMA_VERSION or not _valid_timestamp(
            record["archived_at"]
        ):
            raise JsonCorruptionError(
                f"Архив эпизодической памяти имеет неверную строку {line_number}"
            )
        event = _normalise_event(record["event"])
        fingerprint = event["fingerprint"]
        event_digest = hashlib.sha256(_canonical(event)).hexdigest()
        if (
            record["event"] != event
            or record["fingerprint"] != fingerprint
            or record["event_digest"] != event_digest
            or fingerprint in fingerprints
        ):
            raise JsonCorruptionError(
                f"Целостность архива нарушена в строке {line_number}"
            )
        fingerprints.add(fingerprint)
        record_count += 1
        if record_count > MAX_EPISODIC_ARCHIVE_RECORDS:
            raise JsonStorageError("Архив эпизодической памяти достиг лимита записей")
        last_fingerprint = fingerprint
        if fingerprint == target_fingerprint:
            found = True

    scanned = scan_jsonl_records(path, inspect)
    if scanned != record_count:
        raise JsonCorruptionError("Архив эпизодической памяти имеет неверный счётчик")
    return {
        "found": found,
        "records": record_count,
        "bytes": file_size,
        "last_fingerprint": last_fingerprint,
        "fingerprints": fingerprints,
    }


def _archive_event(event: dict[str, Any]) -> None:
    archive_status = _scan_archive(event["fingerprint"])
    if archive_status["found"]:
        return
    record = _archive_record(event)
    payload_size = len(
        (json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    )
    if archive_status["records"] >= MAX_EPISODIC_ARCHIVE_RECORDS:
        raise JsonStorageError("Архив эпизодической памяти достиг лимита записей")
    if archive_status["bytes"] + payload_size > MAX_EPISODIC_ARCHIVE_BYTES:
        raise JsonStorageError("Архив эпизодической памяти достиг жёсткого лимита")
    append_jsonl_record(
        EPISODIC_ARCHIVE_FILE,
        record,
        unique_field="fingerprint",
    )


def add_episodic_event(user_prompt: str, answer: str) -> None:
    event = _new_event(user_prompt, answer)

    def append_if_new(history: list) -> list:
        active = _normalise_history(history)
        archive_status = _scan_archive(event["fingerprint"])
        active = [
            item
            for item in active
            if item["fingerprint"] not in archive_status["fingerprints"]
        ]
        active_fingerprints = {item["fingerprint"] for item in active}
        if event["fingerprint"] not in active_fingerprints and not archive_status["found"]:
            active.append(event)

        while active and (
            len(active) > MAX_ACTIVE_EPISODIC_EVENTS
            or _active_history_size(active) > MAX_ACTIVE_EPISODIC_BYTES
        ):
            _archive_event(active[0])
            active.pop(0)
        return active

    update_json(
        HISTORY_FILE,
        default_factory=list,
        expected_type=list,
        updater=append_if_new,
    )


def get_episodic_archive_status() -> dict[str, Any]:
    """Return bounded metadata after validating every retained archive record."""

    status = _scan_archive()
    return {
        "status": "ok",
        "records": status["records"],
        "bytes": status["bytes"],
        "last_fingerprint": status["last_fingerprint"],
        "integrity_checked": True,
    }


def get_episodic_memory_status() -> dict[str, Any]:
    """Validate active/archive stores and expose non-content diagnostics."""

    raw_history = _load_json(HISTORY_FILE)
    if not isinstance(raw_history, list):
        raise JsonCorruptionError("Эпизодическая память имеет неверный тип")
    active = _normalise_history(raw_history)
    archive = _scan_archive()
    active_fingerprints = {item["fingerprint"] for item in active}
    overlap = active_fingerprints.intersection(archive["fingerprints"])
    active_bytes = _active_history_size(active)
    if overlap:
        status = "recovery_needed"
    elif (
        len(active) > MAX_ACTIVE_EPISODIC_EVENTS
        or active_bytes > MAX_ACTIVE_EPISODIC_BYTES
    ):
        status = "rotation_required"
    else:
        status = "ok"
    return {
        "status": status,
        "active_records": len(active),
        "active_bytes": active_bytes,
        "archived_records": archive["records"],
        "archive_bytes": archive["bytes"],
        "total_unique_records": len(active) + archive["records"] - len(overlap),
        "recovery_overlap_records": len(overlap),
        "integrity_checked": True,
    }


def get_recent_history(limit: int = 3) -> str:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise ValueError("limit истории должен быть в диапазоне 1..50")
    history = _load_json(HISTORY_FILE)
    if not history or not isinstance(history, list):
        return "История пуста."
    recent = _normalise_history(history)[-limit:]
    formatted = []
    for item in recent:
        if isinstance(item, dict):
            user_msg = item.get("user") or item.get("prompt") or ""
            ai_msg = item.get("ai") or item.get("answer") or ""
            user_msg = redact_sensitive(str(user_msg)).text
            ai_msg = redact_sensitive(str(ai_msg)).text
            if user_msg or ai_msg:
                formatted.append(f"Пользователь: {user_msg}\nAION: {ai_msg}")
    return "\n".join(formatted) if formatted else "История пуста."


def get_long_term_knowledge() -> str:
    knowledge = _load_json(LONG_TERM_FILE)
    if not isinstance(knowledge, dict):
        return "База знаний пуста."
    facts = knowledge.get("learned_lessons", [])
    safe_facts = [redact_sensitive(str(fact)).text for fact in facts]
    return "\n".join([f"- {fact}" for fact in safe_facts]) if safe_facts else "Уроки отсутствуют."


def add_long_term_lesson(lesson: str) -> None:
    raise DirectPromotionBlocked(
        "Прямая запись long-term knowledge запрещена; используйте verification transaction"
    )


def stage_long_term_lesson(lesson: str, promotion_id: str) -> None:
    safe_lesson = redact_sensitive(lesson)
    if safe_lesson.count:
        raise SensitiveDataError(
            "Long-term promotion заблокирован: обнаружены чувствительные данные"
        )

    if not isinstance(promotion_id, str) or not promotion_id.strip():
        raise ValueError("promotion_id обязателен")

    def stage(knowledge: dict) -> dict:
        lessons = knowledge.get("learned_lessons", [])
        if not isinstance(lessons, list):
            raise TypeError("learned_lessons должен быть списком")
        pending = knowledge.get("pending_promotions", {})
        if not isinstance(pending, dict):
            raise TypeError("pending_promotions должен быть объектом")
        existing = pending.get(promotion_id)
        if existing is not None and existing.get("claim") != safe_lesson.text:
            raise ValueError("promotion_id уже связан с другим утверждением")
        if safe_lesson.text not in lessons:
            pending[promotion_id] = {
                "claim": safe_lesson.text,
                "staged_at": _now(),
            }
        knowledge["pending_promotions"] = pending
        return knowledge

    update_json(
        LONG_TERM_FILE,
        default_factory=dict,
        expected_type=dict,
        updater=stage,
    )


def commit_staged_long_term_lesson(lesson: str, promotion_id: str) -> None:
    safe_lesson = redact_sensitive(lesson)
    if safe_lesson.count:
        raise SensitiveDataError("Long-term commit заблокирован: обнаружены чувствительные данные")

    def commit(knowledge: dict) -> dict:
        lessons = knowledge.get("learned_lessons", [])
        pending = knowledge.get("pending_promotions", {})
        if not isinstance(lessons, list) or not isinstance(pending, dict):
            raise TypeError("Некорректная структура long-term knowledge")
        staged = pending.get(promotion_id)
        if staged is None:
            if safe_lesson.text in lessons:
                return knowledge
            raise ValueError("Staged promotion не найден")
        if staged.get("claim") != safe_lesson.text:
            raise ValueError("Staged promotion не соответствует утверждению")
        if safe_lesson.text not in lessons:
            lessons.append(safe_lesson.text)
        pending.pop(promotion_id, None)
        knowledge["learned_lessons"] = lessons
        knowledge["pending_promotions"] = pending
        return knowledge

    update_json(
        LONG_TERM_FILE,
        default_factory=dict,
        expected_type=dict,
        updater=commit,
    )
