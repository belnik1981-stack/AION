#!/usr/bin/env python3
"""Collect public documents and write a non-admissible Evidence v2 draft."""

from __future__ import annotations

import argparse
import json
import sys

from evidence.candidate_bundle import (
    MAX_CANDIDATE_DOCUMENTS,
    EvidenceCandidateError,
    write_collected_candidate_bundle,
)
from evidence.collector import EvidenceCollector, EvidenceCollectorError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Collect bounded public documents into a quarantined Evidence Objects "
            "v2 draft. The result is always DENIED until separately verified."
        )
    )
    parser.add_argument("--claim", required=True, help="Claim requiring later verification")
    parser.add_argument(
        "--url",
        action="append",
        default=[],
        help="Public HTTP(S) seed URL; may be supplied more than once",
    )
    parser.add_argument("--output", required=True, help="New output directory")
    parser.add_argument(
        "--max-docs",
        type=int,
        default=5,
        choices=range(1, MAX_CANDIDATE_DOCUMENTS + 1),
        metavar=f"1..{MAX_CANDIDATE_DOCUMENTS}",
    )
    parser.add_argument("--timeout", type=int, default=20)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        collector = EvidenceCollector(timeout=args.timeout)
        documents = collector.collect(
            args.claim,
            seed_urls=args.url,
            limit=args.max_docs,
        )
        if not documents:
            raise EvidenceCandidateError("candidate_no_documents_collected")
        result = write_collected_candidate_bundle(
            args.claim,
            documents,
            args.output,
        )
    except (EvidenceCollectorError, EvidenceCandidateError) as exc:
        print(
            json.dumps(
                {"status": "error", "code": str(exc)},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

