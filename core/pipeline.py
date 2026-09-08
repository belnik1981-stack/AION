"""
AION Pipeline (TMAO-style orchestration)

Оркестрация поверх существующего LLM Gateway (core.llm.ask_llm) и
существующей episodic-памяти (memory.store). НЕ изменяет core/engine.py,
core/truth.py, server.py и start_app.sh.

max_iterations берётся из Truth (get_execution_limits) и ограничивает общее
число итераций. CycleGuard дополнительно останавливает повторы и колебания
раньше этого лимита, если новых данных/состояния не появилось.
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
        criticism = "Критика недоступна."

    final_answer = None
    accepted = False
    cycle_info = None

    for iteration in range(1, max_iterations + 1):
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
            break

        is_ok, final_critique = final_critic_check(task, final_answer)
        if is_ok:
            accepted = True
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
            break

        criticism = final_critique

    add_episodic_event(task, final_answer)

    if cycle_info is not None:
        status = "cycle_detected"
    else:
        status = "ok" if accepted else "max_iterations_reached"

    return {
        "status": status,
        "task_type": task_type,
        "plan": plan,
        "analysis": analysis,
        "criticism": criticism,
        "final_answer": final_answer,
        "cycle": cycle_info,
        "cycle_guard": guard.status(),
        "timestamp": datetime.now().isoformat(),
    }
