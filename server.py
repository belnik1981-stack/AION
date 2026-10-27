import html
import hashlib
import json
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

from core.truth import get_execution_limits
from core.engine import load_state, run_cycle
from core.pipeline import run_pipeline
from storage.atomic_json import atomic_write_json, load_json
from storage.atomic_json import JsonStorageError
from security.redaction import TextSafetyError, redact_structure
from memory.session import (
    SessionStorageError, recover_interrupted, snapshot as session_snapshot,
)
from providers.base import ProviderHTTPError, ProviderRateLimitError, ProviderTruncatedError

PORT = 8080
MAX_POST_BYTES = 64_000
ROOT = Path(__file__).resolve().parent
INSTANCE_ID = hashlib.sha256(str(ROOT.resolve()).encode("utf-8")).hexdigest()[:16]
PIPELINE_STATE_FILE = ROOT / "pipeline_state.json"

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AION Interactive Control</title>
    <style>
        body { font-family: monospace; background: #121212; color: #00ff66; padding: 15px; margin: 0; }
        h2 { color: #ffffff; border-bottom: 1px solid #00ff66; padding-bottom: 5px; }
        .card { background: #1e1e1e; border: 1px solid #333; padding: 12px; margin-bottom: 15px; border-radius: 6px; }
        pre { white-space: pre-wrap; word-wrap: break-word; color: #cccccc; font-size: 13px; }
        textarea { width: 100%; height: 80px; background: #0d0d0d; color: #00ff66; border: 1px solid #00ff66; border-radius: 4px; padding: 8px; box-sizing: border-box; font-family: monospace; margin-bottom: 10px; }
        button { background: #00ff66; color: #000; border: none; padding: 12px 20px; font-weight: bold; cursor: pointer; border-radius: 4px; width: 100%; font-size: 14px; }
        button:hover { background: #00cc55; }
        .pipeline-btn { background: #ffaa00; }
        .pipeline-btn:hover { background: #cc8800; }
    </style>
</head>
<body>
    <h2>AION Control Panel</h2>
    {{RUN_STATUS}}

    <div class="card">
        <h3>[CONTROL — single model / single cycle]</h3>
        <form action="/run" method="POST">
            <textarea name="user_prompt" placeholder="Напишите вопрос для AION..."></textarea>
            <button type="submit">Задать вопрос</button>
        </form>
    </div>
    {{LAST_ANSWER}}

    <div class="card">
        <h3>[AION PIPELINE — multi-model role rotation when AION_MODELS is set]</h3>
        <form action="/pipeline" method="POST">
            <textarea name="user_prompt" placeholder="Один запрос для сравнения нескольких моделей и ротации ролей..."></textarea>
            <button type="submit" class="pipeline-btn">Запустить сравнительный pipeline</button>
        </form>
    </div>

    <div class="card"><h3>[CURRENT STATE / LAST RESPONSE — single cycle]</h3><pre>{{STATE}}</pre></div>
    <div class="card"><h3>[LAST PIPELINE RESULT]</h3><pre>{{PIPELINE_STATE}}</pre></div>
    <div class="card"><h3>[OPERATIONAL MEMORY]</h3><pre>{{SESSION_STATE}}</pre></div>
    <div class="card"><h3>[EXECUTION LIMITS]</h3><pre>{{LIMITS}}</pre></div>
</body>
</html>
"""


def load_pipeline_state() -> dict:
    return load_json(PIPELINE_STATE_FILE, default_factory=dict, expected_type=dict)


def save_pipeline_state(result: dict) -> None:
    safe_result, _ = redact_structure(result)
    atomic_write_json(PIPELINE_STATE_FILE, safe_result, expected_type=dict)


def _safe_runtime_error(stage: str) -> dict:
    return {
        "status": "error",
        "stage": stage,
        "detail": "Операция безопасно остановлена; недоверенные детали скрыты.",
    }


def _safe_display(loader, stage: str) -> dict:
    try:
        value = loader()
        safe, _ = redact_structure(value)
        return safe
    except (JsonStorageError, SessionStorageError, TextSafetyError, TypeError):
        return _safe_runtime_error(stage)


def render_home(run_status: str = "") -> str:
    limits = json.dumps(get_execution_limits(), indent=2, ensure_ascii=False)
    state_data = _safe_display(load_state, "state_load")
    state = json.dumps(state_data, indent=2, ensure_ascii=False)
    pipeline_state = json.dumps(
        _safe_display(load_pipeline_state, "pipeline_state_load"),
        indent=2,
        ensure_ascii=False,
    )
    session_data = _safe_display(lambda: session_snapshot(limit=5), "session_load")
    session_state = json.dumps(session_data, indent=2, ensure_ascii=False)
    last_answer = ""
    if isinstance(state_data, dict) and state_data.get("last_answer"):
        prompt = str(state_data.get("last_user_prompt", ""))
        answer = str(state_data["last_answer"])
        task_id = ""
        if isinstance(session_data, dict):
            for task in session_data.get("tasks", []):
                if (task.get("kind") == "cycle" and task.get("status") == "completed"
                        and task.get("prompt") == prompt
                        and isinstance(task.get("result"), dict)
                        and task["result"].get("last_answer") == answer):
                    task_id = str(task["id"])
                    break
        last_answer = (
            '<div class="card"><h3>Последний сохранённый ответ</h3>'
            '<p>После перезапуска сравните вопрос, ответ и ID записи.</p>'
            '<p>Вопрос:</p><pre>' + html.escape(prompt) + '</pre>'
            '<p>Ответ:</p><pre>' + html.escape(answer) + '</pre>'
            '<p>ID записи памяти: ' + html.escape(task_id or "нет подтверждённой записи")
            + '</p></div>'
        )
    notice = (
        '<div class="card" role="status">' + html.escape(run_status) + '</div>'
        if run_status else ""
    )
    return (
        HTML_TEMPLATE
        .replace("{{RUN_STATUS}}", notice)
        .replace("{{LAST_ANSWER}}", last_answer)
        .replace("{{LIMITS}}", html.escape(limits))
        .replace("{{STATE}}", html.escape(state))
        .replace("{{PIPELINE_STATE}}", html.escape(pipeline_state))
        .replace("{{SESSION_STATE}}", html.escape(session_state))
    )


class AionHandler(BaseHTTPRequestHandler):
    def _read_form(self) -> dict[str, list[str]] | None:
        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            content_length = 0
        if content_length < 0 or content_length > MAX_POST_BYTES:
            self.send_response(413)
            self.end_headers()
            return None
        post_data = self.rfile.read(content_length).decode("utf-8", errors="replace")
        return urllib.parse.parse_qs(post_data)

    def do_GET(self):
        if self.path in ["/", "/index.html", "/?cycle_ok=1", "/?cycle_error=1",
                         "/?cycle_error=401", "/?cycle_error=429",
                         "/?cycle_error=truncated"]:
            notice = ""
            if self.path == "/?cycle_ok=1":
                notice = "Запрос завершён. Проверьте ответ и новую запись памяти ниже."
            elif self.path == "/?cycle_error=1":
                notice = "Запрос завершился ошибкой. Ответ ниже относится к предыдущему успешному запросу."
            elif self.path == "/?cycle_error=401":
                notice = "HTTP 401: ключ отклонён. Ответ ниже относится к предыдущему запросу."
            elif self.path == "/?cycle_error=429":
                notice = "HTTP 429: лимит запросов. Не повторяйте вопрос сразу. Ответ ниже — предыдущий."
            elif self.path == "/?cycle_error=truncated":
                notice = "Ответ модели усечён и не сохранён как успешный."
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("X-AION-Instance", INSTANCE_ID)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; form-action 'self'")
            self.end_headers()
            self.wfile.write(render_home(notice).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/run":
            parsed_data = self._read_form()
            if parsed_data is None:
                return
            user_prompt = parsed_data.get("user_prompt", [""])[0]
            try:
                run_cycle(user_prompt if user_prompt.strip() else None)
                location = "/?cycle_ok=1"
            except ProviderRateLimitError:
                location = "/?cycle_error=429"
            except ProviderHTTPError as exc:
                location = "/?cycle_error=401" if exc.status_code == 401 else "/?cycle_error=1"
            except ProviderTruncatedError:
                location = "/?cycle_error=truncated"
            except Exception:
                print("[ERROR] Cycle execution failed; details hidden")
                location = "/?cycle_error=1"
            self.send_response(303)
            self.send_header("Location", location)
            self.end_headers()

        elif self.path == "/pipeline":
            parsed_data = self._read_form()
            if parsed_data is None:
                return
            user_prompt = parsed_data.get("user_prompt", [""])[0].strip()
            if user_prompt:
                try:
                    result = run_pipeline(user_prompt)
                except Exception:
                    result = _safe_runtime_error("server")
                try:
                    save_pipeline_state(result)
                except (JsonStorageError, TextSafetyError, TypeError):
                    print("[ERROR] Pipeline state was not persisted; details hidden")
            else:
                try:
                    save_pipeline_state({"status": "error", "detail": "Пустая задача"})
                except (JsonStorageError, TextSafetyError, TypeError):
                    print("[ERROR] Empty-task state was not persisted; details hidden")
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    recover_interrupted()
    server = HTTPServer(("127.0.0.1", PORT), AionHandler)
    print(f"[AION INTERACTIVE SERVER STARTED] http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[AION SERVER STOPPED]")
