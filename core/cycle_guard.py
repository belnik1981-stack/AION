"""Cycle and oscillation guard for AION execution paths.

Detects repeated semantic states and simple A-B-A-B oscillation before an agent
loop wastes additional iterations. The guard does not decide truth; it only
stops repeated execution states and records why progress stopped.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any


_WS = re.compile(r"\s+")


def _normalise(value: Any) -> str:
    """Create a stable representation resilient to whitespace/key-order noise."""
    if isinstance(value, str):
        return _WS.sub(" ", value.strip().lower())
    try:
        rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except TypeError:
        rendered = repr(value)
    return _WS.sub(" ", rendered.strip().lower())


def state_fingerprint(stage: str, value: Any) -> str:
    payload = f"{stage.strip().lower()}|{_normalise(value)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CycleObservation:
    cycle_detected: bool
    cycle_type: str | None
    occurrences: int
    reason: str | None


class CycleGuard:
    """Detect duplicate and alternating states.

    A second occurrence of the same state is enough to stop further repetition.
    A-B-A-B is also treated as an oscillation even when no state occurs
    consecutively.
    """

    def __init__(self, max_history: int = 12) -> None:
        self.max_history = max(4, int(max_history))
        self._history: list[str] = []
        self._counts: dict[str, int] = {}

    def observe(self, stage: str, value: Any) -> CycleObservation:
        fp = state_fingerprint(stage, value)
        count = self._counts.get(fp, 0) + 1
        self._counts[fp] = count
        self._history.append(fp)
        if len(self._history) > self.max_history:
            removed = self._history.pop(0)
            # Counts describe retained history, not lifetime frequency.
            self._counts[removed] = max(0, self._counts.get(removed, 1) - 1)
            count = self._counts.get(fp, count)

        if len(self._history) >= 2 and self._history[-1] == self._history[-2]:
            return CycleObservation(True, "direct_repeat", count, "same_state_repeated")

        if len(self._history) >= 4:
            a, b, c, d = self._history[-4:]
            if a == c and b == d and a != b:
                return CycleObservation(True, "two_state_oscillation", max(self._counts[a], self._counts[b]), "a_b_a_b_oscillation")

        if count >= 2:
            return CycleObservation(True, "revisited_state", count, "previous_state_revisited_without_new_information")

        return CycleObservation(False, None, count, None)

    def status(self) -> dict[str, Any]:
        return {
            "observations": len(self._history),
            "unique_states": len({fp for fp in self._history}),
            "truth_modified": False,
        }
