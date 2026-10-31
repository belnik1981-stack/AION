"""Offline regression cases: evidence gates are not semantic truth judgments.

Run: python -m unittest tests.harness.test_reasoning_evidence_gates -v
No external models, network, or writes to Truth are used.
"""
import unittest

from verification.pipeline import EvidenceItem, evaluate_claim


def evidence(source_id, source_type, stance, group, quality=0.9):
    return EvidenceItem(
        source_id=source_id,
        source_type=source_type,
        stance=stance,
        quality=quality,
        independent_group=group,
    )


class ReasoningEvidenceGateTests(unittest.TestCase):
    def test_invalid_conversion_not_verified_without_evidence(self):
        result = evaluate_claim("All A are B; therefore all B are A", [])
        self.assertEqual(result.decision, "unverified")

    def test_correct_arithmetic_not_automatically_verified(self):
        result = evaluate_claim("15% of 200 equals 30", [])
        self.assertEqual(result.decision, "unverified")

    def test_model_agreement_is_not_proof(self):
        result = evaluate_claim(
            "Two models agree; therefore the claim is proven",
            [
                evidence("model-1", "llm", "supports", "model-1"),
                evidence("model-2", "llm", "supports", "model-2"),
            ],
        )
        self.assertNotEqual(result.decision, "verified")
        self.assertIn("no_non_llm_support", result.reasons)

    def test_unavailable_source_is_not_evidence(self):
        result = evaluate_claim("A source supports this, but its text is unavailable", [])
        self.assertEqual(result.decision, "unverified")

    def test_incomplete_square_root_not_automatically_verified(self):
        result = evaluate_claim("x squared equals 9, so x equals 3 only", [])
        self.assertEqual(result.decision, "unverified")

    def test_material_contradiction_blocks_verification(self):
        result = evaluate_claim(
            "An independently testable claim",
            [
                evidence("doc-1", "document", "supports", "publisher-1"),
                evidence("doc-2", "document", "supports", "publisher-2"),
                evidence("doc-3", "document", "contradicts", "publisher-3"),
            ],
        )
        self.assertEqual(result.decision, "conflicted")


if __name__ == "__main__":
    unittest.main()
