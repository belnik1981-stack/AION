"""Controlled import of chat exports into AION candidate knowledge.

Imported chat data is untrusted. It is stored separately from truth and long-term
knowledge and is never promoted automatically.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from security.redaction import redact_sensitive

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CANDIDATE_STORE = ROOT / "knowledge" / "candidates" / "chat_candidates.jsonl"

_ERROR_MARKERS = (
    "[ОШИБКА",
    "[ERROR",
    "Traceback (most recent call last)",
)


class ChatImportError(ValueError):
    """Raised when the chat export cannot be parsed safely."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalise_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    elif isinstance(value, list):
        text = "\n".join(_normalise_text(item) for item in value)
    elif isinstance(value, dict):
        if "text" in value:
            text = _normalise_text(value.get("text"))
        elif "parts" in value:
            text = _normalise_text(value.get("parts"))
        else:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    else:
        text = str(value)
    return re.sub(r"[ \t]+", " ", text).strip()


def _redact_secrets(text: str) -> tuple[str, bool]:
    result = redact_sensitive(text)
    return result.text, result.count > 0


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, dict):
        content_type = content.get("content_type")
        if content_type in {"text", "multimodal_text"}:
            return _normalise_text(content.get("parts", []))
        return _normalise_text(content.get("parts") or content.get("text") or "")
    return _normalise_text(content)


def _linear_messages_from_mapping(conversation: dict[str, Any]) -> list[dict[str, Any]]:
    mapping = conversation.get("mapping")
    if not isinstance(mapping, dict):
        return []

    current = conversation.get("current_node")
    chain: list[dict[str, Any]] = []
    seen: set[str] = set()

    if isinstance(current, str) and current in mapping:
        node_id: str | None = current
        while node_id and node_id in mapping and node_id not in seen:
            seen.add(node_id)
            node = mapping[node_id]
            if isinstance(node, dict):
                message = node.get("message")
                if isinstance(message, dict):
                    chain.append(message)
                parent = node.get("parent")
                node_id = parent if isinstance(parent, str) else None
            else:
                break
        chain.reverse()
        return chain

    messages = []
    for node in mapping.values():
        if not isinstance(node, dict):
            continue
        message = node.get("message")
        if not isinstance(message, dict):
            continue
        create_time = message.get("create_time")
        messages.append((create_time if isinstance(create_time, (int, float)) else 0, message))
    messages.sort(key=lambda item: item[0])
    return [message for _, message in messages]


def _linear_messages(conversation: dict[str, Any]) -> list[dict[str, Any]]:
    messages = conversation.get("messages")
    if isinstance(messages, list):
        return [item for item in messages if isinstance(item, dict)]
    return _linear_messages_from_mapping(conversation)


def _role(message: dict[str, Any]) -> str:
    author = message.get("author")
    if isinstance(author, dict):
        role = author.get("role")
        if isinstance(role, str):
            return role.lower()
    role = message.get("role")
    return role.lower() if isinstance(role, str) else ""


def _quality_flags(user_text: str, assistant_text: str, redacted: bool) -> list[str]:
    flags: list[str] = []
    combined = f"{user_text}\n{assistant_text}".strip()

    if redacted:
        flags.append("secret_redacted")
    if len(combined) < 40:
        flags.append("very_short_exchange")
    if any(marker.lower() in assistant_text.lower() for marker in _ERROR_MARKERS):
        flags.append("assistant_error_output")
    if not assistant_text:
        flags.append("missing_assistant_reply")
    return flags


def _iter_exchanges(conversation: dict[str, Any]) -> Iterable[dict[str, Any]]:
    pending_user: dict[str, Any] | None = None
    turn_index = 0

    for message in _linear_messages(conversation):
        role = _role(message)
        if role not in {"user", "assistant"}:
            continue

        text = _message_text(message)
        if not text:
            continue

        if role == "user":
            if pending_user is not None:
                turn_index += 1
                yield {
                    "turn_index": turn_index,
                    "user": pending_user["text"],
                    "assistant": "",
                    "message_ids": [pending_user.get("id")],
                }
            pending_user = {"text": text, "id": message.get("id")}
            continue

        if pending_user is None:
            continue

        turn_index += 1
        yield {
            "turn_index": turn_index,
            "user": pending_user["text"],
            "assistant": text,
            "message_ids": [pending_user.get("id"), message.get("id")],
        }
        pending_user = None

    if pending_user is not None:
        turn_index += 1
        yield {
            "turn_index": turn_index,
            "user": pending_user["text"],
            "assistant": "",
            "message_ids": [pending_user.get("id")],
        }


