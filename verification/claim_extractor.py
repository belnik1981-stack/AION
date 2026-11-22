"""Claim extraction helpers for candidate chat records.

The extractor is intentionally conservative. It prepares candidate claims for
verification but never marks them verified or promotes them.
"""
from __future__ import annotations

import json
import re
from typing import Any

from core.llm import ask_llm


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")


def heuristic_claims(candidate: dict[str, Any], max_claims: int = 8) -> list[str]:
    content = candidate.get("content", {}) if isinstance(candidate, dict) else {}
    assistant = str(content.get("assistant", "")).strip()
    if not assistant:
        return []

    claims: list[str] = []
    seen: set[str] = set()
    for sentence in _SENTENCE_SPLIT.split(assistant):
        text = " ".join(sentence.split()).strip(" -•\t\n")
        if len(text) < 30:
            continue
        lowered = text.lower()
        if lowered.startswith(("я думаю", "возможно", "вероятно", "например")):
            continue
        key = lowered
        if key not in seen:
            seen.add(key)
            claims.append(text)
        if len(claims) >= max_claims:
            break
    return claims


def agent_claims(candidate: dict[str, Any], max_claims: int = 8) -> list[str]:
    """Use configured AION LLM only to propose atomic factual claims.

    Output is treated as untrusted extraction. Verification remains separate.
    """
    content = candidate.get("content", {}) if isinstance(candidate, dict) else {}
    user = str(content.get("user", "")).strip()
    assistant = str(content.get("assistant", "")).strip()
    prompt = (
        "Extract only atomic factual claims that can be independently verified. "
        "Do not decide whether they are true. Exclude opinions, advice, commands, "
        "and purely subjective statements. Return only a JSON array of strings, "
        f"maximum {max_claims}.\n\nUSER:\n{user}\n\nASSISTANT:\n{assistant}"
    )
    raw = ask_llm(prompt).strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return heuristic_claims(candidate, max_claims=max_claims)
    if not isinstance(parsed, list):
        return heuristic_claims(candidate, max_claims=max_claims)
    claims = []
    for item in parsed:
        text = str(item).strip()
        if text and text not in claims:
            claims.append(text)
        if len(claims) >= max_claims:
            break
    return claims
