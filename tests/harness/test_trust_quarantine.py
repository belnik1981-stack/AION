from learning.quarantine import assess_quarantine, effective_influence


def check(name, condition):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}")
    if not condition:
        raise AssertionError(name)


print("========== AION TRUST QUARANTINE TEST ==========")

soft = assess_quarantine(importance=0.30, cleanliness=0.95, negative_impact=0.20)
check("soft quarantine level", soft.level == 1)
check("soft quarantine keeps partial influence", 0.0 < soft.influence_multiplier <= 1.0)
check("soft quarantine may learn", soft.learning_allowed is True)

strict = assess_quarantine(importance=0.80, cleanliness=0.68, negative_impact=0.55)
check("strict quarantine level", strict.level == 2)
check("strict quarantine caps influence", 0.0 < strict.influence_multiplier <= 0.35)
check("strict quarantine blocks auto-promotion", strict.auto_promote_allowed is False)
check("strict quarantine blocks learning", strict.learning_allowed is False)

isolation = assess_quarantine(importance=0.90, cleanliness=0.35, negative_impact=0.90)
check("isolation level", isolation.level == 3)
check("isolation influence zero", isolation.influence_multiplier == 0.0)
check("isolation blocks learning", isolation.learning_allowed is False)
check("effective influence zero in isolation", effective_influence(0.95, isolation) == 0.0)

print("========== RESULT ==========")
print("THREE-LEVEL TRUST QUARANTINE: PASS")
