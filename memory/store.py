"""Private mutable memory store, physically separate from Truth."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DIR = Path(
    os.getenv("AION_RUNTIME_DIR", str(ROOT / "runtime"))
).expanduser()
HISTORY_FILE = Path(
    os.getenv(
        "AION_EPISODIC_FILE",
        str(RUNTIME_DIR / "knowledge" / "episodic" / "history.json"),
    )
).expanduser()
LONG_TERM_FILE = Path(
    os.getenv(
        "AION_LONG_TERM_FILE",
        str(RUNTIME_DIR / "knowledge" / "long_term" / "knowledge.json"),
    )
).expanduser()


def _load_json(file_path: Path) -> list | dict:
    if not file_path.exists():
        return [] if file_path == HISTORY_FILE else {}
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [] if file_path == HISTORY_FILE else {}


def _save_json(file_path: Path, data: list | dict) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        file_path.parent.chmod(0o700)
    except OSError:
        pass
    temporary = file_path.with_name(f".{file_path.name}.tmp")
    temporary.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    try:
        temporary.chmod(0o600)
    except OSError:
        pass
    os.replace(temporary, file_path)


def add_episodic_event(
    user_prompt: str,
    answer: str,
    *,
    status: str = "observed",
) -> None:
    history = _load_json(HISTORY_FILE)
    if not isinstance(history, list):
        history = []
    history.append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "user": user_prompt,
            "ai": answer,
        }
    )
    _save_json(HISTORY_FILE, history)


def get_recent_history(limit: int = 3) -> str:
    history = _load_json(HISTORY_FILE)
    if not history or not isinstance(history, list):
        return "История пуста."
    formatted = []
    for item in history[-max(0, limit) :]:
        if isinstance(item, dict):
            user_msg = item.get("user") or item.get("prompt") or ""
            ai_msg = item.get("ai") or item.get("answer") or ""
            if user_msg or ai_msg:
                formatted.append(f"Пользователь: {user_msg}\nAION: {ai_msg}")
    return "\n".join(formatted) if formatted else "История пуста."


def get_long_term_knowledge() -> str:
    knowledge = _load_json(LONG_TERM_FILE)
    if not isinstance(knowledge, dict):
        return "База знаний пуста."
    facts = knowledge.get("learned_lessons", [])
    return "\n".join(f"- {fact}" for fact in facts) if facts else "Уроки отсутствуют."


def add_long_term_lesson(lesson: str) -> None:
    knowledge = _load_json(LONG_TERM_FILE)
    if not isinstance(knowledge, dict):
        knowledge = {}
    lessons = knowledge.get("learned_lessons", [])
    if not isinstance(lessons, list):
        lessons = []
    if lesson not in lessons:
        lessons.append(lesson)
    knowledge["learned_lessons"] = lessons
    _save_json(LONG_TERM_FILE, knowledge)
