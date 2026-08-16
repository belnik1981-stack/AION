from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path

from core.llm import ask_llm
from core.truth import get_execution_limits, get_principles
from memory.store import (
    add_episodic_event,
    get_recent_history,
    get_long_term_knowledge,
    add_long_term_lesson,
)

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "state.json"

def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

def build_prompt(user_input: str | None = None) -> str:
    principles = get_principles()
    limits = get_execution_limits()
    recent_history = get_recent_history(limit=3)
    long_term_knowledge = get_long_term_knowledge()

    prompt = f"""СИСТЕМНЫЕ ПРИНЦИПЫ:
{principles}

ОГРАНИЧЕНИЯ:
{limits}

ДОЛГОСРОЧНЫЙ ОПЫТ И УРОКИ (LONG-TERM MEMORY):
{long_term_knowledge}

ПОСЛЕДНИЙ КОНТЕКСТ ДИАЛОГА (EPISODIC MEMORY):
{recent_history}
"""
    if user_input:
        prompt += f"\nТЕКУЩАЯ ЗАДАЧА ОТ ПОЛЬЗОВАТЕЛЯ:\n{user_input}\n"

    return prompt

def reflect_and_learn(user_input: str, answer: str) -> None:
    """Шаг самообучения: извлечение инсайтов после цикла."""
    reflection_prompt = f"""Проанализируй выполненное действие.
Задача: {user_input}
Ответ: {answer}

Сформулируй 1 короткое правило или урок на будущее для накопительной базы знаний AION. 
Отвечай ТОЛЬКО текстом самого урока (одно предложение), без вводных слов.
"""
    try:
        lesson = ask_llm(reflection_prompt).strip()
        if lesson and len(lesson) > 5:
            add_long_term_lesson(lesson)
    except Exception as e:
        print(f"[REFLECTION ERROR] {e}")

def run_cycle(user_input: str | None = None) -> dict:
    state = load_state()
    prompt = build_prompt(user_input)
    answer = ask_llm(prompt)

    if user_input:
        add_episodic_event(user_input, answer)
        reflect_and_learn(user_input, answer)

    state["last_run"] = datetime.now().isoformat()
    if user_input:
        state["last_user_prompt"] = user_input
    state["last_answer"] = answer
    state["status"] = "idle"

    save_state(state)
    return state
