"""AION verification layer.

Candidate information can be evaluated here, but this package never writes to
AION truth. Promotion is limited to verified long-term knowledge.
"""

from verification.pipeline import (
    EvidenceItem,
    RevalidatedVerification,
    VerificationPolicy,
    evaluate_claim,
    promote_verified_claim,
    revalidate_verification_record,
    recover_pending_promotions,
    verify_candidate_record,
)

__all__ = [
    "EvidenceItem",
    "RevalidatedVerification",
    "VerificationPolicy",
    "evaluate_claim",
    "promote_verified_claim",
    "revalidate_verification_record",
    "recover_pending_promotions",
    "verify_candidate_record",
]
