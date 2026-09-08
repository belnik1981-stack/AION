"""Bounded Planner/Analyst/Critic/Synthesizer trial pipeline."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from core.agents import analyst, critic, final_critic_check, planner, synthesizer
from core.audit_log import append_audit_event, fingerprint_text
from core.execution import ExecutionBudget, ExecutionLimitError, validate_text
from core.truth import get_execution_limits
from memory.store import add_episodic_event


def router(task: str) -> str:
    task_lower = task.lower()
    if any(word in task_lower for word in ("проанализируй", "анализ", "сравни", "оцени")):
        return "analysis"
    if any(word in task_lower for word in ("план", "шаги", "как сделать", "разработай")):
        return "planning"
    return "general"


def _complete(
    result: dict,
    budget: ExecutionBudget,
    event_id: str,
) -> dict:
    result["execution"] = budget.snapshot()
    result["timestamp"] = datetime.now(timezone.utc).isoformat()
    append_audit_event(
        "pipeline_completed",
        event_id=event_id,
        status=result.get("status", "unknown"),
        execution=budget.snapshot(),
    )
    return result


def run_pipeline(task: str) -> dict:
    limits = get_execution_limits()
    task = validate_text(task, limits["max_input_chars"], "task")
    budget = ExecutionBudget(
        max_api_calls=limits["max_api_calls"],
        max_total_seconds=limits["max_total_seconds"],
    )
    event_id = uuid4().hex
    append_audit_event(
        "pipeline_started",
        event_id=event_id,
        task_hash=fingerprint_text(task),
    )

    try:
        task_type = router(task)
        plan = planner(task, budget)
        if plan.startswith("[ОШИБКА"):
            return _complete(
                {"status": "error", "stage": "planner", "detail": plan},
                budget,
                event_id,
            )

        analysis = analyst(task, plan, budget)
        if analysis.startswith("[ОШИБКА"):
            return _complete(
                {"status": "error", "stage": "analyst", "detail": analysis},
                budget,
                event_id,
            )

        criticism = critic(task, plan, analysis, budget)
        if criticism.startswith("[ОШИБКА"):
            criticism = "Критика недоступна."

        final_answer = ""
        accepted = False
        for _ in range(limits["max_iterations"]):
            final_answer = synthesizer(task, plan, analysis, criticism, budget)
            if final_answer.startswith("[ОШИБКА"):
                return _complete(
                    {"status": "error", "stage": "synthesizer", "detail": final_answer},
                    budget,
                    event_id,
                )
            accepted, final_critique = final_critic_check(task, final_answer, budget)
            if accepted:
                break
            criticism = final_critique

        status = "ok" if accepted else "max_iterations_reached"
        add_episodic_event(task, final_answer, status=status)
        return _complete(
            {
                "status": status,
                "task_type": task_type,
                "plan": plan,
                "analysis": analysis,
                "criticism": criticism,
                "final_answer": final_answer,
            },
            budget,
            event_id,
        )
    except ExecutionLimitError as exc:
        return _complete(
            {
                "status": "limit_reached",
                "stage": "execution_budget",
                "detail": str(exc),
            },
            budget,
            event_id,
        )
    except Exception as exc:
        append_audit_event(
            "pipeline_failed",
            event_id=event_id,
            error_type=type(exc).__name__,
            execution=budget.snapshot(),
        )
        raise
