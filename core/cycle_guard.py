"""Cycle, oscillation and semantic-repeat guard for AION execution paths.

Detects exact repeats, revisited states, A-B-A-B oscillation and conservative
near-semantic repeats before an agent loop wastes additional iterations.
The guard does not decide truth; it only stops repeated execution states.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any


_WS = re.compile(r"\s+")
_TOKEN = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)
_STOP = {
    "и", "в", "во", "на", "с", "со", "к", "по", "для", "из", "от", "до", "а", "но",
    "что", "это", "как", "так", "же", "ли", "бы", "или", "при", "the", "a", "an", "and",
    "or", "to", "of", "in", "on", "for", "with", "is", "are", "be", "this", "that",
}


def _normalise(value: Any) -> str:
    if isinstance(value, str):
        return _WS.sub(" ", value.strip().lower())
    try:
        rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except TypeError:
        rendered = repr(value)
    return _WS.sub(" ", rendered.strip().lower())


def _semantic_tokens(value: Any) -> set[str]:
    text = _normalise(value)
    return {token for token in _TOKEN.findall(text) if len(token) >= 3 and token not in _STOP}


def _char_ngrams(value: Any, n: int = 4) -> set[str]:
    text = re.sub(r"[^a-zа-яё0-9]+", "", _normalise(value))
    if len(text) < n:
        return {text} if text else set()
    return {text[i:i+n] for i in range(len(text) - n + 1)}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def semantic_similarity(left: Any, right: Any) -> float:
    token_score = _jaccard(_semantic_tokens(left), _semantic_tokens(right))
    ngram_score = _jaccard(_char_ngrams(left), _char_ngrams(right))
    return round(max(token_score, 0.55 * token_score + 0.45 * ngram_score), 4)


def state_fingerprint(stage: str, value: Any, semantic_key: str | None = None) -> str:
    semantic_part = semantic_key.strip().lower() if semantic_key else _normalise(value)
    payload = f"{stage.strip().lower()}|{semantic_part}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CycleObservation:
    cycle_detected: bool
    cycle_type: str | None
    occurrences: int
    reason: str | None
    similarity: float | None = None


class CycleGuard:
    def __init__(self, max_history: int = 12, semantic_threshold: float = 0.82) -> None:
        self.max_history = max(4, int(max_history))
        self.semantic_threshold = max(0.60, min(0.98, float(semantic_threshold)))
        self._history: list[str] = []
        self._values: list[Any] = []
        self._stages: list[str] = []
        self._semantic_keys: list[str | None] = []
        self._counts: dict[str, int] = {}

    def observe(self, stage: str, value: Any, semantic_key: str | None = None) -> CycleObservation:
        stage_norm = stage.strip().lower()
        key_norm = semantic_key.strip().lower() if semantic_key else None
        previous_values = list(self._values)
        previous_stages = list(self._stages)
        previous_keys = list(self._semantic_keys)

        fp = state_fingerprint(stage_norm, value, key_norm)
        count = self._counts.get(fp, 0) + 1
        self._counts[fp] = count
        self._history.append(fp)
        self._values.append(value)
        self._stages.append(stage_norm)
        self._semantic_keys.append(key_norm)

        if len(self._history) > self.max_history:
            removed = self._history.pop(0)
            self._values.pop(0)
            self._stages.pop(0)
            self._semantic_keys.pop(0)
            self._counts[removed] = max(0, self._counts.get(removed, 1) - 1)
            count = self._counts.get(fp, count)

        # Same explicit interpretation under different wording has priority over
        # generic fingerprint repetition, because semantic_key participates in fp.
        if key_norm:
            for previous_stage, previous_key, previous_value in zip(previous_stages, previous_keys, previous_values):
                if previous_stage == stage_norm and previous_key == key_norm:
                    if _normalise(previous_value) != _normalise(value):
                        return CycleObservation(
                            True,
                            "same_interpretation",
                            count,
                            "same_semantic_key_repeated_with_different_wording",
                            1.0,
                        )

        if len(self._history) >= 2 and self._history[-1] == self._history[-2]:
            return CycleObservation(True, "direct_repeat", count, "same_state_repeated", 1.0)

        if len(self._history) >= 4:
            a, b, c, d = self._history[-4:]
            if a == c and b == d and a != b:
                return CycleObservation(
                    True,
                    "two_state_oscillation",
                    max(self._counts[a], self._counts[b]),
                    "a_b_a_b_oscillation",
                    1.0,
                )

        if count >= 2:
            return CycleObservation(
                True,
                "revisited_state",
                count,
                "previous_state_revisited_without_new_information",
                1.0,
            )

        current_tokens = _semantic_tokens(value)
        if len(current_tokens) >= 4:
            for previous_stage, previous_value in zip(previous_stages, previous_values):
                if previous_stage != stage_norm:
                    continue
                previous_tokens = _semantic_tokens(previous_value)
                if len(previous_tokens) < 4:
                    continue
                similarity = semantic_similarity(previous_value, value)
                if similarity >= self.semantic_threshold:
                    return CycleObservation(
                        True,
                        "semantic_rephrase",
                        2,
                        "same_interpretation_rephrased_without_material_new_information",
                        similarity,
                    )

        return CycleObservation(False, None, count, None, None)

    def status(self) -> dict[str, Any]:
        return {
            "observations": len(self._history),
            "unique_states": len({fp for fp in self._history}),
            "semantic_threshold": self.semantic_threshold,
            "truth_modified": False,
        }
