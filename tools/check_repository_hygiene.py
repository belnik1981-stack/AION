"""Fail-closed repository hygiene checks without echoing matched secrets."""
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


MAX_REVIEWED_FILE_BYTES = 2 * 1024 * 1024
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "trial_output"}
FORBIDDEN_SUFFIXES = {".docx", ".pdf", ".sdocx", ".zip", ".patch"}
KNOWN_TEST_VALUES = {
    "sk-or-v1-ABCDEFGHIJKLMNOPQRSTUVWX",
}

SECRET_RULES = {
    "openai_or_openrouter_key": re.compile(
        r"(?<![A-Za-z0-9])sk-(?:or-v1-)?[A-Za-z0-9_-]{20,}"
    ),
    "github_token": re.compile(r"(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{20,}"),
    "google_api_key": re.compile(r"(?<![A-Za-z0-9])AIza[0-9A-Za-z_-]{20,}"),
    "aws_access_key": re.compile(r"(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}"),
    "bearer_token": re.compile(
        r"(?<![A-Za-z0-9])Bearer\s+[A-Za-z0-9._~+/-]{20,}=*",
        re.IGNORECASE,
    ),
    "private_key": re.compile(
        r"-----BEGIN\s+(?:RSA\s+|EC\s+|OPENSSH\s+)?PRIVATE KEY-----"
    ),
}


@dataclass(frozen=True, order=True)
class Finding:
    path: str
    rule: str
    line: int = 0


def _iter_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        yield path


def _path_findings(relative: Path) -> list[Finding]:
    path_text = relative.as_posix()
    name = relative.name
    findings: list[Finding] = []
    if name.startswith("CONVERSATION_ORIGIN_") and relative.suffix.lower() == ".md":
        findings.append(Finding(path_text, "plaintext_origin_transcript"))
    if relative.suffix.lower() in FORBIDDEN_SUFFIXES:
        findings.append(Finding(path_text, "binary_or_transport_artifact"))
    if name == ".env" or name.startswith(".env."):
        findings.append(Finding(path_text, "tracked_environment_file"))
    if path_text in {"state.json", "pipeline_state.json", "project_summary.txt"}:
        findings.append(Finding(path_text, "tracked_runtime_or_user_state"))
    if (
        path_text.startswith("knowledge/episodic/")
        or path_text.startswith("knowledge/long_term/")
        or path_text.startswith("knowledge/candidates/")
        or path_text.startswith("knowledge/adaptive/")
        or path_text.startswith("logs/")
    ):
        findings.append(Finding(path_text, "tracked_runtime_or_user_state"))
    return findings


def scan_repository(root: str | Path) -> list[Finding]:
    base = Path(root).resolve()
    findings: list[Finding] = []
    for path in _iter_files(base):
        relative = path.relative_to(base)
        findings.extend(_path_findings(relative))
        size = path.stat().st_size
        if size > MAX_REVIEWED_FILE_BYTES:
            findings.append(Finding(relative.as_posix(), "oversized_unreviewed_file"))
            continue
        raw = path.read_bytes()
        if b"\x00" in raw:
            findings.append(Finding(relative.as_posix(), "binary_file_requires_review"))
            continue
        text = raw.decode("utf-8", errors="replace")
        for rule, pattern in SECRET_RULES.items():
            for match in pattern.finditer(text):
                if match.group(0) in KNOWN_TEST_VALUES:
                    continue
                line = text.count("\n", 0, match.start()) + 1
                findings.append(Finding(relative.as_posix(), rule, line))
    return sorted(set(findings))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    findings = scan_repository(args.root)
    if findings:
        print("REPOSITORY HYGIENE: FAIL")
        for item in findings:
            location = f":{item.line}" if item.line else ""
            print(f"- {item.path}{location}: {item.rule}")
        return 1
    print("REPOSITORY HYGIENE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
