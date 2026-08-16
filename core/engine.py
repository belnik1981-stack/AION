"""
AION CORE ENGINE
"""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path

from core.llm import ask_llm
from core.truth import get_execution_limits, get_principles

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

def build_prompt(state: dict, user_input: str | None = None) -> str:
    principles = get_principles()
    limits = get_execution_limits()
    prompt = f"Системные принципы:\n{principles}\nОграничения:\n{limits}\n"
    if user_input:
        prompt += f"\nЗадача от пользователя:\n{user_input}\n"
    elif "last_answer" in state:
        prompt += f"\nПредыдущий контекст:\n{state['last_answer']}\n"
    return prompt

def run_cycle(user_input: str | None = None) -> dict:
    state = load_state()
    prompt = build_prompt(state, user_input)
    answer = ask_llm(prompt)
    
    state["last_run"] = datetime.now().isoformat()
    if user_input:
        state["last_user_prompt"] = user_input
    state["last_answer"] = answer
    state["status"] = "idle"
    
    save_state(state)
    return state
