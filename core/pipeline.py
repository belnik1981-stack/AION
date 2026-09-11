"""
AION Pipeline.

При одной модели сохраняется прежний TMAO-проход.
При AION_MODELS=model1,model2,... запускается многомодельный режим:
1) каждая модель независимо отвечает на исходную задачу;
2) роли Planner/Analyst/Critic/Synthesizer/Verifier ротируются между моделями;
3) телеметрия сохраняет ответы и назначения ролей для анализа расхождений.
"""

from datetime import datetime
import os

from core.truth import get_execution_limits
from core.agents import planner, analyst, critic, synthesizer, final_critic_check
from core.llm import ask_llm
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


def _models() -> list[str]:
    raw = os.getenv("AION_MODELS", "").strip()
    if not raw:
        single = os.getenv("AION_MODEL", "").strip()
        return [single] if single else []
    result = []
    for item in raw.split(","):
        model = item.strip()
        if model and model not in result:
            result.append(model)
    return result


def _raw_answer(task: str, model: str) -> str:
    prompt = (
        "Ответь на задачу независимо. Не учитывай ответы других моделей, потому что их ещё нет. "
        "Отделяй установленные факты от предположений и явно отмечай существенную неопределённость.\n\n"
        f"ЗАДАЧА:\n{task}"
    )
    try:
        return ask_llm(prompt, max_tokens=int(os.getenv("AION_ANALYST_TOKENS", "420")), model=model).strip()
    except Exception as exc:
        return f"[ОШИБКА:raw] {exc}"


def _legacy_pipeline(task: str, task_type: str, max_iterations: int) -> dict:
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
        "mode": "single_model",
        "task_type": task_type,
        "iterations_used": iterations_used,
        "plan": plan,
        "analysis": analysis,
        "criticism": criticism,
        "final_answer": final_answer,
        "timestamp": datetime.now().isoformat(),
    }


def _multi_model_pipeline(task: str, task_type: str, models: list[str], max_iterations: int) -> dict:
    raw_answers = {model: _raw_answer(task, model) for model in models}
    usable = {m: a for m, a in raw_answers.items() if not a.startswith("[ОШИБКА")}
    if len(usable) < 2:
        return {
            "status": "error",
            "stage": "raw_multi_model",
            "detail": "Для сравнительного режима нужны успешные ответы минимум двух разных моделей.",
            "models": models,
            "raw_answers": raw_answers,
        }

    raw_bundle = "\n\n".join(f"MODEL {m}:\n{a}" for m, a in usable.items())
    rotations = min(len(models), max_iterations)
    round_results = []
    final_answer = None
    accepted = False

    for r in range(rotations):
        assignment = {
            "planner": models[r % len(models)],
            "analyst": models[(r + 1) % len(models)],
            "critic": models[(r + 2) % len(models)],
            "synthesizer": models[(r + 3) % len(models)],
            "verifier": models[(r + 4) % len(models)],
        }

        plan = planner(
            task + "\n\nНезависимые исходные ответы моделей:\n" + raw_bundle,
            model=assignment["planner"],
        )
        analysis = analyst(
            task + "\n\nСопоставь независимые ответы и отдели устойчивые совпадения от расхождений:\n" + raw_bundle,
            plan,
            model=assignment["analyst"],
        )
        criticism = critic(task, plan, analysis, model=assignment["critic"])
        final_answer = synthesizer(task, plan, analysis, criticism, model=assignment["synthesizer"])
        is_ok, verdict = final_critic_check(task, final_answer, model=assignment["verifier"])

        round_results.append({
            "round": r + 1,
            "role_assignment": assignment,
            "plan": plan,
            "analysis": analysis,
            "criticism": criticism,
            "candidate_answer": final_answer,
            "verifier": verdict,
            "accepted": is_ok,
        })

        if is_ok:
            accepted = True
            break

    if final_answer:
        add_episodic_event(task, final_answer)

    return {
        "status": "ok" if accepted else "rotations_exhausted",
        "mode": "multi_model_role_rotation",
        "task_type": task_type,
        "models": models,
        "independent_model_count": len(usable),
        "raw_answers": raw_answers,
        "rotations_planned": rotations,
        "rotations_used": len(round_results),
        "rounds": round_results,
        "final_answer": final_answer,
        "timestamp": datetime.now().isoformat(),
    }


def run_pipeline(task: str) -> dict:
    limits = get_execution_limits()
    max_iterations = int(limits.get("max_iterations", 2))
    task_type = router(task)
    models = _models()

    if len(models) >= 2:
        return _multi_model_pipeline(task, task_type, models, max_iterations)
    return _legacy_pipeline(task, task_type, max_iterations)
