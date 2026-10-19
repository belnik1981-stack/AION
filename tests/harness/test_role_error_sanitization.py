"""Role errors must not disclose provider exception text or secrets."""
from unittest.mock import patch

from core import agents

secret = "sk-or-v1-EXAMPLEPRIVATEACCOUNTSECRET"
with patch.object(agents, "governance_context", return_value="governance"), \
     patch.object(agents, "ask_llm", side_effect=RuntimeError(secret)):
    result = agents.planner("test task")

assert result.startswith("[ОШИБКА:planner]"), result
assert secret not in result, result
assert "role_execution_failed" in result, result
print("ROLE ERROR SANITIZATION: PASS")
