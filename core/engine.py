"""
AION CORE ENGINE
"""
from __future__ import annotations
from datetime import datetime
from pathlib import Path

from core.llm import ask_llm
from core.runtime_budget import ExecutionBudget, configured_call_limit, use_budget
from core.truth import get_execution_limits, get_principles
from security.redaction import redact_sensitive, redact_structure
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
        prompt += f"\nЗадача от пользователя:\n{redact_sensitive(user_input).text}\n"
    elif "last_answer" in state:
        prompt += f"\nПредыдущий контекст:\n{redact_sensitive(str(state['last_answer'])).text}\n"
    return prompt

def run_cycle(user_input: str | None = None) -> dict:
    state = load_state()
    prompt = build_prompt(state, user_input)
    limits = get_execution_limits()
    budget = ExecutionBudget(
        timeout_seconds=float(limits["timeout_seconds"]),
        max_calls=configured_call_limit(),
    )
    with use_budget(budget):
        answer = ask_llm(prompt)
    safe_answer = redact_sensitive(answer).text
    
    state["last_run"] = datetime.now().isoformat()
    if user_input:
        state["last_user_prompt"] = redact_sensitive(user_input).text
    state["last_answer"] = safe_answer
    state["status"] = "idle"
    state["runtime_budget"] = budget.snapshot()
    
    safe_state, _ = redact_structure(state)
    save_state(safe_state)
    return safe_state
