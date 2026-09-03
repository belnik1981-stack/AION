import sys
from core.pipeline import run_pipeline

if __name__ == "__main__":
    task = " ".join(sys.argv[1:]).strip()
    if not task:
        print("Использование: python pipeline_cli.py <задача>")
        sys.exit(1)

    result = run_pipeline(task)
    print("\n=== СТАТУС:", result["status"], "===")
    print("\nФИНАЛЬНЫЙ ОТВЕТ:\n")
    print(result.get("final_answer", result.get("detail")))
