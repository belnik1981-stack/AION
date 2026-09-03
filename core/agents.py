"""
AION Agent Roles (TMAO-style pipeline agents)

Каждая роль — это разное построение prompt для одного и того же
LLM Gateway (core.llm.ask_llm). Новых HTTP-клиентов не создаётся:
провайдер, ключ и timeout остаются едиными для всей системы.
"""

from core.llm import ask_llm

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


def _ask(role: str, content: str) -> str:
    prompt = f"{ROLE_INSTRUCTIONS[role]}\n\n{content}"
    try:
        return ask_llm(prompt).strip()
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
