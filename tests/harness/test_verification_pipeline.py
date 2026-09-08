from verification.pipeline import EvidenceItem, VerificationPolicy, evaluate_claim


policy = VerificationPolicy()

verified = evaluate_claim(
    "Water freezes at 0 °C at standard atmospheric pressure.",
    [
        EvidenceItem("src-a", "reference", "supports", 0.9, "group-a"),
        EvidenceItem("src-b", "reference", "supports", 0.8, "group-b"),
    ],
    policy,
)
assert verified.decision == "verified", verified

llm_only = evaluate_claim(
    "Claim from two model outputs.",
    [
        EvidenceItem("m1", "llm", "supports", 0.9, "model-a"),
        EvidenceItem("m2", "model_output", "supports", 0.9, "model-b"),
    ],
    policy,
)
assert llm_only.decision == "needs_more_evidence", llm_only
assert "no_non_llm_support" in llm_only.reasons

conflicted = evaluate_claim(
    "A disputed claim.",
    [
        EvidenceItem("src-a", "reference", "supports", 0.9, "group-a"),
        EvidenceItem("src-b", "reference", "supports", 0.8, "group-b"),
        EvidenceItem("src-c", "reference", "contradicts", 0.9, "group-c"),
    ],
    policy,
)
assert conflicted.decision == "conflicted", conflicted
assert "material_contradiction_present" in conflicted.reasons

same_origin = evaluate_claim(
    "Repeated copies are not independent evidence.",
    [
        EvidenceItem("copy-1", "reference", "supports", 0.9, "same-origin"),
        EvidenceItem("copy-2", "reference", "supports", 0.9, "same-origin"),
    ],
    policy,
)
assert same_origin.decision == "needs_more_evidence", same_origin
assert "insufficient_independent_sources" in same_origin.reasons

print("VERIFICATION PIPELINE TEST: PASS")
