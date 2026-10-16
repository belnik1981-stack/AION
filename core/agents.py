"""
AION Agent Roles (TMAO-style pipeline agents)

Каждая роль строит собственный prompt, получает единый read-only
Governance-контекст и может быть запущена на явно выбранной модели.
"""

import os

from core.llm import ask_llm
from providers.base import ProviderTruncatedError
from core.truth import get_principles, get_execution_limits


ROLE_INSTRUCTIONS = {
    "planner": (
        "Ты — Planner. Составь краткий рабочий план проверки. "
        "Максимум 3 коротких пункта, до 80 слов. "
        "Не описывай планируемые шаги как уже фактически выполненные."
    ),
    "analyst": (
        "Ты — Analyst. Проведи содержательный анализ по плану. "
        "Максимум 6 кратких предложений. Выдели аргументы, неопределённости и проверяемые выводы. "
        "Не утверждай, что pipeline выполнил конкретное число итераций или внешних действий, "
        "если такая телеметрия явно не передана во входном материале."
    ),
    "critic": (
        "Ты — Critic. Найди только реальные ошибки, противоречия, пропуски и обрывы. "
        "Если существенных дефектов нет — ответь ровно 'OK'. "
        "Если есть — максимум 3 коротких пункта, не более 60 слов."
    ),
    "verifier": (
        "Ты — Final Verifier. Верни строго ОДНУ строку и ничего больше. "
        "Разрешены только два формата: 'OK' или "
        "'FAIL: причина 1; причина 2; причина 3'. Не более 60 слов."
    ),
    "synthesizer": (
        "Ты — Synthesizer. Сформируй завершённый финальный ответ. "
        "Исправь замечания Critic. Не копируй промежуточные тексты целиком. "
        "Ответ должен иметь явный итоговый вывод, 4–8 коротких предложений и не обрываться."
    ),
}


def _ceiling() -> int:
    # A hard per-role cap prevents accidentally unbounded response budgets.
    ceiling = int(os.getenv("AION_ROLE_TOKEN_CEILING", "4096"))
    if ceiling < 128 or ceiling > 8192:
        raise ValueError("AION_ROLE_TOKEN_CEILING должен быть в диапазоне 128..8192")
    return ceiling


def _budget(name: str, default: int) -> int:
    requested = int(os.getenv(name, str(default)))
    if requested <= 0:
        raise ValueError(f"{name} должен быть положительным")
    return min(max(64, requested), _ceiling())


ROLE_BUDGETS = {
    "planner": lambda: _budget("AION_PLANNER_TOKENS", 512),
    "analyst": lambda: _budget("AION_ANALYST_TOKENS", 900),
    "critic": lambda: _budget("AION_CRITIC_TOKENS", 1600),
    "verifier": lambda: _budget("AION_FINAL_CRITIC_TOKENS", 1200),
    "synthesizer": lambda: _budget("AION_SYNTHESIZER_TOKENS", 1400),
}


def governance_context() -> str:
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


def _ask(role: str, content: str, model: str | None = None) -> str:
    prompt = (
        f"{governance_context()}\n\n"
        f"РОЛЬ:\n{ROLE_INSTRUCTIONS[role]}\n\n"
        f"РАБОЧИЙ МАТЕРИАЛ:\n{content}"
    )
    try:
        budget = ROLE_BUDGETS[role]()
        try:
            result = ask_llm(prompt, max_tokens=budget, model=model)
        except ProviderTruncatedError:
            # Exactly one bounded retry for a truncated answer, never for HTTP 429.
            # Never treat the incomplete first response as successful output.
            enabled = os.getenv("AION_TRUNCATION_RETRY", "1").strip().lower() in ("1", "true", "yes", "on")
            next_budget = min(_ceiling(), max(budget + 256, budget * 2))
            if not enabled or next_budget <= budget:
                raise
            result = ask_llm(prompt, max_tokens=next_budget, model=model)
        if not isinstance(result, str) or not result.strip():
            raise ValueError("LLM вернула пустой ответ")
        return result.strip()
    except Exception as e:
        return f"[ОШИБКА:{role}] {e}"


def planner(task: str, model: str | None = None) -> str:
    return _ask("planner", f"Задача пользователя:\n{task}", model=model)


def analyst(task: str, plan: str, model: str | None = None) -> str:
    content = f"Исходная задача:\n{task}\n\nКраткий план:\n{plan}\n\nДай анализ без повторного переписывания плана."
    return _ask("analyst", content, model=model)


def critic(task: str, plan: str, analysis: str, model: str | None = None) -> str:
    content = (
        f"Исходная задача:\n{task}\n\nПлан:\n{plan}\n\nАнализ:\n{analysis}\n\n"
        "Укажи только существенные дефекты, которые нужно исправить в финальном ответе."
    )
    return _ask("critic", content, model=model)


def synthesizer(task: str, plan: str, analysis: str, criticism: str, model: str | None = None) -> str:
    content = (
        f"Исходная задача:\n{task}\n\nПлан:\n{plan}\n\nАнализ:\n{analysis}\n\n"
        f"Замечания Critic:\n{criticism}\n\nСформируй самостоятельный завершённый ответ."
    )
    return _ask("synthesizer", content, model=model)


def final_critic_check(task: str, final_answer: str, model: str | None = None) -> tuple:
    content = (
        f"Задача пользователя:\n{task}\n\nФинальный ответ:\n{final_answer}\n\n"
        "Проверь только существенные дефекты: незавершённость, несоответствие задаче, "
        "критическую логическую ошибку или потерю существенной неопределённости."
    )
    verdict = _ask("verifier", content, model=model)
    if verdict.startswith("[ОШИБКА"):
        return False, verdict
    normalized = verdict.strip()
    upper = normalized.upper()
    if upper == "OK":
        return True, "OK"
    if upper.startswith("FAIL:") or upper == "FAIL":
        return False, normalized
    return False, f"FAIL: Final Verifier нарушил формат: {normalized[:240]}"
