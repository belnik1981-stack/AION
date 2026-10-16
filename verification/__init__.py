"""AION verification layer.

Candidate information can be evaluated here, but this package never writes to
AION truth. Promotion is limited to verified long-term knowledge.
"""

from verification.pipeline import (
    EvidenceItem,
    VerificationPolicy,
    evaluate_claim,
    promote_verified_claim,
    verify_candidate_record,
)

__all__ = [
    "EvidenceItem",
    "VerificationPolicy",
    "evaluate_claim",
    "promote_verified_claim",
    "verify_candidate_record",
]
