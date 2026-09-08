import os
import platform
import shutil
import sys
from pathlib import Path

from core.truth import truth_status, get_execution_limits
from providers.registry import provider_status

PROJECT_DIR = Path(__file__).resolve().parent.parent
REQUIRED_DIRS = ["core", "providers", "knowledge", "memory", "tests", "docs"]


def _print(status: str, message: str) -> None:
    print(f"[{status}] {message}")


def check_python() -> bool:
    ok = sys.version_info >= (3, 10)
    _print("OK" if ok else "FAIL", f"Python: {sys.version.split()[0]} (requires >= 3.10)")
    return ok


def check_os() -> bool:
    _print("OK", f"OS: {platform.system()} {platform.release()}")
    return True


def check_folders() -> bool:
    ok = True
    for folder in REQUIRED_DIRS:
        path = PROJECT_DIR / folder
        exists = path.is_dir()
        _print("OK" if exists else "FAIL", f"directory {folder}")
        ok = ok and exists
    return ok


def check_truth() -> bool:
    try:
        status = truth_status()
        limits = get_execution_limits()
        ok = bool(status["truth_exists"] and status["system_exists"])
        _print("OK" if ok else "FAIL", f"truth layer; limits={limits}")
        return ok
    except Exception as exc:
        _print("FAIL", f"truth layer: {exc}")
        return False


def check_provider() -> bool:
    try:
        status = provider_status()
        ok = status.get("status") == "ok"
        safe_status = {k: v for k, v in status.items() if "key" not in k.lower()}
        _print("OK" if ok else "FAIL", f"provider: {safe_status}")
        return ok
    except Exception as exc:
        _print("FAIL", f"provider configuration: {exc}")
        return False


def check_disk() -> bool:
    _, _, free = shutil.disk_usage(PROJECT_DIR)
    free_mb = free // (1024**2)
    ok = free_mb >= 100
    _print("OK" if ok else "FAIL", f"free disk: {free_mb} MB")
    return ok


def main() -> int:
    print("=== AION PRE-FLIGHT ===")
    checks = [
        check_python(),
        check_os(),
        check_folders(),
        check_truth(),
        check_provider(),
        check_disk(),
    ]
    ok = all(checks)
    print("=======================")
    print("PRE-FLIGHT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
