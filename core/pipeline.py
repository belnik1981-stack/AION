"""
AION Pipeline.

При одной модели сохраняется прежний TMAO-проход.
При AION_MODELS=model1,model2,... запускается многомодельный режим:
1) каждая модель независимо отвечает на исходную задачу;
2) роли Planner/Analyst/Critic/Synthesizer/Verifier ротируются между моделями;
3) телеметрия сохраняет ответы и назначения ролей для анализа расхождений.

Опционально AION_EVIDENCE_BUNDLE указывает на Evidence Objects v2 bundle.
Bundle проходит fail-closed валидацию и допускается только как analysis-only
материал; он не становится Truth и не разрешает действия.
"""

from datetime import datetime
import os

from core.truth import get_execution_limits
from core.agents import planner, analyst, critic, synthesizer, final_critic_check
from core.evidence_bridge import EvidenceBridgeError, format_evidence_for_prompt, load_analysis_evidence
from core.llm import ask_llm
from providers.base import ProviderTruncatedError, ProviderRateLimitError
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


def _evidence_context() -> tuple[str, dict]:
    path = os.getenv("AION_EVIDENCE_BUNDLE", "").strip()
    if not path:
        return "", {"enabled": False}
    try:
        evidence = load_analysis_evidence(path)
    except Exception as exc:
        return "", {
            "enabled": True,
            "status": "rejected",
            "detail": str(exc),
        }
    return format_evidence_for_prompt(evidence), {
        "enabled": True,
        "status": evidence["status"],
        "claim_count": evidence["claim_count"],
        "bundle_path": evidence["bundle_path"],
        "execution_authorized": False,
        "truth_update_authorized": False,
    }


def _task_with_evidence(task: str, evidence_text: str) -> str:
    if not evidence_text:
        return task
    return (
        f"{task}\n\n{evidence_text}\n\n"
        "Правило: evidence выше является только проверенным материалом для анализа. "
        "Не называй его Truth автоматически; различай наблюдение, заявление источника, "
        "вывод, предположение и прогноз."
    )


def _raw_answer(task: str, model: str) -> str:
    prompt = (
        "Ответь на задачу независимо. Не учитывай ответы других моделей, потому что их ещё нет. "
        "Отделяй установленные факты от предположений и явно отмечай существенную неопределённость.\n\n"
        f"ЗАДАЧА:\n{task}"
    )
    try:
        ceiling = int(os.getenv("AION_ROLE_TOKEN_CEILING", "4096"))
        if not 128 <= ceiling <= 8192:
            raise ValueError("AION_ROLE_TOKEN_CEILING вне диапазона 128..8192")
        requested = int(os.getenv("AION_ANALYST_TOKENS", "900"))
        if requested <= 0:
            raise ValueError("AION_ANALYST_TOKENS должен быть положительным")
        budget = min(max(128, requested), ceiling)
        try:
            return ask_llm(prompt, max_tokens=budget, model=model).strip()
        except ProviderTruncatedError:
            enabled = os.getenv("AION_TRUNCATION_RETRY", "1").strip().lower() in ("1", "true", "yes", "on")
            retry_budget = min(ceiling, max(budget + 256, budget * 2))
            if not enabled or retry_budget <= budget:
                raise
            return ask_llm(prompt, max_tokens=retry_budget, model=model).strip()
    except ProviderRateLimitError:
        return "[ОШИБКА:raw] HTTP 429 rate_limited"
    except Exception as exc:
        return f"[ОШИБКА:raw] {exc}"


def _legacy_pipeline(task: str, task_type: str, max_iterations: int, evidence_meta: dict) -> dict:
    plan = planner(task)
    if plan.startswith("[ОШИБКА"):
        return {"status": "error", "stage": "planner", "detail": plan, "evidence": evidence_meta}

    analysis = analyst(task, plan)
    if analysis.startswith("[ОШИБКА"):
        return {"status": "error", "stage": "analyst", "detail": analysis, "evidence": evidence_meta}

    criticism = critic(task, plan, analysis)
    if criticism.startswith("[ОШИБКА"):
        return {"status": "error", "stage": "critic", "detail": criticism, "evidence": evidence_meta}

    final_answer = None
    accepted = False
    previous_final = None
    guard = CycleGuard()
    cycle_info = None
    stop_reason = "max_iterations_reached"
    iterations_used = 0

    for iteration in range(1, max_iterations + 1):
        iterations_used = iteration
        final_answer = synthesizer(task, plan, analysis, criticism)
        if final_answer.startswith("[ОШИБКА"):
            return {"status": "error", "stage": "synthesizer", "detail": final_answer, "evidence": evidence_meta}
        observed = guard.observe("synthesizer", final_answer)
        if observed.cycle_detected:
            cycle_info = {"type": observed.cycle_type, "reason": observed.reason, "iteration": iteration}
            stop_reason = "cycle_detected"
            break
        if previous_final is not None and _norm(final_answer) == _norm(previous_final):
            stop_reason = "stalled_no_progress"
            break
        is_ok, final_critique = final_critic_check(task, final_answer)
        if final_critique.startswith("[ОШИБКА"):
            return {"status": "error", "stage": "final_critic", "detail": final_critique, "evidence": evidence_meta}
        if is_ok:
            accepted = True
            criticism = "OK"
            stop_reason = "accepted"
            break
        observed_critique = guard.observe("critic", final_critique)
        if observed_critique.cycle_detected:
            cycle_info = {"type": observed_critique.cycle_type, "reason": observed_critique.reason, "iteration": iteration}
            criticism = final_critique
            stop_reason = "cycle_detected"
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
        "cycle": cycle_info,
        "cycle_guard": guard.status(),
        "evidence": evidence_meta,
        "plan": plan,
        "analysis": analysis,
        "criticism": criticism,
        "final_answer": final_answer,
        "timestamp": datetime.now().isoformat(),
    }


