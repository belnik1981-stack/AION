"""Role errors must not disclose provider exception text or secrets."""
from unittest.mock import patch

from core import agents

secret = "sk-" + "or-v1-" + ("A" * 32)
with patch.object(agents, "governance_context", return_value="governance"), \
     patch.object(agents, "ask_llm", side_effect=RuntimeError(secret)):
    result = agents.planner("test task")

assert result.startswith("[ОШИБКА:planner]"), result
assert secret not in result, result
assert "role_execution_failed" in result, result

rate_limit_secret = "ACCOUNT-METADATA-MUST-NOT-LEAK"
with patch.object(agents, "governance_context", return_value="governance"), \
     patch.object(
         agents,
         "ask_llm",
         side_effect=agents.ProviderRateLimitError(rate_limit_secret),
     ):
    result = agents.planner("test task")

assert result == "[ОШИБКА:planner] provider_rate_limited", result
assert rate_limit_secret not in result, result

http_secret = "UNTRUSTED-STATUS-FIELD"
with patch.object(agents, "governance_context", return_value="governance"), \
     patch.object(
         agents,
         "ask_llm",
         side_effect=agents.ProviderHTTPError(http_secret, "hidden detail"),
     ):
    result = agents.planner("test task")

assert result == "[ОШИБКА:planner] provider_http_unknown", result
assert http_secret not in result, result
print("ROLE ERROR SANITIZATION: PASS")
