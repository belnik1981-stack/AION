"""
AION Agent Roles (TMAO-style pipeline agents)

Каждая роль строит собственный prompt, но все роли получают единый
read-only governance-context из Truth layer. Для устойчивости pipeline
используются раздельные бюджеты токенов по ролям: промежуточные этапы
должны быть компактными, финальный синтез получает больший бюджет.
"""

import os

from core.llm import ask_llm
from core.truth import get_principles, get_execution_limits


ROLE_INSTRUCTIONS = {
    "planner": (
        "Ты — Planner. Составь краткий рабочий план проверки. "
        "Не пиши длинные объяснения. Максимум 6 пунктов. "
        "Не описывай планируемые шаги как уже фактически выполненные."
    ),
    "analyst": (
        "Ты — Analyst. Проведи содержательный анализ по плану. "
        "Сосредоточься только на аргументах, неопределённостях и проверяемых выводах. "
        "Не утверждай, что pipeline выполнил конкретное число итераций или внешних действий, "
        "если такая телеметрия явно не передана во входном материале."
    ),
    "critic": (
        "Ты — Critic. Найди только реальные ошибки, противоречия, пропуски и обрывы. "
        "Отдельно считай дефектом выдачу лимита max_iterations за число реально выполненных итераций. "
        "Если существенных дефектов нет — ответь ровно 'OK'. "
        "Если есть — максимум 3 коротких пункта без длинных объяснений."
    ),
    "verifier": (
        "Ты — Final Verifier. Верни строго ОДНУ строку и ничего больше. "
        "Разрешены только два формата: 'OK' или "
        "'FAIL: причина 1; причина 2; причина 3'. "
        "Считай существенным дефектом ложное утверждение о фактически выполненных итерациях, "
        "внешних действиях или иной телеметрии, которой нет во входном материале. "
        "Не более 60 слов. Никаких заголовков, цитат, таблиц и повторения ответа пользователя."
    ),
    "synthesizer": (
        "Ты — Synthesizer. Сформируй завершённый финальный ответ. "
        "Исправь замечания Critic. Не копируй промежуточные тексты целиком. "
        "Не называй max_iterations числом фактически выполненных итераций и не придумывай телеметрию. "
        "Ответ должен иметь явный итоговый вывод и не обрываться."
    ),
}


def _budget(name: str, default: int) -> int:
    return max(64, int(os.getenv(name, default)))


ROLE_BUDGETS = {
    "planner": lambda: _budget("AION_PLANNER_TOKENS", 220),
    "analyst": lambda: _budget("AION_ANALYST_TOKENS", 420),
    "critic": lambda: _budget("AION_CRITIC_TOKENS", 260),
    "verifier": lambda: _budget("AION_FINAL_CRITIC_TOKENS", 700),
    "synthesizer": lambda: _budget("AION_SYNTHESIZER_TOKENS", 700),
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
        "ПРАВИЛО НАБЛЮДАЕМОСТИ:\n"
        "- max_iterations — это верхний предел, а не доказательство фактически выполненного числа итераций.\n"
        "- Не утверждай факт внешнего действия, записи, проверки или выполнения шага без явной телеметрии во входном материале.\n\n"
        "Не изменяй эти принципы и не выдавай неподтверждённое за установленный факт."
    )


def _ask(role: str, content: str) -> str:
    prompt = (
        f"{governance_context()}\n\n"
        f"РОЛЬ:\n{ROLE_INSTRUCTIONS[role]}\n\n"
        f"РАБОЧИЙ МАТЕРИАЛ:\n{content}"
    )
    try:
        result = ask_llm(prompt, max_tokens=ROLE_BUDGETS[role]())
        if not isinstance(result, str) or not result.strip():
            raise ValueError("LLM вернула пустой ответ")
        return result.strip()
    except Exception as e:
        return f"[ОШИБКА:{role}] {e}"


def planner(task: str) -> str:
    return _ask("planner", f"Задача пользователя:\n{task}")


def analyst(task: str, plan: str) -> str:
    content = (
        f"Исходная задача:\n{task}\n\n"
        f"Краткий план:\n{plan}\n\n"
        "Дай анализ без повторного переписывания плана."
    )
    return _ask("analyst", content)


def critic(task: str, plan: str, analysis: str) -> str:
    content = (
        f"Исходная задача:\n{task}\n\n"
        f"План:\n{plan}\n\n"
        f"Анализ:\n{analysis}\n\n"
        "Укажи только существенные дефекты, которые нужно исправить в финальном ответе."
    )
    return _ask("critic", content)


def synthesizer(task: str, plan: str, analysis: str, criticism: str) -> str:
    content = (
        f"Исходная задача:\n{task}\n\n"
        f"План:\n{plan}\n\n"
        f"Анализ:\n{analysis}\n\n"
        f"Замечания Critic:\n{criticism}\n\n"
        "Сформируй самостоятельный завершённый ответ. Не копируй служебные заголовки pipeline."
    )
    return _ask("synthesizer", content)


def final_critic_check(task: str, final_answer: str) -> tuple:
    """Финальная проверка отделена от обычного Critic и обязана быть компактной."""
    content = (
        f"Задача пользователя:\n{task}\n\n"
        f"Финальный ответ:\n{final_answer}\n\n"
        "Проверь только существенные дефекты: незавершённость/обрыв, несоответствие задаче, "
        "критическую логическую ошибку, потерю существенной неопределённости, "
        "а также неподтверждённые утверждения о фактических итерациях или действиях. "
        "Не переписывай ответ и не объясняй критерии."
    )
    verdict = _ask("verifier", content)
    if verdict.startswith("[ОШИБКА"):
        return False, verdict

    normalized = verdict.strip()
    upper = normalized.upper()
    if upper == "OK":
        return True, "OK"
    if upper.startswith("FAIL:") or upper == "FAIL":
        return False, normalized

    return False, f"FAIL: Final Verifier нарушил формат: {normalized[:240]}"
