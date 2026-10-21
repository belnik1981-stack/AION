import json
import sys

from runtimes.openai_agents import AgentsRuntimeError, run_agent, runtime_status


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--status":
        print(json.dumps(runtime_status(), indent=2, ensure_ascii=False))
        raise SystemExit(0)

    task = " ".join(sys.argv[1:]).strip()
    if not task:
        print("Использование: python agents_cli.py <задача> | --status")
        raise SystemExit(1)

    try:
        result = run_agent(task)
    except AgentsRuntimeError as exc:
        print(json.dumps({"status": "error", "detail": str(exc)}, ensure_ascii=False))
        raise SystemExit(2)

    print(json.dumps(result, indent=2, ensure_ascii=False))
