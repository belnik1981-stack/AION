import argparse
import json
import sys

from ingestion.chat_import import (
    ChatImportError,
    candidate_store_status,
    import_chat_export,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="AION controlled chat-ingestion CLI"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    status_parser = sub.add_parser(
        "status",
        help="Show candidate-store status without exposing chat contents.",
    )
    status_parser.add_argument(
        "--store",
        default=None,
        help="Optional candidate JSONL path.",
    )

    import_parser = sub.add_parser(
        "import",
        help="Import a ChatGPT-compatible JSON export into unverified candidates.",
    )
    import_parser.add_argument("export_path")
    import_parser.add_argument(
        "--store",
        default=None,
        help="Optional candidate JSONL path.",
    )

    args = parser.parse_args()

    try:
        if args.command == "status":
            result = (
                candidate_store_status(args.store)
                if args.store
                else candidate_store_status()
            )
        else:
            result = (
                import_chat_export(args.export_path, args.store)
                if args.store
                else import_chat_export(args.export_path)
            )
    except ChatImportError as exc:
        print(json.dumps({"status": "error", "detail": str(exc)}, ensure_ascii=False))
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
