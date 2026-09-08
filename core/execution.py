"""Bounded execution primitives for AION trial paths."""
from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic


class ExecutionLimitError(RuntimeError):
    """Raised when a hard execution boundary is reached."""


@dataclass
class ExecutionBudget:
    max_api_calls: int
    max_total_seconds: float
    started_at: float = field(default_factory=monotonic)
    api_calls: int = 0

    def __post_init__(self) -> None:
        if self.max_api_calls <= 0:
            raise ValueError("max_api_calls must be greater than zero")
        if self.max_total_seconds <= 0:
            raise ValueError("max_total_seconds must be greater than zero")

    def acquire(self, per_call_timeout: float) -> float:
        if self.api_calls >= self.max_api_calls:
            raise ExecutionLimitError("API call budget exhausted")

        remaining = self.remaining_seconds()
        if remaining <= 0:
            raise ExecutionLimitError("Total execution deadline reached")

        timeout = min(float(per_call_timeout), remaining)
        if timeout <= 0:
            raise ExecutionLimitError("No time remains for another provider call")

        self.api_calls += 1
        return max(0.1, timeout)

    def remaining_seconds(self) -> float:
        elapsed = monotonic() - self.started_at
        return max(0.0, self.max_total_seconds - elapsed)

    def snapshot(self) -> dict:
        elapsed = monotonic() - self.started_at
        return {
            "api_calls": self.api_calls,
            "max_api_calls": self.max_api_calls,
            "elapsed_seconds": round(elapsed, 3),
            "max_total_seconds": self.max_total_seconds,
            "remaining_seconds": round(max(0.0, self.max_total_seconds - elapsed), 3),
        }


def validate_text(value: str, max_chars: int, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    text = value.strip()
    if not text:
        raise ValueError(f"{label} is empty")
    if len(text) > max_chars:
        raise ExecutionLimitError(
            f"{label} exceeds the configured character limit ({max_chars})"
        )
    return text