def _multi_model_pipeline(task: str, task_type: str, models: list[str], max_iterations: int, evidence_meta: dict) -> dict:
    raw_answers = {}
    for model in models:
        raw_answers[model] = _raw_answer(task, model)
        if raw_answers[model].startswith("[ОШИБКА:raw] HTTP 429"):
            return {
                "status": "error",
                "stage": "raw_multi_model",
                "detail": "HTTP 429: испытание остановлено без запросов к следующей модели.",
                "models": models,
                "raw_answers": raw_answers,
                "evidence": evidence_meta,
                "truth_verified": False,
            }
    usable = {m: a for m, a in raw_answers.items() if not a.startswith("[ОШИБКА")}
    if len(usable) < 2:
        return {
            "status": "error",
            "stage": "raw_multi_model",
            "detail": "Для сравнительного режима нужны успешные ответы минимум двух разных моделей.",
            "models": models,
            "raw_answers": raw_answers,
            "evidence": evidence_meta,
        }

    raw_bundle = "\n\n".join(f"MODEL {m}:\n{a}" for m, a in usable.items())
    requested_rotations = int(os.getenv("AION_MULTI_TEST_ROUNDS", str(max_iterations)))
    if not 1 <= requested_rotations <= max_iterations:
        return {"status": "error", "stage": "model_selection",
                "detail": "AION_MULTI_TEST_ROUNDS должен быть в пределах лимита Truth.",
                "truth_verified": False}
    rotations = min(len(models), requested_rotations)
    round_results = []
    final_answer = None
    accepted = False
    stop_reason = "rotations_exhausted"
    cycle_info = None
    guard = CycleGuard()

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
        if plan.startswith("[ОШИБКА"):
            return {"status": "error", "stage": "planner", "detail": plan, "evidence": evidence_meta}
        analysis = analyst(
            task + "\n\nСопоставь независимые ответы и отдели устойчивые совпадения от расхождений:\n" + raw_bundle,
            plan,
            model=assignment["analyst"],
        )
        if analysis.startswith("[ОШИБКА"):
            return {"status": "error", "stage": "analyst", "detail": analysis, "evidence": evidence_meta}
        criticism = critic(task, plan, analysis, model=assignment["critic"])
        if criticism.startswith("[ОШИБКА"):
            return {"status": "error", "stage": "critic", "detail": criticism, "evidence": evidence_meta}
        final_answer = synthesizer(task, plan, analysis, criticism, model=assignment["synthesizer"])
        if final_answer.startswith("[ОШИБКА"):
            return {"status": "error", "stage": "synthesizer", "detail": final_answer, "evidence": evidence_meta}
        observed = guard.observe("synthesizer", final_answer)
        if observed.cycle_detected:
            cycle_info = {"type": observed.cycle_type, "reason": observed.reason, "round": r + 1}
            stop_reason = "cycle_detected"
            break
        is_ok, verdict = final_critic_check(task, final_answer, model=assignment["verifier"])
        if verdict.startswith("[ОШИБКА"):
            return {"status": "error", "stage": "verifier", "detail": verdict, "evidence": evidence_meta}

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
            stop_reason = "ok"
            break
        observed_verdict = guard.observe("verifier", verdict)
        if observed_verdict.cycle_detected:
            cycle_info = {"type": observed_verdict.cycle_type, "reason": observed_verdict.reason, "round": r + 1}
            stop_reason = "cycle_detected"
            break

    if final_answer:
        add_episodic_event(task, final_answer)

    return {
        "status": "ok" if accepted else stop_reason,
        "mode": "multi_model_role_rotation",
        "task_type": task_type,
        "models": models,
        # Distinct IDs and isolated initial prompts are observable; actual
        # model/vendor independence and factual truth are not proven by agreement.
        "independent_model_count": len(usable),
        "independent_initial_outputs": len(usable),
        "model_ids_distinct": len(set(usable)) == len(usable),
        "truth_verified": False,
        "verification_scope": "llm_review_only",
        "evidence": evidence_meta,
        "raw_answers": raw_answers,
        "rotations_planned": rotations,
        "rotations_used": len(round_results),
        "cycle": cycle_info,
        "cycle_guard": guard.status(),
        "rounds": round_results,
        "final_answer": final_answer,
        "timestamp": datetime.now().isoformat(),
    }


def run_pipeline(task: str) -> dict:
    limits = get_execution_limits()
    max_iterations = int(limits.get("max_iterations", 2))
    task_type = router(task)
    models = _models()
    requested_models = os.getenv("AION_MODELS", "").strip()
    if requested_models:
        submitted = [item.strip() for item in requested_models.split(",")]
        if (len(submitted) < 2 or any(not item for item in submitted)
                or len(set(submitted)) != len(submitted)
                or "openrouter/free" in submitted):
            return {
                "status": "error",
                "stage": "model_selection",
                "detail": "Для независимого сравнения нужны минимум две разные "
                          "явно названные модели; дубликаты и openrouter/free запрещены.",
                "truth_verified": False,
            }
    evidence_text, evidence_meta = _evidence_context()

    if evidence_meta.get("status") == "rejected":
        return {
            "status": "error",
            "stage": "evidence_bridge",
            "detail": evidence_meta.get("detail"),
            "evidence": evidence_meta,
        }

    effective_task = _task_with_evidence(task, evidence_text)

    if len(models) >= 2:
        return _multi_model_pipeline(effective_task, task_type, models, max_iterations, evidence_meta)
    return _legacy_pipeline(effective_task, task_type, max_iterations, evidence_meta)