def _fingerprint(user_text: str, assistant_text: str) -> str:
    payload = f"user:{user_text}\nassistant:{assistant_text}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_existing_fingerprints(store_path: Path) -> set[str]:
    if not store_path.exists():
        return set()

    fingerprints: set[str] = set()
    with store_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            fingerprint = item.get("fingerprint")
            if isinstance(fingerprint, str):
                fingerprints.add(fingerprint)
    return fingerprints


def _conversation_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        conversations = payload.get("conversations")
        if isinstance(conversations, list):
            return [item for item in conversations if isinstance(item, dict)]
        if "mapping" in payload or "messages" in payload:
            return [payload]
    raise ChatImportError(
        "Ожидается ChatGPT conversations.json, список бесед или объект с messages/mapping."
    )


def import_chat_export(
    export_path: str | Path,
    store_path: str | Path = DEFAULT_CANDIDATE_STORE,
) -> dict[str, Any]:
    export = Path(export_path).expanduser().resolve()
    destination = Path(store_path).expanduser().resolve()

    try:
        payload = json.loads(export.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ChatImportError(f"Файл не найден: {export}") from exc
    except json.JSONDecodeError as exc:
        raise ChatImportError(f"Некорректный JSON: {exc}") from exc

    conversations = _conversation_list(payload)
    destination.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_existing_fingerprints(destination)

    imported = 0
    duplicates = 0
    redacted_count = 0
    flagged = 0

    with destination.open("a", encoding="utf-8") as handle:
        for conversation_index, conversation in enumerate(conversations, start=1):
            conversation_id = str(
                conversation.get("id")
                or conversation.get("conversation_id")
                or f"conversation-{conversation_index}"
            )
            title = _normalise_text(conversation.get("title")) or "Untitled conversation"

            for exchange in _iter_exchanges(conversation):
                user_text, user_redacted = _redact_secrets(exchange["user"])
                assistant_text, assistant_redacted = _redact_secrets(exchange["assistant"])
                was_redacted = user_redacted or assistant_redacted
                fingerprint = _fingerprint(user_text, assistant_text)

                if fingerprint in existing:
                    duplicates += 1
                    continue

                flags = _quality_flags(user_text, assistant_text, was_redacted)
                record = {
                    "candidate_id": f"chat-{fingerprint[:16]}",
                    "source": {
                        "type": "chat_export",
                        "conversation_id": conversation_id,
                        "title": title,
                        "turn_index": exchange["turn_index"],
                        "message_ids": [
                            str(value) for value in exchange["message_ids"] if value
                        ],
                    },
                    "content": {
                        "user": user_text,
                        "assistant": assistant_text,
                    },
                    "fingerprint": fingerprint,
                    "status": "candidate",
                    "verification": {
                        "state": "unverified",
                        "evidence_score": None,
                        "contradictions": [],
                        "reviewed_by": None,
                    },
                    "quality_flags": flags,
                    "imported_at": _utc_now(),
                }
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                existing.add(fingerprint)
                imported += 1
                if was_redacted:
                    redacted_count += 1
                if flags:
                    flagged += 1

    return {
        "status": "ok",
        "source": str(export),
        "store": str(destination),
        "conversations_seen": len(conversations),
        "imported": imported,
        "duplicates_skipped": duplicates,
        "records_with_redactions": redacted_count,
        "records_flagged_for_review": flagged,
        "truth_modified": False,
        "long_term_modified": False,
    }


def candidate_store_status(
    store_path: str | Path = DEFAULT_CANDIDATE_STORE,
) -> dict[str, Any]:
    path = Path(store_path).expanduser().resolve()
    records = 0
    unverified = 0
    flagged = 0

    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                records += 1
                if item.get("verification", {}).get("state") == "unverified":
                    unverified += 1
                if item.get("quality_flags"):
                    flagged += 1

    return {
        "store": str(path),
        "exists": path.exists(),
        "records": records,
        "unverified": unverified,
        "flagged": flagged,
        "truth_modified": False,
    }
