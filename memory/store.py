import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HISTORY_FILE = ROOT / "knowledge" / "episodic" / "history.json"
LONG_TERM_FILE = ROOT / "knowledge" / "long_term" / "knowledge.json"

def _load_json(file_path: Path) -> list | dict:
    if not file_path.exists():
        return [] if "history" in str(file_path) else {}
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except Exception:
        return [] if "history" in str(file_path) else {}

def _save_json(file_path: Path, data: list | dict) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def add_episodic_event(user_prompt: str, answer: str) -> None:
    history = _load_json(HISTORY_FILE)
    if not isinstance(history, list):
        history = []
    history.append({"user": user_prompt, "ai": answer})
    _save_json(HISTORY_FILE, history)

def get_recent_history(limit: int = 3) -> str:
    history = _load_json(HISTORY_FILE)
    if not history or not isinstance(history, list):
        return "История пуста."
    recent = history[-limit:]
    return "\n".join([f"Пользователь: {item['user']}\nAION: {item['ai']}" for item in recent])

def get_long_term_knowledge() -> str:
    knowledge = _load_json(LONG_TERM_FILE)
    if not knowledge or not isinstance(knowledge, dict):
        return "База знаний пуста."
    facts = knowledge.get("learned_lessons", [])
    return "\n".join([f"- {fact}" for fact in facts]) if facts else "Уроки отсутствуют."

def add_long_term_lesson(lesson: str) -> None:
    knowledge = _load_json(LONG_TERM_FILE)
    if not isinstance(knowledge, dict):
        knowledge = {}
    lessons = knowledge.get("learned_lessons", [])
    if lesson not in lessons:
        lessons.append(lesson)
    knowledge["learned_lessons"] = lessons
    _save_json(LONG_TERM_FILE, knowledge)
