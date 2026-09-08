"""AION Truth Store: validated, read-only configuration."""
from __future__ import annotations

import json
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None


ROOT = Path(__file__).resolve().parent.parent
TRUTH_DIR = ROOT / "knowledge" / "truth"
TRUTH_FILE = TRUTH_DIR / "truth.json"
SYSTEM_FILE = TRUTH_DIR / "system.yaml"

_LIMIT_BOUNDS = {
    "max_iterations": (1, 10),
    "timeout_seconds": (1, 120),
    "max_api_calls": (1, 20),
    "max_total_seconds": (1, 600),
    "max_input_chars": (1, 100_000),
    "max_prompt_chars": (1, 200_000),
    "max_response_bytes": (1_024, 10_485_760),
    "max_tokens": (1, 8_192),
    "max_request_bytes": (1_024, 1_048_576),
}


class TruthError(Exception):
    """Error in the immutable Truth configuration."""


def load_truth() -> dict:
    if not TRUTH_FILE.exists():
        raise TruthError(f"Truth file is missing: {TRUTH_FILE}")
    try:
        data = json.loads(TRUTH_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TruthError(f"Invalid truth.json: {exc}") from exc
    if not isinstance(data, dict):
        raise TruthError("truth.json must contain an object")
    return data


def load_system() -> dict:
    if not SYSTEM_FILE.exists():
        raise TruthError(f"System file is missing: {SYSTEM_FILE}")
    if yaml is None:
        raise TruthError("PyYAML is required to read system.yaml")
    try:
        data = yaml.safe_load(SYSTEM_FILE.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        raise TruthError(f"Invalid system.yaml: {exc}") from exc
    if not isinstance(data, dict):
        raise TruthError("system.yaml must contain an object")
    return data


def get_principles() -> list[str]:
    principles = load_truth().get("principles", [])
    if not isinstance(principles, list):
        raise TruthError("'principles' must be a list")
    if not all(isinstance(item, str) for item in principles):
        raise TruthError("Every principle must be a string")
    return principles


def get_execution_limits() -> dict[str, int]:
    execution = load_system().get("execution", {})
    if not isinstance(execution, dict):
        raise TruthError("'execution' in system.yaml must be an object")

    values: dict[str, int] = {}
    for name, (minimum, maximum) in _LIMIT_BOUNDS.items():
        try:
            value = int(execution[name])
        except (KeyError, TypeError, ValueError) as exc:
            raise TruthError(f"Missing or invalid execution limit: {name}") from exc
        if not minimum <= value <= maximum:
            raise TruthError(
                f"{name} must be between {minimum} and {maximum}, got {value}"
            )
        values[name] = value

    if values["timeout_seconds"] > values["max_total_seconds"]:
        raise TruthError("timeout_seconds cannot exceed max_total_seconds")
    return values


def truth_status() -> dict:
    return {
        "truth_file": str(TRUTH_FILE),
        "truth_exists": TRUTH_FILE.exists(),
        "system_file": str(SYSTEM_FILE),
        "system_exists": SYSTEM_FILE.exists(),
        "read_only_by_design": True,
        "automation_write_api_present": False,
    }
