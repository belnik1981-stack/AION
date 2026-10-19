"""Crash-safe local storage primitives used by AION runtime state."""

from .atomic_json import (
    JsonCorruptionError,
    JsonRecoveryWarning,
    JsonStorageError,
    append_jsonl_record,
    atomic_write_json,
    backup_path,
    load_json,
    update_json,
)

__all__ = [
    "JsonCorruptionError",
    "JsonRecoveryWarning",
    "JsonStorageError",
    "append_jsonl_record",
    "atomic_write_json",
    "backup_path",
    "load_json",
    "update_json",
]
