"""End-to-end cloud smoke test using the no-network mock provider."""
from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRUTH_FILES = [
    ROOT / "knowledge" / "truth" / "truth.json",
    ROOT / "knowledge" / "truth" / "system.yaml",
]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


truth_before = {path: digest(path) for path in TRUTH_FILES}

with tempfile.TemporaryDirectory(prefix="aion-cloud-smoke-") as runtime:
    port = free_port()
    env = os.environ.copy()
    env.update(
        {
            "AION_PROVIDER": "mock",
            "AION_BIND": "127.0.0.1",
            "AION_PORT": str(port),
            "AION_RUNTIME_DIR": runtime,
            "PYTHONPATH": str(ROOT),
        }
    )
    process = subprocess.Popen(
        [sys.executable, "server.py"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        base_url = f"http://127.0.0.1:{port}"
        for _ in range(50):
            try:
                with urllib.request.urlopen(base_url + "/healthz", timeout=1) as response:
                    health = json.loads(response.read().decode("utf-8"))
                if health.get("status") == "ok":
                    break
            except Exception:
                time.sleep(0.1)
        else:
            raise AssertionError("Trial server did not become healthy")

        with urllib.request.urlopen(base_url + "/", timeout=2) as response:
            page = response.read().decode("utf-8")
        token_match = re.search(
            r'name="csrf_token" value="([^"]+)"',
            page,
        )
        assert token_match, "CSRF token was not rendered"

        task = "Проверка </pre><script>cloud</script>"
        body = urllib.parse.urlencode(
            {
                "csrf_token": token_match.group(1),
                "user_prompt": task,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            base_url + "/run",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            rendered = response.read().decode("utf-8")

        state_file = Path(runtime) / "state.json"
        audit_file = Path(runtime) / "audit.jsonl"
        state = json.loads(state_file.read_text(encoding="utf-8"))
        assert state["last_answer"].startswith("MOCK_RESPONSE:")
        assert state["execution"]["api_calls"] == 1
        assert audit_file.exists()
        assert "<script>cloud</script>" not in rendered
        assert "&lt;script&gt;cloud&lt;/script&gt;" in rendered
        assert {path: digest(path) for path in TRUTH_FILES} == truth_before
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)

print("CLOUD LOOPBACK SMOKE TEST: PASS")
