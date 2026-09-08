import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.engine import build_prompt, load_state
from core.truth import (
    get_execution_limits,
    get_principles,
    truth_status,
)
from tests.harness.mock_provider import MockProvider


def check(name, condition):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}")
    if not condition:
        raise AssertionError(name)


print("========== AION LOCAL ARCHITECTURE TEST ==========")

print("\n[1] Truth layer")
principles = get_principles()
limits = get_execution_limits()
truth = truth_status()

check("truth exists", truth["truth_exists"])
check("system exists", truth["system_exists"])
check("principles loaded", isinstance(principles, list) and len(principles) > 0)
check("max_iterations loaded", limits["max_iterations"] > 0)
check("timeout_seconds loaded", limits["timeout_seconds"] > 0)

print("\n[2] State")
state = load_state()
check("state is dict", isinstance(state, dict))

print("\n[3] Prompt construction")
prompt = build_prompt(state)
check("prompt is string", isinstance(prompt, str))
check("prompt contains a configured principle", principles[0] in prompt)
check("prompt contains limits", "max_iterations" in prompt and "timeout_seconds" in prompt)

print("\n[4] Provider contract")
provider = MockProvider()
check("MockProvider is provider-compatible", all(hasattr(provider, x) for x in ("ask", "health")))
health = provider.health()
check("provider health works", isinstance(health, dict))

print("\n[5] Provider execution")
response = provider.ask(prompt)
check("provider accepted prompt", len(provider.calls) == 1)
check("provider returned string", isinstance(response, str))
check("response received", response.startswith("MOCK_RESPONSE:"))

print("\n[6] State serialization")
test_state = {"status": "test", "response": response}
encoded = json.dumps(test_state, ensure_ascii=False)
decoded = json.loads(encoded)
check("state serializes", isinstance(decoded, dict))
check("response survives serialization", decoded["response"] == response)

print("\n========== RESULT ==========")
print("LOCAL ARCHITECTURE TEST: PASS")
print("Реальный API НЕ использовался.")
print("Проверен локальный execution path вокруг API-контракта.")
