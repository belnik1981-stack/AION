import html
import json
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

from core.truth import get_execution_limits
from core.engine import load_state, run_cycle
from core.pipeline import run_pipeline

PORT = 8080
MAX_POST_BYTES = 64_000
ROOT = Path(__file__).resolve().parent
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

    <div class="card">
        <h3>[CONTROL — single model / single cycle]</h3>
        <form action="/run" method="POST">
            <textarea name="user_prompt" placeholder="Контрольный запрос одной модели..."></textarea>
            <button type="submit">Запустить контрольный цикл</button>
        </form>
    </div>

    <div class="card">
        <h3>[AION PIPELINE — multi-model role rotation when AION_MODELS is set]</h3>
        <form action="/pipeline" method="POST">
            <textarea name="user_prompt" placeholder="Один запрос для сравнения нескольких моделей и ротации ролей..."></textarea>
            <button type="submit" class="pipeline-btn">Запустить сравнительный pipeline</button>
        </form>
    </div>

    <div class="card"><h3>[CURRENT STATE / LAST RESPONSE — single cycle]</h3><pre>{{STATE}}</pre></div>
    <div class="card"><h3>[LAST PIPELINE RESULT]</h3><pre>{{PIPELINE_STATE}}</pre></div>
    <div class="card"><h3>[EXECUTION LIMITS]</h3><pre>{{LIMITS}}</pre></div>
</body>
</html>
"""


def load_pipeline_state() -> dict:
    if not PIPELINE_STATE_FILE.exists():
        return {}
    try:
        return json.loads(PIPELINE_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_pipeline_state(result: dict) -> None:
    PIPELINE_STATE_FILE.write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def render_home() -> str:
    limits = json.dumps(get_execution_limits(), indent=2, ensure_ascii=False)
    state = json.dumps(load_state(), indent=2, ensure_ascii=False)
    pipeline_state = json.dumps(load_pipeline_state(), indent=2, ensure_ascii=False)
    return (
        HTML_TEMPLATE
        .replace("{{LIMITS}}", html.escape(limits))
        .replace("{{STATE}}", html.escape(state))
        .replace("{{PIPELINE_STATE}}", html.escape(pipeline_state))
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
        if self.path in ["/", "/index.html"]:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; form-action 'self'")
            self.end_headers()
            self.wfile.write(render_home().encode("utf-8"))
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
            except Exception as exc:
                print(f"[ERROR] Cycle execution failed: {exc}")
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()

        elif self.path == "/pipeline":
            parsed_data = self._read_form()
            if parsed_data is None:
                return
            user_prompt = parsed_data.get("user_prompt", [""])[0].strip()
            if user_prompt:
                try:
                    result = run_pipeline(user_prompt)
                except Exception as exc:
                    result = {"status": "error", "stage": "server", "detail": str(exc)}
                save_pipeline_state(result)
            else:
                save_pipeline_state({"status": "error", "detail": "Пустая задача"})
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", PORT), AionHandler)
    print(f"[AION INTERACTIVE SERVER STARTED] http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[AION SERVER STOPPED]")
