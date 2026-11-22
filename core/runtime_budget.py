"""Process-local execution budget for one AION pipeline run.

The immutable Truth timeout is enforced as one monotonic deadline shared by
all model roles.  The call budget is deliberately independent from the
iteration limit: one iteration can contain several roles and a bounded retry.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import os
import time
from typing import Callable, Iterator


DEFAULT_MAX_LLM_CALLS = 24
HARD_MAX_LLM_CALLS = 32


class RuntimeLimitError(RuntimeError):
    """A safe, machine-readable stop caused by a runtime resource limit."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def configured_call_limit() -> int:
    """Read a bounded per-run call limit without allowing an unbounded value."""

    raw = os.getenv("AION_MAX_LLM_CALLS", str(DEFAULT_MAX_LLM_CALLS))
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("AION_MAX_LLM_CALLS должен быть целым числом") from exc
    if not 1 <= value <= HARD_MAX_LLM_CALLS:
        raise ValueError(
            f"AION_MAX_LLM_CALLS должен быть в диапазоне 1..{HARD_MAX_LLM_CALLS}"
        )
    return value


@dataclass
class ExecutionBudget:
    timeout_seconds: float
    max_calls: int
    clock: Callable[[], float] = time.monotonic
    started_at: float = field(init=False)
    deadline: float = field(init=False)
    calls_used: int = 0
    stop_reason: str | None = None

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds должен быть > 0")
        if not 1 <= self.max_calls <= HARD_MAX_LLM_CALLS:
            raise ValueError("Некорректный лимит LLM-вызовов")
        self.started_at = self.clock()
        self.deadline = self.started_at + float(self.timeout_seconds)

    def _remaining(self) -> float:
        return self.deadline - self.clock()

    def reserve_call(self) -> None:
        """Reserve exactly one provider attempt or stop before network access."""

        if self._remaining() <= 0:
            self.stop_reason = "runtime_deadline_exceeded"
            raise RuntimeLimitError(self.stop_reason)
        if self.calls_used >= self.max_calls:
            self.stop_reason = "runtime_call_limit_exceeded"
            raise RuntimeLimitError(self.stop_reason)
        self.calls_used += 1

    def provider_timeout(self) -> float:
        """Return the remaining deadline for the next provider socket timeout."""

        remaining = self._remaining()
        if remaining <= 0:
            self.stop_reason = "runtime_deadline_exceeded"
            raise RuntimeLimitError(self.stop_reason)
        # urllib accepts a float. A tiny positive floor avoids passing zero
        # after the preceding monotonic check.
        return max(0.001, remaining)

    def snapshot(self) -> dict:
        elapsed = max(0.0, self.clock() - self.started_at)
        remaining = max(0.0, self.deadline - self.clock())
        return {
            "timeout_seconds": self.timeout_seconds,
            "max_calls": self.max_calls,
            "calls_used": self.calls_used,
            "elapsed_seconds": round(elapsed, 3),
            "remaining_seconds": round(remaining, 3),
            "stop_reason": self.stop_reason,
        }


_CURRENT_BUDGET: ContextVar[ExecutionBudget | None] = ContextVar(
    "aion_execution_budget", default=None
)


def current_budget() -> ExecutionBudget | None:
    return _CURRENT_BUDGET.get()


@contextmanager
def use_budget(budget: ExecutionBudget) -> Iterator[ExecutionBudget]:
    token = _CURRENT_BUDGET.set(budget)
    try:
        yield budget
    finally:
        _CURRENT_BUDGET.reset(token)
