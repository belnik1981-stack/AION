"""
AION Pipeline (TMAO-style orchestration)

Оркестрация поверх существующего LLM Gateway и episodic-памяти.
max_iterations берётся из Truth и жёстко ограничивает цикл доработки.
Pipeline также останавливается при отсутствии прогресса, чтобы исключить
бессмысленное повторение одинакового финального ответа.
"""

from datetime import datetime

from core.truth import get_execution_limits
from core.agents import planner, analyst, critic, synthesizer, final_critic_check
from memory.store import add_episodic_event


def router(task: str) -> str:
    task_lower = task.lower()
    if any(w in task_lower for w in ["проанализируй", "анализ", "сравни", "оцени"]):
        return "analysis"
    if any(w in task_lower for w in ["план", "шаги", "как сделать", "разработай"]):
        return "planning"
    return "general"


def _norm(text: str | None) -> str:
    return " ".join((text or "").lower().split())


def run_pipeline(task: str) -> dict:
    limits = get_execution_limits()
    max_iterations = int(limits.get("max_iterations", 2))
    task_type = router(task)

    plan = planner(task)
    if plan.startswith("[ОШИБКА"):
        return {"status": "error", "stage": "planner", "detail": plan}

    analysis = analyst(task, plan)
    if analysis.startswith("[ОШИБКА"):
        return {"status": "error", "stage": "analyst", "detail": analysis}

    criticism = critic(task, plan, analysis)
    if criticism.startswith("[ОШИБКА"):
        return {"status": "error", "stage": "critic", "detail": criticism}

    final_answer = None
    accepted = False
    previous_final = None
    stop_reason = "max_iterations_reached"
    iterations_used = 0

    for iteration in range(1, max_iterations + 1):
        iterations_used = iteration
        final_answer = synthesizer(task, plan, analysis, criticism)
        if final_answer.startswith("[ОШИБКА"):
            return {"status": "error", "stage": "synthesizer", "detail": final_answer}

        if previous_final is not None and _norm(final_answer) == _norm(previous_final):
            stop_reason = "stalled_no_progress"
            break

        is_ok, final_critique = final_critic_check(task, final_answer)
        if final_critique.startswith("[ОШИБКА"):
            return {"status": "error", "stage": "final_critic", "detail": final_critique}

        if is_ok:
            accepted = True
            criticism = "OK"
            stop_reason = "accepted"
            break

        previous_final = final_answer
        criticism = final_critique

    if final_answer:
        add_episodic_event(task, final_answer)

    return {
        "status": "ok" if accepted else stop_reason,
        "task_type": task_type,
        "iterations_used": iterations_used,
        "plan": plan,
        "analysis": analysis,
        "criticism": criticism,
        "final_answer": final_answer,
        "timestamp": datetime.now().isoformat(),
    }
