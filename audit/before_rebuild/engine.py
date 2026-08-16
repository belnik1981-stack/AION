import json
from pathlib import Path
from datetime import datetime

from core.llm import ask_llm

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "state.json"


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state):
    STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def run_cycle():
    state = load_state()

    prompt = (
        "Ты ядро системы AION.\n"
        f"Текущее состояние:\n{json.dumps(state, ensure_ascii=False, indent=2)}\n\n"
        "Предложи одно следующее действие."
    )

    answer = ask_llm(prompt)

    state["last_run"] = datetime.now().isoformat()
    state["last_answer"] = answer
    state["status"] = "running"

    save_state(state)

    print("\n=== AION ===")
    print(answer)
    print("============")


if __name__ == "__main__":
    run_cycle()
