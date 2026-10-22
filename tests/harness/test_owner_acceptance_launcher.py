"""Exercise the owner launcher without network, API calls, or project memory."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "scripts" / "owner_acceptance_test.sh"


def run(*args: str, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", *args],
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
    )


syntax = subprocess.run(
    ["bash", "-n", str(LAUNCHER)],
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    check=False,
)
assert syntax.returncode == 0, syntax.stdout

help_result = run(str(LAUNCHER), "--help", cwd=ROOT, env=os.environ.copy())
assert help_result.returncode == 0, help_result.stdout
assert "--local-revision" in help_result.stdout
assert "--live" in help_result.stdout

with tempfile.TemporaryDirectory() as temp_dir:
    base = Path(temp_dir)
    project = base / "project"
    (project / "scripts").mkdir(parents=True)
    (project / "tools").mkdir(parents=True)
    (project / "knowledge" / "truth").mkdir(parents=True)
    (project / "knowledge" / "episodic").mkdir(parents=True)
    shutil.copy2(LAUNCHER, project / "scripts" / LAUNCHER.name)
    shutil.copy2(ROOT / "tools" / "acceptance_checkpoint.py", project / "tools" / "acceptance_checkpoint.py")
    (project / "scripts" / "cloud_check.sh").write_text(
        "#!/usr/bin/env bash\nset -eu\n"
        "if printenv AION_EXPECTED_SHA >/dev/null; then exit 99; fi\n"
        "echo run >> \"$AION_FAKE_OFFLINE_COUNT\"\n"
        "echo '[PASS] Truth unchanged after offline tests'\n"
        "echo '[PASS] OFFLINE LIFE TRIAL'\n",
        encoding="utf-8",
    )
    (project / "knowledge" / "truth" / "truth.json").write_text(
        '{"principles": ["test-only"]}\n', encoding="utf-8"
    )
    (project / "knowledge" / "truth" / "system.yaml").write_text(
        "limits:\n  max_iterations: 1\n", encoding="utf-8"
    )
    memory = project / "knowledge" / "episodic" / "history.json"
    memory.write_text('[{"user": "kept", "ai": "kept"}]\n', encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "test-branch"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.name", "AION Test"], cwd=project, check=True)
    subprocess.run(["git", "add", "."], cwd=project, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "fixture"], cwd=project, check=True)
    fixture_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=project, text=True).strip()

    report_dir = base / "reports"
    temp_root = base / "temporary"
    temp_root.mkdir()
    env = os.environ.copy()
    env.update(
        {
            "AION_TEST_REPORT_DIR": str(report_dir),
            "AION_ACCEPTANCE_VENV_DIR": str(base / "venv-outside-project"),
            "TMPDIR": str(temp_root),
            "AION_EXPECTED_SHA": fixture_sha,
            "AION_FAKE_OFFLINE_COUNT": str(base / "offline-count.txt"),
        }
    )
    before = memory.read_bytes()
    accepted = run(
        "scripts/owner_acceptance_test.sh",
        "--local-revision",
        cwd=project,
        env=env,
    )
    assert accepted.returncode == 0, accepted.stdout
    assert "[ACCEPTANCE PASS]" in accepted.stdout
    assert "live=SKIP" in accepted.stdout
    assert "Primary runtime and memory unchanged" in accepted.stdout
    assert memory.read_bytes() == before
    assert list(report_dir.glob("owner-acceptance-*.json"))
    assert not list(temp_root.glob("aion-owner-acceptance.*"))
    assert (base / "offline-count.txt").read_text().count("run") == 1

    resumed = run("scripts/owner_acceptance_test.sh", "--local-revision", cwd=project, env=env)
    assert resumed.returncode == 0, resumed.stdout
    assert "[STAGE REUSED] offline_life_trial" in resumed.stdout
    assert (base / "offline-count.txt").read_text().count("run") == 1

    checkpoint_log = next(report_dir.glob("offline-*.log"))
    checkpoint_log.write_text("corrupted evidence\n", encoding="utf-8")
    rerun = run("scripts/owner_acceptance_test.sh", "--local-revision", cwd=project, env=env)
    assert rerun.returncode == 0, rerun.stdout
    assert "[STAGE PENDING] offline_life_trial" in rerun.stdout
    assert (base / "offline-count.txt").read_text().count("run") == 2

    runtime_state = project / "state.json"
    runtime_state.write_text('{"changed": true}\n', encoding="utf-8")
    changed_env = run("scripts/owner_acceptance_test.sh", "--local-revision", cwd=project, env=env)
    assert changed_env.returncode == 0, changed_env.stdout
    assert "[STAGE PENDING] offline_life_trial" in changed_env.stdout
    assert (base / "offline-count.txt").read_text().count("run") == 3
    runtime_state.unlink()

    external_history = base / "external-history.json"
    external_history.write_text('[{"outside": true}]\n', encoding="utf-8")
    runtime_link = project / "knowledge" / "episodic" / "external.json"
    runtime_link.symlink_to(external_history)
    linked_data = run("scripts/owner_acceptance_test.sh", "--local-revision", cwd=project, env=env)
    assert linked_data.returncode != 0
    assert "Symlinked protected runtime data" in linked_data.stdout
    runtime_link.unlink()

    protected_report_env = dict(env)
    protected_report_env["AION_TEST_REPORT_DIR"] = str(
        project / "knowledge" / "episodic" / "reports"
    )
    protected_report = run(
        "scripts/owner_acceptance_test.sh",
        "--local-revision",
        cwd=project,
        env=protected_report_env,
    )
    assert protected_report.returncode != 0
    assert "Report directory overlaps protected project data" in protected_report.stdout
    assert memory.read_bytes() == before

    protected_tmp_env = dict(env)
    protected_tmp_env["TMPDIR"] = str(project / "temporary")
    protected_tmp = run(
        "scripts/owner_acceptance_test.sh",
        "--local-revision",
        cwd=project,
        env=protected_tmp_env,
    )
    assert protected_tmp.returncode != 0
    assert "TMPDIR must be outside the repository" in protected_tmp.stdout
    assert memory.read_bytes() == before

    release_wrong_branch = run(
        "scripts/owner_acceptance_test.sh",
        cwd=project,
        env=env,
    )
    assert release_wrong_branch.returncode != 0
    assert "Release acceptance requires branch master" in release_wrong_branch.stdout
    assert memory.read_bytes() == before

    live_without_key_env = dict(env)
    live_without_key_env.pop("AION_API_KEY", None)
    live_without_key = run(
        "scripts/owner_acceptance_test.sh",
        "--local-revision",
        "--live",
        cwd=project,
        env=live_without_key_env,
    )
    assert live_without_key.returncode != 0
    assert "--live requires AION_API_KEY" in live_without_key.stdout
    assert memory.read_bytes() == before
    assert not list(temp_root.glob("aion-owner-acceptance.*"))


print("OWNER ACCEPTANCE LAUNCHER: PASS")
