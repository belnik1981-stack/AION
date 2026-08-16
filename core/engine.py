"""
AION CORE ENGINE

Ответственность:
- загрузить состояние;
- загрузить системную Truth;
- построить запрос;
- выполнить один цикл;
- сохранить состояние.

Engine НЕ изменяет Truth.
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
    """Загрузить состояние AION."""

    if not STATE_FILE.exists():
        return {}

    try:
        data = json.loads(
            STATE_FILE.read_text(
                encoding="utf-8"
            )
        )

        return data if isinstance(data, dict) else {}

    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    """Сохранить состояние AION."""

    STATE_FILE.write_text(
        json.dumps(
            state,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def build_prompt(state: dict) -> str:
    """Построить запрос для LLM."""

    principles = get_principles()
    limits = get_execution_limits()

    principles_text = "\n".join(
        f"- {item}"
        for item in principles
    )

    return (
        "Ты являешься исполнительным ядром AION.\n\n"

        "АРХИТЕКТУРНЫЕ ПРИНЦИПЫ:\n"
        f"{principles_text}\n\n"

        "ЛИМИТЫ:\n"
        f"- max_iterations: "
        f"{limits['max_iterations']}\n"
        f"- timeout_seconds: "
        f"{limits['timeout_seconds']}\n\n"

        "ТЕКУЩЕЕ СОСТОЯНИЕ:\n"
        f"{json.dumps(state, ensure_ascii=False, indent=2)}\n\n"

        "ЗАДАЧА:\n"
        "Предложи одно следующее рациональное действие."
    )


def run_cycle() -> str:
    """
    Выполнить один цикл AION.
    """

    state = load_state()
    limits = get_execution_limits()

    state["status"] = "running"
    state["architecture"] = "truth_controlled"
    state["max_iterations"] = limits["max_iterations"]
    state["timeout_seconds"] = limits["timeout_seconds"]

    save_state(state)

    prompt = build_prompt(state)

    answer = ask_llm(prompt)

    state["last_run"] = datetime.now().isoformat()
    state["last_answer"] = answer
    state["status"] = "idle"

    save_state(state)

    print()
    print("=== AION ===")
    print(answer)
    print("============")

    return answer


if __name__ == "__main__":
    run_cycle()
