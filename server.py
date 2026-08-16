import json
import os
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

from core.truth import load_truth, get_execution_limits
from core.engine import load_state, run_cycle

PORT = 8080
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
    </style>
</head>
<body>
    <h2>AION Control Panel</h2>
    
    <div class="card">
        <h3>[EXECUTE TASK]</h3>
        <form action="/run" method="POST">
            <textarea name="user_prompt" placeholder="Введите задачу или инструкцию для AION..."></textarea>
            <button type="submit">Запустить цикл AION</button>
        </form>
    </div>

    <div class="card">
        <h3>[CURRENT STATE / LAST RESPONSE]</h3>
        <pre>{{STATE}}</pre>
    </div>

    <div class="card">
        <h3>[EXECUTION LIMITS]</h3>
        <pre>{{LIMITS}}</pre>
    </div>
</body>
</html>
"""

class AionHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ["/", "/index.html"]:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            
            limits = json.dumps(get_execution_limits(), indent=2, ensure_ascii=False)
            state = json.dumps(load_state(), indent=2, ensure_ascii=False)
            
            html = HTML_TEMPLATE.replace("{{LIMITS}}", limits).replace("{{STATE}}", state)
            self.wfile.write(html.encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/run":
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            parsed_data = urllib.parse.parse_qs(post_data)
            
            user_prompt = parsed_data.get("user_prompt", [""])[0]
            
            # Выполнение цикла ядра AION
            try:
                run_cycle(user_prompt if user_prompt.strip() else None)
            except Exception as e:
                print(f"[ERROR] Cycle execution failed: {e}")

            # Редирект обратно на главную страницу для обновления состояния
            self.send_response(303)
            self.send_header('Location', '/')
            self.end_headers()

if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", PORT), AionHandler)
    print(f"[AION INTERACTIVE SERVER STARTED] http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[AION SERVER STOPPED]")
