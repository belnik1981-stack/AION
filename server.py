"""Loopback-only AION trial control server."""
from __future__ import annotations

import html
import json
import os
import secrets
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from core.engine import load_state, run_cycle
from core.pipeline import run_pipeline
from core.truth import get_execution_limits
from providers.registry import provider_status

ROOT = Path(__file__).resolve().parent
RUNTIME_DIR = Path(
    os.getenv("AION_RUNTIME_DIR", str(ROOT / "runtime"))
).expanduser()
PIPELINE_STATE_FILE = Path(
    os.getenv("AION_PIPELINE_STATE_FILE", str(RUNTIME_DIR / "pipeline_state.json"))
).expanduser()
CSRF_TOKEN = secrets.token_urlsafe(32)

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AION Trial Control</title>
  <style>
    body { font-family: monospace; background: #121212; color: #00ff66; padding: 15px; margin: 0; }
    h2 { color: #fff; border-bottom: 1px solid #00ff66; padding-bottom: 5px; }
    .card { background: #1e1e1e; border: 1px solid #333; padding: 12px; margin-bottom: 15px; border-radius: 6px; }
    pre { white-space: pre-wrap; overflow-wrap: anywhere; color: #ccc; font-size: 13px; }
    textarea { width: 100%; height: 80px; background: #0d0d0d; color: #00ff66; border: 1px solid #00ff66; border-radius: 4px; padding: 8px; box-sizing: border-box; font-family: monospace; margin-bottom: 10px; }
    button { background: #00ff66; color: #000; border: 0; padding: 12px 20px; font-weight: bold; cursor: pointer; border-radius: 4px; width: 100%; }
    .pipeline { background: #ffaa00; }
  </style>
</head>
<body>
  <h2>AION Trial Control Panel</h2>
  <div class="card">
    <h3>Single bounded cycle</h3>
    <form action="/run" method="POST">
      <input type="hidden" name="csrf_token" value="{{CSRF_TOKEN}}">
      <textarea name="user_prompt" required maxlength="{{MAX_INPUT_CHARS}}" placeholder="Введите тестовую задачу"></textarea>
      <button type="submit">Запустить один цикл</button>
    </form>
  </div>
  <div class="card">
    <h3>Bounded Planner/Analyst/Critic/Synthesizer pipeline</h3>
    <form action="/pipeline" method="POST">
      <input type="hidden" name="csrf_token" value="{{CSRF_TOKEN}}">
      <textarea name="user_prompt" required maxlength="{{MAX_INPUT_CHARS}}" placeholder="Введите тестовую задачу"></textarea>
      <button type="submit" class="pipeline">Запустить pipeline</button>
    </form>
  </div>
  <div class="card"><h3>Single-cycle state</h3><pre>{{STATE}}</pre></div>
  <div class="card"><h3>Pipeline state</h3><pre>{{PIPELINE_STATE}}</pre></div>
  <div class="card"><h3>Enforced limits</h3><pre>{{LIMITS}}</pre></div>
</body>
</html>
"""


class RequestRejected(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _write_private_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    try:
        temporary.chmod(0o600)
    except OSError:
        pass
    os.replace(temporary, path)


def load_pipeline_state() -> dict:
    if not PIPELINE_STATE_FILE.exists():
        return {}
    try:
        data = json.loads(PIPELINE_STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_pipeline_state(result: dict) -> None:
    _write_private_json(PIPELINE_STATE_FILE, result)


def render_page(state: dict | None = None, pipeline_state: dict | None = None) -> str:
    limits = get_execution_limits()
    state_json = json.dumps(
        load_state() if state is None else state,
        indent=2,
        ensure_ascii=False,
    )
    pipeline_json = json.dumps(
        load_pipeline_state() if pipeline_state is None else pipeline_state,
        indent=2,
        ensure_ascii=False,
    )
    limits_json = json.dumps(limits, indent=2, ensure_ascii=False)
    return (
        HTML_TEMPLATE
        .replace("{{CSRF_TOKEN}}", html.escape(CSRF_TOKEN, quote=True))
        .replace("{{MAX_INPUT_CHARS}}", str(limits["max_input_chars"]))
        .replace("{{STATE}}", html.escape(state_json))
        .replace("{{PIPELINE_STATE}}", html.escape(pipeline_json))
        .replace("{{LIMITS}}", html.escape(limits_json))
    )


def _parse_port() -> int:
    try:
        port = int(os.getenv("AION_PORT", "8080"))
    except ValueError as exc:
        raise SystemExit("AION_PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise SystemExit("AION_PORT must be between 1 and 65535")
    return port


class AionHandler(BaseHTTPRequestHandler):
    server_version = "AIONTrial/0.3"

    def _security_headers(self, content_type: str) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; "
            "form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
        )

    def _send_bytes(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self._security_headers(content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _host_is_loopback(self) -> bool:
        host = self.headers.get("Host", "").split(":", 1)[0].strip("[]").lower()
        return host in {"127.0.0.1", "localhost"}

    def _read_form(self) -> dict[str, list[str]]:
        limits = get_execution_limits()
        raw_length = self.headers.get("Content-Length")
        try:
            content_length = int(raw_length or "0")
        except ValueError as exc:
            raise RequestRejected(400, "Invalid Content-Length") from exc
        if content_length <= 0:
            raise RequestRejected(400, "Request body is empty")
        if content_length > limits["max_request_bytes"]:
            raise RequestRejected(413, "Request body exceeds the configured limit")
        content_type = self.headers.get("Content-Type", "")
        if not content_type.startswith("application/x-www-form-urlencoded"):
            raise RequestRejected(415, "Unsupported Content-Type")
        raw = self.rfile.read(content_length)
        try:
            decoded = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RequestRejected(400, "Request body is not valid UTF-8") from exc
        parsed = urllib.parse.parse_qs(
            decoded,
            keep_blank_values=True,
            max_num_fields=4,
        )
        supplied_token = parsed.get("csrf_token", [""])[0]
        if not secrets.compare_digest(supplied_token, CSRF_TOKEN):
            raise RequestRejected(403, "Invalid request token")
        return parsed

    def _redirect_home(self) -> None:
        self.send_response(303)
        self._security_headers("text/plain; charset=utf-8")
        self.send_header("Location", "/")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        if not self._host_is_loopback():
            self._send_bytes(421, b"Loopback Host header required\n", "text/plain; charset=utf-8")
            return
        if self.path == "/healthz":
            body = json.dumps(
                {
                    "status": "ok",
                    "provider": provider_status(),
                    "limits": get_execution_limits(),
                },
                ensure_ascii=False,
            ).encode("utf-8")
            self._send_bytes(200, body, "application/json; charset=utf-8")
            return
        if self.path in {"/", "/index.html"}:
            self._send_bytes(
                200,
                render_page().encode("utf-8"),
                "text/html; charset=utf-8",
            )
            return
        self._send_bytes(404, b"Not found\n", "text/plain; charset=utf-8")

    def do_POST(self) -> None:
        if not self._host_is_loopback():
            self._send_bytes(421, b"Loopback Host header required\n", "text/plain; charset=utf-8")
            return
        if self.path not in {"/run", "/pipeline"}:
            self._send_bytes(404, b"Not found\n", "text/plain; charset=utf-8")
            return
        try:
            parsed = self._read_form()
            user_prompt = parsed.get("user_prompt", [""])[0].strip()
            if not user_prompt:
                raise RequestRejected(400, "Task is empty")

            if self.path == "/run":
                try:
                    run_cycle(user_prompt)
                except Exception:
                    save_pipeline_state(
                        {
                            "status": "error",
                            "stage": "single_cycle",
                            "detail": "Execution failed; inspect the private audit log.",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    )
            else:
                try:
                    result = run_pipeline(user_prompt)
                except Exception:
                    result = {
                        "status": "error",
                        "stage": "pipeline",
                        "detail": "Execution failed; inspect the private audit log.",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                save_pipeline_state(result)
            self._redirect_home()
        except RequestRejected as exc:
            self._send_bytes(
                exc.status,
                (exc.message + "\n").encode("utf-8"),
                "text/plain; charset=utf-8",
            )

    def log_message(self, format: str, *args) -> None:
        return


def main() -> None:
    bind = os.getenv("AION_BIND", "127.0.0.1").strip().lower()
    if bind not in {"127.0.0.1", "localhost"}:
        raise SystemExit(
            "External bind is disabled for the trial. Use an SSH port forward."
        )
    port = _parse_port()
    server = HTTPServer((bind, port), AionHandler)
    print(f"[AION TRIAL SERVER] http://{bind}:{port}")
    print("[AION] External bind disabled; stop with Ctrl+C.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[AION SERVER STOPPED]")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
