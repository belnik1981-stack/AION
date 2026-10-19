"""Deterministic claim/disagreement registry for independent model outputs.

This module records what models said. It does not decide that repeated text is
true, and it never converts model agreement into external verification.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from learning.quarantine import assess_quarantine


MAX_CLAIMS_PER_MODEL = 16
MAX_CLAIM_CHARS = 600
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+|[\r\n]+")
_URL = re.compile(r"https?://[^\s<>\]\[(){}\"']+", re.IGNORECASE)
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_NEGATIONS = {"not", "no", "never", "without", "не", "нет", "никогда", "без"}

_PREDICTION_MARKERS = (
    "will ", "likely", "probably", "forecast", "ожидается", "вероятно",
    "скорее всего", "прогноз", "будет ",
)
_ASSUMPTION_MARKERS = (
    "assume", "hypothesis", "suppose", "perhaps", "maybe", "предполож",
    "гипотез", "возможно", "допустим",
)
_UNCERTAINTY_MARKERS = (
    "unknown", "uncertain", "cannot verify", "not enough evidence",
    "неизвест", "неопредел", "невозможно проверить", "недостаточно доказательств",
)


def _tokens(text: str, *, remove_negation: bool = False) -> set[str]:
    tokens: set[str] = set()
    for match in _TOKEN.findall(text.casefold()):
        token = match
        if remove_negation and token in _NEGATIONS:
            continue
        if len(token) > 5 and token.endswith("s") and token.isascii():
            token = token[:-1]
        tokens.add(token)
    return tokens


def _polarity(text: str) -> str:
    tokens = _tokens(text)
    return "negative" if tokens.intersection(_NEGATIONS) else "positive"


def _similarity(left: str, right: str, *, remove_negation: bool = False) -> float:
    left_tokens = _tokens(left, remove_negation=remove_negation)
    right_tokens = _tokens(right, remove_negation=remove_negation)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _claim_type(text: str) -> str:
    lowered = text.casefold()
    if any(marker in lowered for marker in _UNCERTAINTY_MARKERS):
        return "uncertainty_statement"
    if any(marker in lowered for marker in _ASSUMPTION_MARKERS):
        return "assumption"
    if any(marker in lowered for marker in _PREDICTION_MARKERS):
        return "prediction"
    if lowered.startswith(("fact:", "факт:")):
        return "claimed_fact_unverified"
    return "unverified_assertion"


def _sentences(text: str) -> list[str]:
    claims: list[str] = []
    for part in _SENTENCE_SPLIT.split(text):
        cleaned = " ".join(part.strip(" \t-•").split())
        if not cleaned:
            continue
        claims.append(cleaned[:MAX_CLAIM_CHARS])
        if len(claims) >= MAX_CLAIMS_PER_MODEL:
            break
    return claims


def _observation(model_id: str, index: int, text: str) -> dict[str, Any]:
    claim_id = "model-claim-" + hashlib.sha256(
        f"{model_id}\0{index}\0{text}".encode("utf-8")
    ).hexdigest()[:20]
    urls = [url.rstrip(".,;:!?") for url in _URL.findall(text)][:8]
    quarantine = assess_quarantine(
        importance=0.50,
        cleanliness=0.50,
        negative_impact=0.50,
    ).to_dict()
    # Raw model output can never auto-promote, even when the generic numeric
    # quarantine policy would otherwise allow it.
    quarantine["auto_promote_allowed"] = False
    quarantine["learning_allowed"] = False
    quarantine["policy_override"] = "unverified_model_output"
    return {
        "claim_id": claim_id,
        "model_id": model_id,
        "text": text,
        "claim_type": _claim_type(text),
        "polarity": _polarity(text),
        "reported_sources": [
            {"url": url, "status": "model_reported_unverified"} for url in urls
        ],
        "verification": {
            "status": "unverified",
            "scope": "model_output_only",
            "objective_truth_verified": False,
        },
        "quarantine": quarantine,
    }


def _components(observations: list[dict[str, Any]], pairs: list[tuple[int, int]]) -> list[list[int]]:
    parent = list(range(len(observations)))

    def find(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: int, right: int) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[b] = a

    for left, right in pairs:
        union(left, right)
    groups: dict[int, list[int]] = {}
    for index in range(len(observations)):
        root = find(index)
        groups.setdefault(root, []).append(index)
    return [indices for indices in groups.values() if len(indices) > 1]


def build_claim_registry(
    model_answers: dict[str, str],
    evidence_claims: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    observations: list[dict[str, Any]] = []
    for model_id, answer in model_answers.items():
        if not isinstance(answer, str) or not answer.strip() or answer.startswith("[ОШИБКА"):
            continue
        for index, text in enumerate(_sentences(answer), start=1):
            observations.append(_observation(model_id, index, text))

    agreement_pairs: list[tuple[int, int]] = []
    contradictions: list[dict[str, Any]] = []
    involved_in_contradiction: set[int] = set()
    for left in range(len(observations)):
        for right in range(left + 1, len(observations)):
            a, b = observations[left], observations[right]
            if a["model_id"] == b["model_id"]:
                continue
            same_polarity = a["polarity"] == b["polarity"]
            similarity = _similarity(a["text"], b["text"])
            base_similarity = _similarity(a["text"], b["text"], remove_negation=True)
            if same_polarity and similarity >= 0.80:
                agreement_pairs.append((left, right))
            elif not same_polarity and base_similarity >= 0.72:
                contradictions.append({
                    "left_claim_id": a["claim_id"],
                    "right_claim_id": b["claim_id"],
                    "models": [a["model_id"], b["model_id"]],
                    "similarity_without_negation": round(base_similarity, 4),
                    "status": "unresolved_possible_contradiction",
                })
                involved_in_contradiction.update({left, right})

    agreement_groups = []
    agreed_indices: set[int] = set()
    for indices in _components(observations, agreement_pairs):
        models = sorted({observations[index]["model_id"] for index in indices})
        if len(models) < 2:
            continue
        agreed_indices.update(indices)
        agreement_groups.append({
            "claim_ids": [observations[index]["claim_id"] for index in indices],
            "models": models,
            "status": "multi_model_agreement_not_external_evidence",
            "objective_truth_verified": False,
        })

    evidence_claims = evidence_claims or []
    evidence_alignments: list[dict[str, Any]] = []
    for observation in observations:
        for evidence in evidence_claims:
            text = evidence.get("text")
            if not isinstance(text, str):
                continue
            base_similarity = _similarity(observation["text"], text, remove_negation=True)
            if base_similarity < 0.80:
                continue
            same_polarity = observation["polarity"] == _polarity(text)
            evidence_alignments.append({
                "model_claim_id": observation["claim_id"],
                "evidence_claim_id": evidence.get("claim_id"),
                "relation": "aligned" if same_polarity else "contradicts",
                "similarity": round(base_similarity, 4),
                "evidence_scope": "validated_bundle_analysis_only",
                "objective_truth_verified": False,
            })

    unresolved_indices = set(range(len(observations))) - agreed_indices - involved_in_contradiction
    return {
        "schema_version": "aion-claim-registry-v1",
        "observations": observations,
        "agreement_groups": agreement_groups,
        "contradictions": contradictions,
        "divergent_claim_ids": [observations[index]["claim_id"] for index in sorted(unresolved_indices)],
        "evidence_alignments": evidence_alignments,
        "model_reported_sources": [
            {"claim_id": item["claim_id"], **source}
            for item in observations
            for source in item["reported_sources"]
        ],
        "verification": {
            "scope": (
                "model_comparison_plus_analysis_only_evidence"
                if evidence_claims else "model_comparison_only"
            ),
            "objective_truth_verified": False,
            "external_verification_performed": False,
            "note": "Agreement is preserved as an observation, not accepted as proof.",
        },
    }


def format_registry_for_prompt(registry: dict[str, Any], max_chars: int = 6000) -> str:
    lines = [
        "DETERMINISTIC CLAIM REGISTRY (comparison only; not proof):",
        f"- observations: {len(registry.get('observations', []))}",
        f"- agreement groups: {len(registry.get('agreement_groups', []))}",
        f"- possible contradictions: {len(registry.get('contradictions', []))}",
        f"- divergent claims retained: {len(registry.get('divergent_claim_ids', []))}",
        "Rule: do not turn agreement into fact; retain unresolved contradictions and minority claims.",
    ]
    by_id = {item["claim_id"]: item for item in registry.get("observations", [])}
    for conflict in registry.get("contradictions", [])[:8]:
        left = by_id.get(conflict["left_claim_id"], {})
        right = by_id.get(conflict["right_claim_id"], {})
        lines.append(f"- CONTRADICTION? {left.get('text', '')} <> {right.get('text', '')}")
    return "\n".join(lines)[:max_chars]
