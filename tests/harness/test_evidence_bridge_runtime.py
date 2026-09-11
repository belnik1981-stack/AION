from pathlib import Path

from core.evidence_bridge import load_analysis_evidence, format_evidence_for_prompt
from trials.evidence_objects_v2.run_trial import VALID_BUNDLE


def main():
    result = load_analysis_evidence(VALID_BUNDLE)
    assert result["status"] == "available_for_analysis"
    assert result["claim_count"] >= 1
    assert result["report"]["execution_authorized"] is False

    rendered = format_evidence_for_prompt(result)
    assert "VALIDATED EVIDENCE OBJECTS V2" in rendered
    assert "analysis-only" in rendered

    for claim in result["claims"]:
        assert claim["claim_id"] in rendered
        assert claim["text"] in rendered

    print("RUNTIME EVIDENCE BRIDGE: PASS")


if __name__ == "__main__":
    main()
