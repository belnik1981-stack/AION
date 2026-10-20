"""Evidence collection and fail-closed candidate preparation for AION."""

from .collector import EvidenceCollector, EvidenceDocument, EvidenceCollectorError
from .candidate_bundle import (
    EvidenceCandidateError,
    build_collected_candidate_bundle,
    write_collected_candidate_bundle,
)

__all__ = [
    "EvidenceCollector",
    "EvidenceDocument",
    "EvidenceCollectorError",
    "EvidenceCandidateError",
    "build_collected_candidate_bundle",
    "write_collected_candidate_bundle",
]
