"""Offline regression tests for bounded AION orchestration; no network or API."""
from unittest.mock import patch

from core import pipeline


def execute_case(answers, critiques, max_iterations=3):
    answers = iter(answers)
    critiques = iter(critiques)
    calls = {"final_critic": 0, "memory": 0}

    def final_check(task, answer):
        calls["final_critic"] += 1
        return next(critiques)

    def save_event(task, answer):
        calls["memory"] += 1

    with patch.multiple(
        pipeline,
        get_execution_limits=lambda: {"max_iterations": max_iterations, "timeout_seconds": 30},
        planner=lambda task: "plan",
        analyst=lambda task, plan: "analysis",
        critic=lambda task, plan, analysis: "critic",
        synthesizer=lambda task, plan, analysis, criticism: next(answers),
        final_critic_check=final_check,
        add_episodic_event=save_event,
    ):
        result = pipeline.run_pipeline("test")
    return result, calls


accepted, accepted_calls = execute_case(["supported result"], [(True, "OK")])
assert accepted["status"] == "ok", accepted
assert accepted["iterations_used"] == 1, accepted
assert accepted["cycle"] is None, accepted
assert accepted_calls["final_critic"] == 1, accepted_calls

repeated, repeated_calls = execute_case(
    ["unchanged answer", "unchanged answer"],
    [(False, "FAIL: missing source")],
)
assert repeated["status"] == "cycle_detected", repeated
assert repeated["iterations_used"] == 2, repeated
assert repeated["cycle"]["type"] == "revisited_state", repeated
assert repeated_calls["final_critic"] == 1, repeated_calls

critic_cycle, _ = execute_case(
    ["first distinct answer", "second materially different response"],
    [(False, "FAIL: unsupported conclusion"), (False, "FAIL: unsupported conclusion")],
)
assert critic_cycle["status"] == "cycle_detected", critic_cycle
assert critic_cycle["cycle"]["type"] == "revisited_state", critic_cycle

bounded, bounded_calls = execute_case(
    ["first answer", "completely different second answer"],
    [(False, "FAIL: missing evidence A"), (False, "FAIL: missing evidence B")],
    max_iterations=2,
)
assert bounded["status"] == "max_iterations_reached", bounded
assert bounded["iterations_used"] == 2, bounded
assert bounded_calls["final_critic"] == 2, bounded_calls

print("PIPELINE CYCLE REGRESSION: PASS")
