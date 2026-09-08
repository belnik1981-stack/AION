import argparse
import json
from pathlib import Path

from verification.claim_extractor import heuristic_claims
from verification.pipeline import EvidenceItem, promote_verified_claim, verify_candidate_record


def load_candidate(path: str, candidate_id: str) -> dict:
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            item = json.loads(line)
            if item.get("candidate_id") == candidate_id:
                return item
    raise SystemExit(f"Candidate not found: {candidate_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description="AION candidate verification CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    extract = sub.add_parser("extract")
    extract.add_argument("store")
    extract.add_argument("candidate_id")

    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("store")
    evaluate.add_argument("candidate_id")
    evaluate.add_argument("claim")
    evaluate.add_argument("evidence_json", help="JSON array of evidence items")

    promote = sub.add_parser("promote")
    promote.add_argument("verification_json", help="Path to verification record JSON")

    args = parser.parse_args()

    if args.command == "extract":
        candidate = load_candidate(args.store, args.candidate_id)
        print(json.dumps(heuristic_claims(candidate), ensure_ascii=False, indent=2))
        return

    if args.command == "evaluate":
        candidate = load_candidate(args.store, args.candidate_id)
        raw = json.loads(args.evidence_json)
        evidence = [EvidenceItem(**item) for item in raw]
        result = verify_candidate_record(candidate, args.claim, evidence)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    record = json.loads(Path(args.verification_json).read_text(encoding="utf-8"))
    result = promote_verified_claim(record)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
