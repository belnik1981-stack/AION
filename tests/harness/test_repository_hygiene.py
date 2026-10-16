import tempfile
from pathlib import Path

from tools.check_repository_hygiene import scan_repository


ROOT = Path(__file__).resolve().parents[2]


findings = scan_repository(ROOT)
assert not findings, [f"{item.path}:{item.rule}" for item in findings]

with tempfile.TemporaryDirectory() as tmp:
    test_root = Path(tmp)
    (test_root / "safe.txt").write_text("safe fixture", encoding="utf-8")
    assert scan_repository(test_root) == []

    secret = "ghp_" + ("A" * 36)
    (test_root / "secret.txt").write_text(secret, encoding="utf-8")
    secret_findings = scan_repository(test_root)
    assert any(item.rule == "github_token" for item in secret_findings)

    (test_root / "secret.txt").unlink()
    (test_root / "CONVERSATION_ORIGIN_private.md").write_text(
        "private origin material", encoding="utf-8"
    )
    transcript_findings = scan_repository(test_root)
    assert any(item.rule == "plaintext_origin_transcript" for item in transcript_findings)

print("REPOSITORY HYGIENE TEST: PASS")
