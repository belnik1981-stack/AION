"""Security primitives shared by AION input, output and persistence boundaries."""

from .redaction import (
    RedactionResult,
    SensitiveDataError,
    TextSafetyError,
    redact_sensitive,
    redact_structure,
)

__all__ = [
    "RedactionResult",
    "SensitiveDataError",
    "TextSafetyError",
    "redact_sensitive",
    "redact_structure",
]
