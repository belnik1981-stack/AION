"""Real Git/HTTP/widget integration with local PR refs; no external provider calls."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
import shlex
import signal
import time
from urllib.error import HTTPError

from tools import termux_widget as widget


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools/termux_widget.py"


def invoke(*args, cwd=None, env=None, check=True):
    result = subprocess.run([str(a) for a in args], cwd=cwd, env=env, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
    if check and result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return result


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class WidgetIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="aion-widget-test-")
        cls.base = Path(cls.temporary.name)
        cls.remote = cls.base / "remote.git"
        cls.seed = cls.base / "seed"
        invoke("git", "init", "--bare", "--quiet", cls.remote)
        # GitHub Actions uses a shallow checkout. Build an independent fixture
        # history instead of trying to push its missing ancestors to a bare repo.
        invoke("git", "init", "--quiet", "-b", "master", cls.seed)
        for relative in widget.git(ROOT, "ls-files", "-z").split("\0"):
            if not relative:
                continue
            target = cls.seed / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, target)
        invoke("git", "-C", cls.seed, "remote", "add", "origin", cls.remote)
        invoke("git", "-C", cls.seed, "config", "user.name", "Widget fixture")
        invoke("git", "-C", cls.seed, "config", "user.email", "fixture@localhost")
        invoke("git", "-C", cls.seed, "add", "--all")
        invoke("git", "-C", cls.seed, "commit", "--quiet", "-m", "Independent master fixture")
        invoke("git", "-C", cls.seed, "push", "--quiet", "origin", "master")
        cls.master_sha = widget.git(cls.seed, "rev-parse", "HEAD")
        invoke("git", "-C", cls.seed, "switch", "-c", "fixture-pr")
        (cls.seed / "widget-pr-fixture.txt").write_text("Local PR content, not in master.\n")
        invoke("git", "-C", cls.seed, "add", "widget-pr-fixture.txt")
        invoke("git", "-C", cls.seed, "commit", "--quiet", "-m", "Local PR fixture")
        invoke("git", "-C", cls.seed, "push", "--quiet", "origin", "HEAD:refs/pull/17/head")
        invoke("git", "-C", cls.seed, "push", "--quiet", "origin", "HEAD:refs/heads/feat/termux-widget-dual-launch")
        cls.pr_sha = widget.git(cls.seed, "rev-parse", "HEAD")

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.case = Path(tempfile.mkdtemp(dir=self.base, prefix="case-"))
        self.home = self.case / "Termux home with spaces"
        self.home.mkdir()
        self.port = free_port()
        self.env = {key: value for key, value in os.environ.items() if not key.startswith("AION_")}
        self.env["PYTHONDONTWRITEBYTECODE"] = "1"
        self.env["AION_API_KEY"] = "synthetic-widget-test-key"

    def cli(self, *args, check=True):
        return invoke(sys.executable, "-B", TOOL, "--home-dir", self.home, *args,
                      env=self.env, check=check)

    def install(self, *args, check=True):
        return self.cli("install", "--pr", "17", "--repository", str(self.remote),
                        "--port", str(self.port), "--runtime-python", sys.executable,
                        "--offline", *args, check=check)

    def tearDown(self):
        config = widget.layout(self.home)[2]
        if config.exists() and widget.current_status(self.port):
            self.cli("stop", check=False)

    def test_dirty_master_preserved_and_merge_preview_isolated(self):
        master = self.home / "AION"
        invoke("git", "clone", "--quiet", "--branch", "master", self.remote, master)
        original = (master / "README.md").read_text() + "\nlocal owner change\n"
        (master / "README.md").write_text(original)
        (master / ".env").write_text("OWNER_SETTING=preserve\n")
        original_head = widget.git(master, "rev-parse", "HEAD")
        original_status = widget.git(master, "status", "--porcelain")
        original_files = {str(p.relative_to(master)): p.read_bytes()
                          for p in master.rglob("*") if p.is_file() and ".git" not in p.parts}
        self.install()
        self.assertEqual((master / "README.md").read_text(), original)
        self.assertEqual(widget.git(master, "rev-parse", "HEAD"), original_head)
        self.assertEqual(widget.git(master, "status", "--porcelain"), original_status)
        self.assertEqual(original_files, {str(p.relative_to(master)): p.read_bytes()
                          for p in master.rglob("*") if p.is_file() and ".git" not in p.parts})
        preview = self.home / "AION-PR-test"
        self.assertFalse((preview / ".env").exists())
        self.assertEqual(widget.git(preview, "rev-parse", "HEAD"), self.master_sha)
        self.assertEqual(widget.git(preview, "rev-parse", "MERGE_HEAD"), self.pr_sha)
        self.assertTrue((preview / "widget-pr-fixture.txt").exists())
        self.assertFalse((master / "widget-pr-fixture.txt").exists())
        self.assertEqual(widget.git(master, "branch", "--show-current"), "master")
        self.assertNotEqual((master / ".git").stat().st_ino, (preview / ".git").stat().st_ino)

    def test_shortcuts_browser_switch_back_and_secret_permissions(self):
        shortcuts = self.home / ".shortcuts"
        shortcuts.mkdir()
        unrelated = shortcuts / "Other task"
        unrelated.write_text("#!/bin/sh\necho other\n")
        (shortcuts / "AION").write_text('#!/bin/sh\ncd "$HOME/AION"\npython server.py\n')
        self.install()
        self.assertEqual(unrelated.read_text(), "#!/bin/sh\necho other\n")
        self.assertFalse((shortcuts / "AION").exists())
        _, data, config_file = widget.layout(self.home)
        self.assertTrue(list((data / "shortcut-backups").rglob("AION")))
        self.assertEqual(config_file.stat().st_mode & 0o777, 0o600)
        browser_bin = self.case / "bin"
        browser_bin.mkdir()
        browser_calls = self.case / "browser-calls"
        opener = browser_bin / "termux-open-url"
        opener.write_text("#!/bin/sh\nprintf '%s\\n' \"$1\" >> " +
                          shlex.quote(str(browser_calls)) + "\n")
        opener.chmod(0o700)
        self.env["PATH"] = str(browser_bin) + os.pathsep + self.env["PATH"]
        for variant, label in (("master", "MASTER"), ("test", "TEST PR"), ("master", "MASTER")):
            shortcut = shortcuts / ("AION " + label)
            self.assertEqual(shortcut.stat().st_mode & 0o777, 0o700)
            self.assertNotIn(self.env["AION_API_KEY"], shortcut.read_text())
            result = invoke("bash", shortcut, env=self.env)
            self.assertNotIn(self.env["AION_API_KEY"], result.stdout + result.stderr)
            status = widget.current_status(self.port)
            self.assertEqual(status["variant"], label)
            self.assertEqual(status["repo"], str(self.home / ("AION" if variant == "master" else "AION-PR-test")))
            code, page, headers = widget.local_request(self.port, "/")
            self.assertEqual(code, 200)
            self.assertIn(("AION " + label).encode(), page)
            self.assertEqual(headers["Cache-Control"], "no-store")
            with self.assertRaises(HTTPError) as rejected:
                widget.local_request(self.port, "/__aion_widget/stop", "incorrect-token")
            self.assertEqual(rejected.exception.code, 403)
        self.assertEqual(browser_calls.read_text().splitlines(), [f"http://127.0.0.1:{self.port}"] * 3)
        (self.home / "AION/state.json").write_text('{"owner_marker":"master only"}')
        self.assertFalse((self.home / "AION-PR-test/state.json").exists())

    def test_install_does_not_stop_running_server_and_is_repeatable(self):
        self.install()
        self.cli("start", "master", "--no-browser")
        before = widget.current_status(self.port)
        self.install()
        after = widget.current_status(self.port)
        self.assertEqual(before, after)
        self.assertEqual(self.cli("status").returncode, 0)

    def test_auto_pr_resolves_head_against_pull_ref(self):
        self.install("--pr", "auto")
        config = widget.read_json(widget.layout(self.home)[2])
        self.assertEqual(config["pr"], 17)

    def test_verified_pair_populates_only_unset_settings(self):
        self.install()
        config_file = widget.layout(self.home)[2]
        report = self.case / "live.log"
        report.write_text("[PASS] TWO DISTINCT MODEL IDS: author-a/model:free, author-b/model:free\n")
        widget.save_verified_pair(config_file, report)
        config = widget.read_json(config_file)
        self.assertEqual(config["settings"]["AION_MODELS"], "author-a/model:free,author-b/model:free")
        report.write_text("[PASS] TWO DISTINCT MODEL IDS: other/model:free, fourth/model:free\n")
        widget.save_verified_pair(config_file, report)
        self.assertEqual(widget.read_json(config_file), config)
        self.assertEqual(config_file.stat().st_mode & 0o777, 0o600)

    def test_explicit_env_file_is_data_not_shell_code(self):
        executed = self.case / "must-not-exist"
        config_file = self.case / "owner.env"
        config_file.write_text('export AION_MODEL="openrouter/free"\n'
                              + 'AION_OWNER_NOTE="$(touch ' + str(executed) + ')"\n')
        result = self.install("--config-file", str(config_file))
        self.assertEqual(result.returncode, 0)
        self.assertFalse(executed.exists())
        saved = widget.read_json(widget.layout(self.home)[2])
        self.assertEqual(saved["settings"]["AION_MODEL"], "openrouter/free")
        self.assertIn("$(touch", saved["settings"]["AION_OWNER_NOTE"])

    def test_unrelated_listener_is_not_stopped(self):
        self.install()
        with socket.socket() as unrelated:
            unrelated.bind(("127.0.0.1", self.port))
            unrelated.listen()
            result = self.cli("start", "test", "--no-browser", check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unverified process", result.stderr)
            self.assertEqual(unrelated.getsockname()[1], self.port)
            self.assertTrue(widget.listening(self.port))

    def test_user_shortcut_collision_is_preserved(self):
        shortcuts = self.home / ".shortcuts"
        shortcuts.mkdir()
        original = shortcuts / "AION MASTER"
        original.write_text("owner shortcut\n")
        result = self.install(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(original.read_text(), "owner shortcut\n")

    def test_aion_named_maintenance_shortcut_is_preserved(self):
        shortcuts = self.home / ".shortcuts"
        shortcuts.mkdir()
        original = shortcuts / "AION"
        original.write_text('#!/bin/sh\necho "AION server.py maintenance notes"\n')
        self.install()
        self.assertTrue(original.exists())

    def test_legacy_shortcut_with_new_caption_is_archived_before_replacement(self):
        shortcuts = self.home / ".shortcuts"
        shortcuts.mkdir()
        original = shortcuts / "AION MASTER"
        old_script = '#!/bin/sh\ncd "$HOME/AION"\nbash start_app.sh\n'
        original.write_text(old_script)
        self.install()
        self.assertIn(widget.SHORTCUT_MARKER, original.read_text())
        backups = list((widget.layout(self.home)[1] / "shortcut-backups").rglob("AION MASTER"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), old_script)

    def test_changed_test_copy_is_preserved(self):
        self.install()
        preview = self.home / "AION-PR-test"
        (preview / "README.md").write_text("owner test changes\n")
        result = self.install(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((preview / "README.md").read_text(), "owner test changes\n")

    def test_paid_configuration_rejected_before_stopping_master(self):
        self.install()
        self.cli("start", "master", "--no-browser")
        original = widget.current_status(self.port)
        config_file = widget.layout(self.home)[2]
        config = widget.read_json(config_file)
        config["settings"]["AION_MODEL"] = "author/paid-model"
        widget.write_json(config_file, config)
        result = self.cli("start", "test", "--no-browser", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(widget.current_status(self.port), original)

    def test_legacy_identity_and_safe_stop(self):
        self.install()
        config_file = widget.layout(self.home)[2]
        config = widget.read_json(config_file)
        legacy = self.case / "legacy"
        legacy.mkdir()
        (legacy / "server.py").write_text(
            "from http.server import HTTPServer, BaseHTTPRequestHandler\n"
            f"HTTPServer(('127.0.0.1', {self.port}), BaseHTTPRequestHandler).serve_forever()\n")
        config["variants"]["master"]["repo"] = str(legacy)
        process = subprocess.Popen([sys.executable, "-u", "server.py"], cwd=legacy,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 5
            while not widget.listening(self.port) and time.monotonic() < deadline:
                time.sleep(0.05)
            if not (hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal")):
                self.skipTest("pidfd unavailable: Android must use the safe manual Ctrl+C fallback")
            self.assertTrue(widget.legacy_identity(process.pid, [legacy], self.port))
            widget.stop_previous(self.home, config)
            process.wait(timeout=5)
            self.assertFalse(widget.listening(self.port))
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
