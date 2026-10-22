"""Validate a completed offline acceptance stage before reusing it.

The checkpoint is a local execution record, not a claim of external truth.
Only a completed offline stage writes it; corrupt or missing evidence forces
the stage to run again.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile


MARKERS = ("[PASS] OFFLINE LIFE TRIAL", "[PASS] Truth unchanged after offline tests")


def checkpoint_path(report_dir: Path, revision: str, scope: str) -> Path:
    return report_dir / f"offline-{scope}-{revision}.json"


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def valid_log(path: Path) -> bool:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 16 * 1024 * 1024:
        return False
    content = path.read_text(encoding="utf-8", errors="replace")
    return all(marker in content for marker in MARKERS) and "[ACCEPTANCE FAIL]" not in content


def verify(report_dir: Path, revision: str, scope: str, truth: str, runtime: str) -> bool:
    try:
        record_file = checkpoint_path(report_dir, revision, scope)
        if record_file.is_symlink():
            return False
        record = json.loads(record_file.read_text(encoding="utf-8"))
        if not isinstance(record, dict):
            return False
        expected = {
            "schema_version": "aion-offline-checkpoint-v1",
            "revision": revision,
            "scope": scope,
            "truth_digest": truth,
            "runtime_digest": runtime,
            "python_version": list(sys.version_info[:3]),
        }
        if any(record.get(key) != value for key, value in expected.items()):
            return False
        basename = record.get("log")
        if not isinstance(basename, str) or Path(basename).name != basename:
            return False
        log = report_dir / basename
        return valid_log(log) and record.get("log_sha256") == digest(log)
    except (OSError, ValueError, TypeError, KeyError):
        return False


def record(report_dir: Path, revision: str, scope: str, truth: str, runtime: str, log: Path) -> None:
    report_dir = report_dir.resolve()
    if log.parent.resolve() != report_dir or not valid_log(log):
        raise ValueError("Offline stage log is missing or incomplete")
    payload = {
        "schema_version": "aion-offline-checkpoint-v1",
        "revision": revision,
        "scope": scope,
        "truth_digest": truth,
        "runtime_digest": runtime,
        "python_version": list(sys.version_info[:3]),
        "log": log.name,
        "log_sha256": digest(log),
    }
    target = checkpoint_path(report_dir, revision, scope)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=report_dir,
                                     prefix=".offline-", delete=False) as stream:
        temp = Path(stream.name)
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    try:
        temp.chmod(0o600)
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)


def main() -> int:
    if len(sys.argv) not in (7, 8) or sys.argv[1] not in ("verify", "record"):
        raise SystemExit("usage: acceptance_checkpoint.py verify|record DIR REV SCOPE TRUTH RUNTIME [LOG]")
    action, directory, revision, scope, truth, runtime = sys.argv[1:7]
    report_dir = Path(directory)
    if action == "verify" and len(sys.argv) == 7:
        return 0 if verify(report_dir, revision, scope, truth, runtime) else 1
    if action == "record" and len(sys.argv) == 8:
        record(report_dir, revision, scope, truth, runtime, Path(sys.argv[7]))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
