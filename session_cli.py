"""Local operational-memory controls; never requests a model or network API."""

import argparse
import json

from memory.session import (
    create_checkpoint, record_decision, recover_interrupted, restore_backup,
    set_setting, snapshot,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="AION operational memory")
    commands = parser.add_subparsers(dest="command", required=True)
    status = commands.add_parser("status")
    status.add_argument("--limit", type=int, default=20)
    status.add_argument("--offset", type=int, default=0)
    setting = commands.add_parser("set")
    setting.add_argument("key")
    setting.add_argument("value")
    decision = commands.add_parser("decision")
    decision.add_argument("text")
    checkpoint = commands.add_parser("checkpoint")
    checkpoint.add_argument("label")
    restore = commands.add_parser("restore")
    restore.add_argument("backup_name")
    args = parser.parse_args()

    if args.command == "status":
        recover_interrupted()
        print(json.dumps(snapshot(limit=args.limit, offset=args.offset), ensure_ascii=False, indent=2))
    elif args.command == "set":
        set_setting(args.key, args.value)
        print("[PASS] Настройка сохранена")
    elif args.command == "decision":
        print("[PASS] Решение сохранено:", record_decision(args.text))
    elif args.command == "checkpoint":
        print("[PASS] Контрольная точка:", create_checkpoint(args.label))
    elif args.command == "restore":
        restore_backup(args.backup_name)
        print("[PASS] Резервная копия восстановлена; предыдущие файлы сохранены")


if __name__ == "__main__":
    main()
