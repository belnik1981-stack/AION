from core.cycle_guard import CycleGuard


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    print(f"[PASS] {name}")


if __name__ == "__main__":
    guard = CycleGuard()
    first = guard.observe("step", "same result")
    second = guard.observe("step", "same result")
    check("first state is allowed", first.cycle_detected is False)
    check("second identical state is blocked", second.cycle_detected is True)
    check("direct repeat classified", second.cycle_type == "direct_repeat")

    oscillation = CycleGuard()
    oscillation.observe("step", "A")
    oscillation.observe("step", "B")
    oscillation.observe("step", "A")
    fourth = oscillation.observe("step", "B")
    check("A-B-A-B oscillation blocked", fourth.cycle_detected is True)
    check("oscillation classified", fourth.cycle_type == "two_state_oscillation")

    revisit = CycleGuard()
    revisit.observe("step", "A")
    revisit.observe("step", "B")
    third = revisit.observe("step", "A")
    check("revisited state blocked", third.cycle_detected is True)

    interpretation = CycleGuard()
    interpretation.observe(
        "decision",
        "Источник недостаточно надежен, требуется дополнительная проверка.",
        semantic_key="source_needs_more_verification",
    )
    same_meaning = interpretation.observe(
        "decision",
        "Надежность источника сомнительна, поэтому его нужно проверить снова.",
        semantic_key="source_needs_more_verification",
    )
    check("same interpretation with different wording blocked", same_meaning.cycle_detected is True)
    check("same interpretation classified", same_meaning.cycle_type == "same_interpretation")

    print("CYCLE GUARD TEST: PASS")
