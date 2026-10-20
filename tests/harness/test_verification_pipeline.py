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

duplicate_source = evaluate_claim(
    "Repeating one source id cannot create two sources.",
    [
        EvidenceItem("same-source", "reference", "supports", 0.9, "claimed-root-a"),
        EvidenceItem("same-source", "reference", "supports", 0.9, "claimed-root-b"),
    ],
    policy,
)
assert duplicate_source.decision == "needs_more_evidence", duplicate_source
assert duplicate_source.supporting_sources == 1, duplicate_source
assert duplicate_source.weighted_support == 0.9, duplicate_source
assert duplicate_source.independent_support_groups == 0, duplicate_source

for invalid_quality in (float("nan"), float("inf"), float("-inf")):
    try:
        evaluate_claim(
            "Non-finite quality is invalid.",
            [EvidenceItem("bad", "reference", "supports", invalid_quality, "root")],
            VerificationPolicy(),
        )
    except ValueError:
        pass
    else:
        raise AssertionError("non-finite evidence quality was accepted")

try:
    evaluate_claim(
        "Non-finite policy is invalid.",
        [EvidenceItem("src", "reference", "supports", 0.9, "root")],
        VerificationPolicy(min_weighted_support=float("nan")),
    )
except ValueError:
    pass
else:
    raise AssertionError("non-finite verification policy was accepted")

try:
    evaluate_claim(
        "Empty source type is invalid.",
        [EvidenceItem("src", "", "supports", 0.9, "root")],
        VerificationPolicy(),
    )
except ValueError:
    pass
else:
    raise AssertionError("empty evidence source_type was accepted")

try:
    evaluate_claim(
        "x" * 100_001,
        [EvidenceItem("src", "reference", "supports", 0.9, "root")],
        VerificationPolicy(),
    )
except ValueError:
    pass
else:
    raise AssertionError("oversized claim was accepted")

print("VERIFICATION PIPELINE TEST: PASS")
