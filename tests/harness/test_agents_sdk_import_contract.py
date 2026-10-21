"""Import-level contract for the pinned optional SDK; never calls a provider."""

import asyncio
import inspect
from importlib.metadata import PackageNotFoundError, version


try:
    from agents import Agent, ModelSettings, OpenAIChatCompletionsModel, Runner
    from openai import AsyncOpenAI
except ImportError:
    print("AGENTS SDK IMPORT CONTRACT: SKIP (optional dependency not installed)")
    raise SystemExit(0)

try:
    installed = version("openai-agents")
except PackageNotFoundError as exc:
    raise AssertionError("Agents module exists without package metadata") from exc
assert installed == "0.22.1", installed

settings = ModelSettings(max_tokens=100, timeout=1.0)
assert settings.max_tokens == 100
assert settings.timeout == 1.0
assert inspect.iscoroutinefunction(Runner.run)

client = AsyncOpenAI(
    api_key="synthetic-import-contract-key",
    base_url="https://openrouter.ai/api/v1",
    timeout=1.0,
    max_retries=0,
)
model = OpenAIChatCompletionsModel(
    model="synthetic/model:free",
    openai_client=client,
    strict_feature_validation=True,
)
agent = Agent(
    name="AION Import Contract",
    instructions="No network execution.",
    model=model,
    model_settings=settings,
)
assert agent.model is model
assert agent.model_settings.max_tokens == 100
asyncio.run(client.close())

print("AGENTS SDK IMPORT CONTRACT: PASS")
