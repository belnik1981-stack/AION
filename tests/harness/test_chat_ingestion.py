import json
import tempfile
from pathlib import Path

from ingestion.chat_import import candidate_store_status, import_chat_export


def check(name, condition):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}")
    if not condition:
        raise AssertionError(name)


print("========== AION CHAT INGESTION TEST ==========")

sample = [
    {
        "id": "conv-1",
        "title": "AION test",
        "current_node": "a1",
        "mapping": {
            "root": {"id": "root", "parent": None, "message": None},
            "u1": {
                "id": "u1",
                "parent": "root",
                "message": {
                    "id": "msg-u1",
                    "author": {"role": "user"},
                    "content": {
                        "content_type": "text",
                        "parts": ["Use key sk-or-v1-ABCDEFGHIJKLMNOPQRSTUVWXYZ123456 for this test."],
                    },
                    "create_time": 1,
                },
            },
            "a1": {
                "id": "a1",
                "parent": "u1",
                "message": {
                    "id": "msg-a1",
                    "author": {"role": "assistant"},
                    "content": {
                        "content_type": "text",
                        "parts": ["The secret must never enter candidate storage verbatim."],
                    },
                    "create_time": 2,
                },
            },
        },
    }
]

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    export_path = root / "conversations.json"
    store_path = root / "candidates.jsonl"
    export_path.write_text(json.dumps(sample), encoding="utf-8")

    first = import_chat_export(export_path, store_path)
    check("one exchange imported", first["imported"] == 1)
    check("truth untouched", first["truth_modified"] is False)
    check("long-term untouched", first["long_term_modified"] is False)
    check("secret redaction reported", first["records_with_redactions"] == 1)

    stored = store_path.read_text(encoding="utf-8")
    check("secret absent from store", "sk-or-v1-ABCDEFGHIJKLMNOPQRSTUVWXYZ123456" not in stored)
    check("redaction marker present", "[REDACTED_SECRET]" in stored)

    second = import_chat_export(export_path, store_path)
    check("duplicate skipped", second["imported"] == 0 and second["duplicates_skipped"] == 1)

    status = candidate_store_status(store_path)
    check("candidate status counts records", status["records"] == 1)
    check("candidate remains unverified", status["unverified"] == 1)

print("CHAT INGESTION TEST: PASS")
