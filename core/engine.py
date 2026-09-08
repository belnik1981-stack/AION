"""AION single-cycle engine with bounded execution and private runtime state."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from core.audit_log import append_audit_event, fingerprint_text
from core.execution import ExecutionBudget, validate_text
from core.llm import ask_llm
from core.truth import get_execution_limits, get_principles

ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DIR = Path(
    os.getenv("AION_RUNTIME_DIR", str(ROOT / "runtime"))
).expanduser()
STATE_FILE = Path(
    os.getenv("AION_STATE_FILE", str(RUNTIME_DIR / "state.json"))
).expanduser()


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        STATE_FILE.parent.chmod(0o700)
    except OSError:
        pass
    temporary = STATE_FILE.with_name(f".{STATE_FILE.name}.tmp")
    temporary.write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    try:
        temporary.chmod(0o600)
    except OSError:
        pass
    os.replace(temporary, STATE_FILE)


def build_prompt(state: dict, user_input: str | None = None) -> str:
    principles = get_principles()
    limits = get_execution_limits()
    prompt = f"Системные принципы:\n{principles}\nОграничения:\n{limits}\n"

    if user_input is not None:
        task = validate_text(user_input, limits["max_input_chars"], "user input")
        prompt += f"\nЗадача от пользователя:\n{task}\n"
    else:
        previous = str(state.get("last_answer", "")).strip()
        if previous:
            previous = previous[-limits["max_input_chars"] :]
            prompt += f"\nПредыдущий контекст:\n{previous}\n"

    return validate_text(prompt, limits["max_prompt_chars"], "prompt")


def run_cycle(user_input: str) -> dict:
    limits = get_execution_limits()
    user_input = validate_text(
        user_input,
        limits["max_input_chars"],
        "user input",
    )
    budget = ExecutionBudget(
        max_api_calls=1,
        max_total_seconds=limits["max_total_seconds"],
    )
    state = load_state()
    prompt = build_prompt(state, user_input)
    event_id = uuid4().hex
    task_hash = fingerprint_text(user_input)

    append_audit_event(
        "single_cycle_started",
        event_id=event_id,
        task_hash=task_hash,
    )
    try:
        answer = ask_llm(prompt, budget=budget)
    except Exception as exc:
        append_audit_event(
            "single_cycle_failed",
            event_id=event_id,
            error_type=type(exc).__name__,
            execution=budget.snapshot(),
        )
        raise

    state["last_run"] = datetime.now(timezone.utc).isoformat()
    state["last_user_prompt"] = user_input
    state["last_answer"] = answer
    state["status"] = "idle"
    state["execution"] = budget.snapshot()
    save_state(state)
    append_audit_event(
        "single_cycle_completed",
        event_id=event_id,
        execution=budget.snapshot(),
    )
    return state
