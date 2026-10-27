"""Real loopback HTTP smoke with all provider calls replaced offline."""

from http.client import HTTPConnection
from http.server import HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.parse import urlencode
from unittest.mock import patch

import server
from providers.base import ProviderHTTPError, ProviderRateLimitError


class QuietAionHandler(server.AionHandler):
    def log_message(self, _format, *_args):
        return


def request(port: int, method: str, path: str, body=None, headers=None):
    connection = HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        payload = response.read()
        return response.status, dict(response.getheaders()), payload
    finally:
        connection.close()


with TemporaryDirectory() as temp_dir:
    pipeline_state = Path(temp_dir) / "pipeline-state.json"
    pipeline_calls: list[str] = []
    cycle_calls: list[str | None] = []
    fake_key = "sk-proj-" + "S" * 32

    def fake_pipeline(prompt: str) -> dict:
        pipeline_calls.append(prompt)
        return {
            "status": "ok",
            "final_answer": "</pre><script>alert('x')</script> " + fake_key,
            "truth_verified": False,
        }

    def fake_cycle(prompt=None):
        cycle_calls.append(prompt)
        return {"status": "idle"}

    saved_prompt = "single <question>"
    saved_answer = "four <answer>"
    with patch.object(server, "PIPELINE_STATE_FILE", pipeline_state), patch.object(
        server, "load_state", return_value={"status": "idle", "last_user_prompt": saved_prompt,
                                           "last_answer": saved_answer}
    ), patch.object(
        server, "session_snapshot", return_value={"status": "ok", "tasks": [{
            "id": "task-123", "kind": "cycle", "status": "completed", "prompt": saved_prompt,
            "result": {"last_answer": saved_answer}}]}
    ), patch.object(
        server, "get_execution_limits", return_value={"max_iterations": 2}
    ), patch.object(
        server, "run_pipeline", side_effect=fake_pipeline
    ), patch.object(
        server, "run_cycle", side_effect=fake_cycle
    ) as cycle_mock:
        httpd = HTTPServer(("127.0.0.1", 0), QuietAionHandler)
        assert httpd.server_address[0] == "127.0.0.1"
        port = httpd.server_address[1]
        thread = Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01})
        thread.start()
        try:
            status, headers, body = request(port, "GET", "/")
            assert status == 200
            assert headers["X-Content-Type-Options"] == "nosniff"
            assert headers["X-AION-Instance"] == server.INSTANCE_ID
            assert "default-src 'self'" in headers["Content-Security-Policy"]
            assert b"AION Control Panel" in body
            assert "Задать вопрос".encode("utf-8") in body
            assert b"single &lt;question&gt;" in body
            assert b"four &lt;answer&gt;" in body
            assert b"task-123" in body

            status, _, _ = request(port, "GET", "/missing")
            assert status == 404

            form = urlencode({"user_prompt": "compare safely"})
            status, headers, _ = request(
                port,
                "POST",
                "/pipeline",
                body=form,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Content-Length": str(len(form.encode("utf-8"))),
                },
            )
            assert status == 303
            assert headers["Location"] == "/"
            assert pipeline_calls == ["compare safely"]
            stored = pipeline_state.read_text(encoding="utf-8")
            assert fake_key not in stored
            assert "[REDACTED_SECRET]" in stored
            assert pipeline_state.stat().st_mode & 0o077 == 0

            status, _, body = request(port, "GET", "/")
            assert status == 200
            assert b"<script>alert('x')</script>" not in body
            assert b"&lt;/pre&gt;&lt;script&gt;" in body

            run_form = urlencode({"user_prompt": "single control"})
            status, headers, _ = request(
                port,
                "POST",
                "/run",
                body=run_form,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Content-Length": str(len(run_form.encode("utf-8"))),
                },
            )
            assert status == 303 and headers["Location"] == "/?cycle_ok=1"
            assert cycle_calls == ["single control"]

            cycle_mock.side_effect = RuntimeError("provider failed")
            status, headers, _ = request(
                port, "POST", "/run", body=run_form,
                headers={"Content-Type": "application/x-www-form-urlencoded",
                         "Content-Length": str(len(run_form.encode("utf-8")))},
            )
            assert status == 303 and headers["Location"] == "/?cycle_error=1"
            status, _, body = request(port, "GET", "/?cycle_error=1")
            assert status == 200
            assert "Запрос завершился ошибкой".encode("utf-8") in body

            for exception, error_path, message in (
                (ProviderHTTPError(401, "safe"), "/?cycle_error=401", "HTTP 401"),
                (ProviderRateLimitError("safe"), "/?cycle_error=429", "HTTP 429"),
            ):
                cycle_mock.side_effect = exception
                status, headers, _ = request(
                    port, "POST", "/run", body=run_form,
                    headers={"Content-Type": "application/x-www-form-urlencoded",
                             "Content-Length": str(len(run_form.encode("utf-8")))},
                )
                assert status == 303 and headers["Location"] == error_path
                status, _, body = request(port, "GET", error_path)
                assert status == 200 and message.encode("utf-8") in body

            connection = HTTPConnection("127.0.0.1", port, timeout=3)
            try:
                connection.putrequest("POST", "/pipeline")
                connection.putheader("Content-Length", str(server.MAX_POST_BYTES + 1))
                connection.endheaders()
                response = connection.getresponse()
                response.read()
                assert response.status == 413
            finally:
                connection.close()
            assert pipeline_calls == ["compare safely"]
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=3)
            assert not thread.is_alive()


print("SERVER LOOPBACK HTTP SMOKE: PASS")
