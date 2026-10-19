"""Bounded, deterministic redaction for common credential representations."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


MAX_TEXT_CHARS = 1_000_000
MAX_STRUCTURE_DEPTH = 20
MAX_STRUCTURE_NODES = 20_000
REDACTION_MARKER = "[REDACTED_SECRET]"


class TextSafetyError(ValueError):
    """Input cannot be processed within the bounded redaction contract."""


class SensitiveDataError(ValueError):
    """Sensitive content is forbidden at this trust boundary."""


@dataclass(frozen=True)
class RedactionResult:
    text: str
    count: int
    categories: tuple[str, ...]


_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private_key", re.compile(
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
        re.DOTALL,
    )),
    ("openai_or_openrouter_key", re.compile(r"\bsk-(?:proj-|or-v1-)?[A-Za-z0-9_-]{16,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{16,}=*\b", re.IGNORECASE)),
    ("jwt", re.compile(
        r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"
    )),
    ("assigned_secret", re.compile(
        r"(?i)\b(password|passwd|api[_-]?key|access[_-]?token|secret)"
        r"\s*[:=]\s*(['\"]?)[^\s'\"]{8,}\2"
    )),
)


def redact_sensitive(value: str) -> RedactionResult:
    if not isinstance(value, str):
        raise TypeError("redact_sensitive принимает только строку")
    if len(value) > MAX_TEXT_CHARS:
        raise TextSafetyError("Текст превышает безопасный лимит обработки")

    text = value
    count = 0
    categories: list[str] = []
    for category, pattern in _PATTERNS:
        text, replacements = pattern.subn(REDACTION_MARKER, text)
        if replacements:
            count += replacements
            categories.append(category)
    return RedactionResult(text=text, count=count, categories=tuple(categories))


def redact_structure(value: Any) -> tuple[Any, int]:
    """Redact every string value in a bounded JSON-like structure."""

    nodes = 0

    def visit(item: Any, depth: int) -> tuple[Any, int]:
        nonlocal nodes
        nodes += 1
        if nodes > MAX_STRUCTURE_NODES or depth > MAX_STRUCTURE_DEPTH:
            raise TextSafetyError("Структура превышает безопасный лимит обработки")
        if isinstance(item, str):
            result = redact_sensitive(item)
            return result.text, result.count
        if isinstance(item, dict):
            output = {}
            total = 0
            for key, nested in item.items():
                safe, count = visit(nested, depth + 1)
                output[key] = safe
                total += count
            return output, total
        if isinstance(item, list):
            output = []
            total = 0
            for nested in item:
                safe, count = visit(nested, depth + 1)
                output.append(safe)
                total += count
            return output, total
        if isinstance(item, tuple):
            output = []
            total = 0
            for nested in item:
                safe, count = visit(nested, depth + 1)
                output.append(safe)
                total += count
            return tuple(output), total
        return item, 0

    return visit(value, 0)
