import os

from runtimes.openai_agents import runtime_status


status = runtime_status()

assert status["runtime"] == "openai_agents_sdk"
assert isinstance(status["sdk_installed"], bool)
assert isinstance(status["api_key_present"], bool)
assert isinstance(status["max_turns"], int)
assert status["max_turns"] > 0
assert "api_key" not in status
assert os.getenv("AION_API_KEY", "") not in str(status) if os.getenv("AION_API_KEY") else True

print("AGENTS RUNTIME ADAPTER TEST: PASS")
