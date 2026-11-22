import server


server.get_execution_limits = lambda: {"max_iterations": 3}
server.load_state = lambda: {"response": "</pre><script>alert('x')</script>"}
server.load_pipeline_state = lambda: {"result": "<img src=x onerror=alert(1)>"}

rendered = server.render_home()
assert "<script>alert('x')</script>" not in rendered
assert "<img src=x onerror=alert(1)>" not in rendered
assert "&lt;/pre&gt;&lt;script&gt;" in rendered
assert "&lt;img src=x onerror=alert(1)&gt;" in rendered
assert server.MAX_POST_BYTES > 0

marker = "SENSITIVE-SERVER-EXCEPTION"
safe_error = server._safe_runtime_error("server")
assert marker not in str(safe_error)
assert safe_error["stage"] == "server"

print("SERVER SAFETY TEST: PASS")
