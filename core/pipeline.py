"""
AION Pipeline (TMAO-style orchestration)

Оркестрация поверх существующего LLM Gateway (core.llm.ask_llm) и
существующей episodic-памяти (memory.store). НЕ изменяет core/engine.py,
core/truth.py, server.py и start_app.sh.

max_iterations берётся из Truth (get_execution_limits) и ограничивает общее
число итераций. CycleGuard дополнительно останавливает повторы и колебания
раньше этого лимита, если новых данных/состояния не появилось.
Оркестрация поверх существующего LLM Gateway и episodic-памяти.
max_iterations берётся из Truth и жёстко ограничивает цикл доработки.
Pipeline также останавливается при отсутствии прогресса, чтобы исключить
бессмысленное повторение одинакового финального ответа.
"""

from datetime import datetime

from core.truth import get_execution_limits
from core.agents import planner, analyst, critic, synthesizer, final_critic_check
from core.cycle_guard import CycleGuard
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
    guard = CycleGuard()

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
    cycle_info = None

    previous_final = None
    stop_reason = "max_iterations_reached"
    iterations_used = 0

    for iteration in range(1, max_iterations + 1):
        iterations_used = iteration
        final_answer = synthesizer(task, plan, analysis, criticism)
        if final_answer.startswith("[ОШИБКА"):
            return {"status": "error", "stage": "synthesizer", "detail": final_answer}

        # Observe the candidate answer before asking another critic turn. If the
        # same candidate state has already appeared, a further retry would add no
        # new information and is stopped immediately.
        observed = guard.observe("synthesizer", final_answer)
        if observed.cycle_detected:
            cycle_info = {
                "type": observed.cycle_type,
                "reason": observed.reason,
                "occurrences": observed.occurrences,
                "iteration": iteration,
            }
            stop_reason = "cycle_detected"
            break
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

        # Critique itself may oscillate even while wording of answers changes.
        critique_observed = guard.observe("critic", final_critique)
        if critique_observed.cycle_detected:
            cycle_info = {
                "type": critique_observed.cycle_type,
                "reason": critique_observed.reason,
                "occurrences": critique_observed.occurrences,
                "iteration": iteration,
            }
            criticism = final_critique
            stop_reason = "cycle_detected"
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
        "cycle": cycle_info,
        "cycle_guard": guard.status(),
        "timestamp": datetime.now().isoformat(),
    }
