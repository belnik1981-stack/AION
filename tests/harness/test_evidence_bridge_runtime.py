import copy

from core.evidence_bridge import (
    EvidenceBridgeError,
    format_evidence_for_prompt,
    load_analysis_evidence,
    revalidate_analysis_evidence_context,
)
from trials.evidence_objects_v2.run_trial import VALID_BUNDLE


def main():
    result = load_analysis_evidence(VALID_BUNDLE)
    assert result["status"] == "available_for_analysis"
    assert result["claim_count"] >= 1
    assert result["report"]["execution_authorized"] is False
    assert result["schema_version"] == "aion-analysis-evidence-context-v1"
    assert len(result["context_digest"]) == 64
    assert len(result["context_seal"]) == 64
    assert "bundle_path" not in result
    assert revalidate_analysis_evidence_context(result) == result

    rendered = format_evidence_for_prompt(result)
    assert "VALIDATED EVIDENCE OBJECTS V2" in rendered
    assert "analysis-only" in rendered

    for claim in result["claims"]:
        assert claim["claim_id"] in rendered
        assert claim["text"] in rendered

    # Claims or authority flags cannot be changed after the bridge emits the
    # integrity-bound context.
    for mutation in ("claim", "authority"):
        tampered = copy.deepcopy(result)
        if mutation == "claim":
            tampered["claims"][0]["text"] = "Caller injected an unverified claim."
        else:
            tampered["execution_authorized"] = True
        try:
            revalidate_analysis_evidence_context(tampered)
        except EvidenceBridgeError:
            pass
        else:
            raise AssertionError("Tampered analysis evidence context was accepted")

    # Prompt rendering keeps only complete claim lines inside a hard bound.
    bounded = format_evidence_for_prompt(result, max_chars=128)
    assert len(bounded) <= 128
    assert "omitted" in bounded

    print("RUNTIME EVIDENCE BRIDGE: PASS")


if __name__ == "__main__":
    main()
