"""
AION CORE ENGINE
"""
from __future__ import annotations
from datetime import datetime
from pathlib import Path

from core.llm import ask_llm
from core.truth import get_execution_limits, get_principles
from storage.atomic_json import atomic_write_json, load_json

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "state.json"

def load_state() -> dict:
    return load_json(STATE_FILE, default_factory=dict, expected_type=dict)

def save_state(state: dict) -> None:
    atomic_write_json(STATE_FILE, state, expected_type=dict)

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
