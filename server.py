import json
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from core.truth import load_truth, get_execution_limits
from core.engine import load_state

PORT = 8080
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AION Dashboard</title>
    <style>
        body { font-family: monospace; background: #121212; color: #00ff66; padding: 15px; margin: 0; }
        h2 { color: #ffffff; border-bottom: 1px solid #00ff66; padding-bottom: 5px; }
        .card { background: #1e1e1e; border: 1px solid #333; padding: 12px; margin-bottom: 15px; border-radius: 6px; }
        pre { white-space: pre-wrap; word-wrap: break-word; color: #cccccc; font-size: 13px; }
        button { background: #00ff66; color: #000; border: none; padding: 10px 15px; font-weight: bold; cursor: pointer; border-radius: 4px; }
        button:hover { background: #00cc55; }
    </style>
</head>
<body>
    <h2>AION System Control Panel</h2>
    <div class="card">
        <h3>[TRUTH / EXECUTION LIMITS]</h3>
        <pre>{{LIMITS}}</pre>
    </div>
    <div class="card">
        <h3>[CURRENT STATE]</h3>
        <pre>{{STATE}}</pre>
    </div>
    <div class="card">
        <h3>[SYSTEM HEALTH]</h3>
        <pre>Status: ONLINE | Target: http://localhost:8080</pre>
    </div>
</body>
</html>
"""

class AionHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            
            limits = json.dumps(get_execution_limits(), indent=2, ensure_ascii=False)
            state = json.dumps(load_state(), indent=2, ensure_ascii=False)
            
            html = HTML_TEMPLATE.replace("{{LIMITS}}", limits).replace("{{STATE}}", state)
            self.wfile.write(html.encode("utf-8"))
        elif self.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            status_data = {"status": "ok", "limits": get_execution_limits()}
            self.wfile.write(json.dumps(status_data).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        return  # Отключение стандартных логов подключения

if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", PORT), AionHandler)
    print(f"[AION SERVER STARTED] http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[AION SERVER STOPPED]")
