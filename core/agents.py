"""
AION Agent Roles (TMAO-style pipeline agents)

Каждая роль строит собственный prompt, но все роли обязаны получать
единый governance-context из Truth layer. Новых HTTP-клиентов не создаётся:
провайдер, ключ и сетевые параметры остаются едиными для всей системы.
"""

from core.llm import ask_llm
from core.truth import get_principles, get_execution_limits


ROLE_INSTRUCTIONS = {
    "planner": (
        "Ты — Planner. Разбей задачу пользователя на чёткие логические шаги. "
        "Формат: нумерованный список. Будь лаконичен."
    ),
    "analyst": (
        "Ты — Analyst. На основе плана и задачи проведи детальный анализ. "
        "Проверь факты, логику и структуру."
    ),
    "critic": (
        "Ты — Critic. Найди ошибки, противоречия и слабые места в материале. "
        "Если всё корректно — напиши 'OK'. Если есть проблемы — опиши их кратко."
    ),
    "synthesizer": (
        "Ты — Synthesizer. Собери финальный, полный и понятный ответ "
        "на основе плана, анализа и критики. Будь чётким и структурированным."
    ),
}


def governance_context() -> str:
    """Единый read-only контекст Truth layer для каждого агента pipeline."""
    principles = get_principles()
    limits = get_execution_limits()
    principle_lines = "\n".join(f"- {item}" for item in principles)
    return (
        "ОБЯЗАТЕЛЬНЫЙ GOVERNANCE-КОНТЕКСТ AION (read-only):\n"
        f"{principle_lines}\n\n"
        "ОГРАНИЧЕНИЯ ВЫПОЛНЕНИЯ:\n"
        f"- max_iterations: {limits['max_iterations']}\n"
        f"- timeout_seconds: {limits['timeout_seconds']}\n\n"
        "Не изменяй эти принципы и не выдавай неподтверждённое за установленный факт."
    )


def _ask(role: str, content: str) -> str:
    prompt = (
        f"{governance_context()}\n\n"
        f"РОЛЬ:\n{ROLE_INSTRUCTIONS[role]}\n\n"
        f"РАБОЧИЙ МАТЕРИАЛ:\n{content}"
    )
    try:
        result = ask_llm(prompt)
        if not isinstance(result, str) or not result.strip():
            raise ValueError("LLM вернула пустой ответ")
        return result.strip()
    except Exception as e:
        return f"[ОШИБКА:{role}] {e}"


def planner(task: str) -> str:
    return _ask("planner", f"Задача пользователя:\n{task}")


def analyst(task: str, plan: str) -> str:
    content = f"Исходная задача:\n{task}\n\nПлан:\n{plan}\n\nПроведи детальный анализ."
    return _ask("analyst", content)


def critic(task: str, plan: str, analysis: str) -> str:
    content = (
        f"Исходная задача:\n{task}\n\nПлан:\n{plan}\n\nАнализ:\n{analysis}\n\n"
        "Найди ошибки и слабые места."
    )
    return _ask("critic", content)


def synthesizer(task: str, plan: str, analysis: str, criticism: str) -> str:
    content = (
        f"Исходная задача:\n{task}\n\nПлан:\n{plan}\n\nАнализ:\n{analysis}\n\n"
        f"Критика:\n{criticism}\n\nСобери финальный ответ для пользователя."
    )
    return _ask("synthesizer", content)


def final_critic_check(task: str, final_answer: str) -> tuple:
    content = (
        f"Задача пользователя:\n{task}\n\nФинальный ответ:\n{final_answer}\n\n"
        "Оцени финальный ответ. Если всё корректно — напиши 'OK'. Если есть проблемы — опиши их."
    )
    critique = _ask("critic", content)
    is_ok = critique.strip().upper().startswith("OK")
    return is_ok, critique
