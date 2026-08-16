"""
AION Truth Store

Системные правила и ограничения.
Рабочее ядро может только читать этот слой.
Автоматическая запись запрещена.
"""

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


class TruthError(Exception):
    """Ошибка слоя системной истины."""
    pass


def load_truth() -> dict:
    """Загрузить truth.json только для чтения."""

    if not TRUTH_FILE.exists():
        raise TruthError(
            f"Truth-файл отсутствует: {TRUTH_FILE}"
        )

    try:
        data = json.loads(
            TRUTH_FILE.read_text(
                encoding="utf-8"
            )
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise TruthError(
            f"Некорректный truth.json: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise TruthError(
            "Truth должен быть JSON-объектом"
        )

    return data


def load_system() -> dict:
    """Загрузить system.yaml только для чтения."""

    if not SYSTEM_FILE.exists():
        raise TruthError(
            f"System-файл отсутствует: {SYSTEM_FILE}"
        )

    if yaml is None:
        raise TruthError(
            "Для чтения system.yaml требуется PyYAML"
        )

    try:
        data = yaml.safe_load(
            SYSTEM_FILE.read_text(
                encoding="utf-8"
            )
        ) or {}
    except Exception as exc:
        raise TruthError(
            f"Некорректный system.yaml: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise TruthError(
            "system.yaml должен содержать объект"
        )

    return data


def get_principles() -> list[str]:
    """Получить принципы из truth.json."""

    truth = load_truth()
    principles = truth.get("principles", [])

    if not isinstance(principles, list):
        raise TruthError(
            "Поле 'principles' должно быть списком"
        )

    if not all(isinstance(item, str) for item in principles):
        raise TruthError(
            "Все элементы 'principles' должны быть строками"
        )

    return principles


def get_execution_limits() -> dict[str, int]:
    """Получить ограничения выполнения из system.yaml."""

    system = load_system()
    execution = system.get("execution", {})

    if not isinstance(execution, dict):
        raise TruthError(
            "Поле 'execution' в system.yaml должно быть объектом"
        )

    try:
        max_iterations = int(execution["max_iterations"])
        timeout_seconds = int(execution["timeout_seconds"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TruthError(
            "В system.yaml отсутствуют корректные execution limits"
        ) from exc

    if max_iterations <= 0:
        raise TruthError(
            "max_iterations должен быть > 0"
        )

    if timeout_seconds <= 0:
        raise TruthError(
            "timeout_seconds должен быть > 0"
        )

    return {
        "max_iterations": max_iterations,
        "timeout_seconds": timeout_seconds,
    }


def truth_status() -> dict:
    """Безопасная диагностика truth-слоя."""

    return {
        "truth_file": str(TRUTH_FILE),
        "truth_exists": TRUTH_FILE.exists(),
        "system_file": str(SYSTEM_FILE),
        "system_exists": SYSTEM_FILE.exists(),
        "read_only_by_design": True,
    }
