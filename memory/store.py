import hashlib
from datetime import datetime, timezone
from pathlib import Path

from storage.atomic_json import atomic_write_json, load_json, update_json
from security.redaction import SensitiveDataError, redact_sensitive


class DirectPromotionBlocked(PermissionError):
    """Long-term knowledge may only be committed by verified transaction."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

ROOT = Path(__file__).resolve().parent.parent
HISTORY_FILE = ROOT / "knowledge" / "episodic" / "history.json"
LONG_TERM_FILE = ROOT / "knowledge" / "long_term" / "knowledge.json"

def _load_json(file_path: Path) -> list | dict:
    is_history = file_path == HISTORY_FILE or "history" in file_path.name
    expected = list if is_history else dict
    return load_json(file_path, default_factory=expected, expected_type=expected)

def _save_json(file_path: Path, data: list | dict) -> None:
    expected = list if isinstance(data, list) else dict
    atomic_write_json(file_path, data, expected_type=expected)

def add_episodic_event(user_prompt: str, answer: str) -> None:
    safe_user = redact_sensitive(user_prompt)
    safe_answer = redact_sensitive(answer)
    fingerprint = hashlib.sha256(
        f"user:{safe_user.text}\nai:{safe_answer.text}".encode("utf-8")
    ).hexdigest()
    def append_if_new(history: list) -> list:
        for item in history:
            if not isinstance(item, dict):
                continue
            existing = item.get("fingerprint")
            if existing == fingerprint:
                return history
            if (existing is None and item.get("user") == safe_user.text
                    and item.get("ai") == safe_answer.text):
                return history
        history.append({
            "user": safe_user.text,
            "ai": safe_answer.text,
            "fingerprint": fingerprint,
            "redactions": safe_user.count + safe_answer.count,
        })
        return history

    update_json(
        HISTORY_FILE,
        default_factory=list,
        expected_type=list,
        updater=append_if_new,
    )

def get_recent_history(limit: int = 3) -> str:
    history = _load_json(HISTORY_FILE)
    if not history or not isinstance(history, list):
        return "История пуста."
    recent = history[-limit:]
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
