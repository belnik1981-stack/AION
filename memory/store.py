"""
AION Memory Store

Рабочая память отделена от системной истины.
"""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MEMORY_DIR = ROOT / "knowledge" / "episodic"
MEMORY_FILE = MEMORY_DIR / "memory.json"


class MemoryError(Exception):
    """Ошибка памяти."""
    pass


def load_memory() -> list:
    """Загрузить эпизодическую память."""

    if not MEMORY_FILE.exists():
        return []

    try:
        data = json.loads(
            MEMORY_FILE.read_text(
                encoding="utf-8"
            )
        )
    except json.JSONDecodeError as exc:
        raise MemoryError(
            f"Некорректный memory JSON: {exc}"
        ) from exc

    if not isinstance(data, list):
        raise MemoryError(
            "Память должна быть списком"
        )

    return data


def save_memory(entries: list) -> None:
    """Сохранить эпизодическую память."""

    if not isinstance(entries, list):
        raise MemoryError(
            "entries должен быть списком"
        )

    MEMORY_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    MEMORY_FILE.write_text(
        json.dumps(
            entries,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def memory_status() -> dict:
    return {
        "file": str(MEMORY_FILE),
        "exists": MEMORY_FILE.exists(),
        "entries": len(load_memory()),
    }
