"""Bounded role prompts for the AION trial pipeline."""
from __future__ import annotations

from core.execution import ExecutionBudget, ExecutionLimitError
from core.llm import ask_llm
from providers.base import ProviderError

ROLE_INSTRUCTIONS = {
    "planner": (
        "Ты — Planner. Разбей задачу пользователя на чёткие логические шаги. "
        "Формат: нумерованный список. Будь лаконичен."
    ),
    "analyst": (
        "Ты — Analyst. На основе плана и задачи проведи детальный анализ. "
        "Отделяй проверенные факты от предположений."
    ),
    "critic": (
        "Ты — Critic. Найди ошибки, противоречия и слабые места. "
        "Если всё корректно — напиши 'OK'."
    ),
    "synthesizer": (
        "Ты — Synthesizer. Собери итоговый ответ на основе плана, анализа "
        "и критики. Не превращай неподтверждённые утверждения в факты."
    ),
}


def _ask(role: str, content: str, budget: ExecutionBudget) -> str:
    prompt = f"{ROLE_INSTRUCTIONS[role]}\n\n{content}"
    try:
        return ask_llm(prompt, budget=budget).strip()
    except ExecutionLimitError:
        raise
    except ProviderError as exc:
        return f"[ОШИБКА:{role}] {exc}"
    except Exception:
        return f"[ОШИБКА:{role}] internal_error"


def planner(task: str, budget: ExecutionBudget) -> str:
    return _ask("planner", f"Задача пользователя:\n{task}", budget)


def analyst(task: str, plan: str, budget: ExecutionBudget) -> str:
    content = f"Исходная задача:\n{task}\n\nПлан:\n{plan}\n\nПроведи анализ."
    return _ask("analyst", content, budget)


def critic(task: str, plan: str, analysis: str, budget: ExecutionBudget) -> str:
    content = (
        f"Исходная задача:\n{task}\n\nПлан:\n{plan}\n\n"
        f"Анализ:\n{analysis}\n\nНайди ошибки и слабые места."
    )
    return _ask("critic", content, budget)


def synthesizer(
    task: str,
    plan: str,
    analysis: str,
    criticism: str,
    budget: ExecutionBudget,
) -> str:
    content = (
        f"Исходная задача:\n{task}\n\nПлан:\n{plan}\n\n"
        f"Анализ:\n{analysis}\n\nКритика:\n{criticism}\n\n"
        "Собери финальный ответ для пользователя."
    )
    return _ask("synthesizer", content, budget)


def final_critic_check(
    task: str,
    final_answer: str,
    budget: ExecutionBudget,
) -> tuple[bool, str]:
    content = (
        f"Задача пользователя:\n{task}\n\nФинальный ответ:\n{final_answer}\n\n"
        "Оцени финальный ответ. Если всё корректно — напиши 'OK'. "
        "Если есть проблемы — опиши их."
    )
    critique = _ask("critic", content, budget)
    return critique.strip().upper().startswith("OK"), critique
