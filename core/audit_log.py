"""Minimal append-only audit events without prompts, answers, or credentials."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DIR = Path(
    os.getenv("AION_RUNTIME_DIR", str(ROOT / "runtime"))
).expanduser()
AUDIT_FILE = Path(
    os.getenv("AION_AUDIT_FILE", str(RUNTIME_DIR / "audit.jsonl"))
).expanduser()


def fingerprint_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]


def append_audit_event(event: str, **fields: Any) -> None:
    AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        AUDIT_FILE.parent.chmod(0o700)
    except OSError:
        pass

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **fields,
    }
    with AUDIT_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    try:
        AUDIT_FILE.chmod(0o600)
    except OSError:
        pass
