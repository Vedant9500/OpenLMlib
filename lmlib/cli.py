from __future__ import annotations

import argparse
import json
from pathlib import Path

from .library import (
    add_finding,
    get_finding,
    init_library,
    list_findings,
    retrieve_findings,
    retrieve_prompt_context,
)


def _print_issues(issues) -> None:
    for issue in issues:
        prefix = "ERROR" if issue.severity == "error" else "WARN"
        print(f"{prefix}: {issue.field} - {issue.message}")


def cmd_init(args) -> int:
    result = init_library(Path(args.settings))
    print(result.get("message", "Initialized LMlib data layout and database"))
    return 0


def cmd_add(args) -> int:
    result = add_finding(
        settings_path=Path(args.settings),
        project=args.project,
        claim=args.claim,
        confidence=args.confidence,
        evidence=args.evidence or [],
        reasoning=args.reasoning,
        caveats=args.caveats or [],
        tags=args.tags or [],
        full_text=args.full_text or "",
        proposed_by=args.proposed_by or "",
        finding_id=args.id,
        confirm=True,
    )

    issues = result.get("issues", [])
    for issue in issues:
        prefix = "ERROR" if issue.get("severity") == "error" else "WARN"
        print(f"{prefix}: {issue.get('field')} - {issue.get('message')}")

    if result.get("status") != "ok":
        print("ERROR: failed to add finding")
        return 1

    print(f"Added finding {result.get('id')}")
    return 0


def cmd_list(args) -> int:
    result = list_findings(Path(args.settings), limit=args.limit, offset=args.offset)
    for row in result.get("items", []):
        print(
            f"{row['id']} | {row['project']} | {row['confidence']} | {row['created_at']} | {row['claim']}"
        )
    return 0


def cmd_get(args) -> int:
    result = get_finding(Path(args.settings), args.id)
    if result.get("status") != "ok":
        print("ERROR: finding not found")
        return 1

    print(json.dumps(result.get("finding"), indent=2))
    return 0


def cmd_query(args) -> int:
    if args.safe_context:
        result = retrieve_prompt_context(
            settings_path=Path(args.settings),
            query=args.query,
            project=args.project,
            tags=args.tags or [],
            confidence_min=args.confidence_min,
            final_k=args.final_k,
        )
        if result.get("status") != "ok":
            print("ERROR: retrieval failed")
            return 1
        print(result.get("safe_context", ""))
        return 0

    result = retrieve_findings(
        settings_path=Path(args.settings),
        query=args.query,
        project=args.project,
        tags=args.tags or [],
        created_after=args.created_after,
        created_before=args.created_before,
        confidence_min=args.confidence_min,
        semantic_k=args.semantic_k,
        lexical_k=args.lexical_k,
        final_k=args.final_k,
    )
    if result.get("status") != "ok":
        print("ERROR: retrieval failed")
        return 1

    print(json.dumps(result, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LMlib CLI")
    parser.add_argument(
        "--settings",
        default="config/settings.json",
        help="Path to settings.json",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize database and storage")
    init_parser.set_defaults(func=cmd_init)

    add_parser = subparsers.add_parser("add", help="Add a new finding")
    add_parser.add_argument("--id", help="Finding id")
    add_parser.add_argument("--project", required=True, help="Project name")
    add_parser.add_argument("--claim", required=True, help="Finding claim")
    add_parser.add_argument("--confidence", type=float, default=0.6, help="Confidence score")
    add_parser.add_argument("--evidence", action="append", help="Evidence item (repeatable)")
    add_parser.add_argument("--reasoning", required=True, help="Reasoning text")
    add_parser.add_argument("--caveats", action="append", help="Caveat (repeatable)")
    add_parser.add_argument("--tags", action="append", help="Tag (repeatable)")
    add_parser.add_argument("--full-text", help="Full text for JSON record")
    add_parser.add_argument("--proposed-by", help="Proposed by")
    add_parser.set_defaults(func=cmd_add)

    list_parser = subparsers.add_parser("list", help="List findings")
    list_parser.add_argument("--limit", type=int, default=50)
    list_parser.add_argument("--offset", type=int, default=0)
    list_parser.set_defaults(func=cmd_list)

    get_parser = subparsers.add_parser("get", help="Get a finding by id")
    get_parser.add_argument("--id", required=True)
    get_parser.set_defaults(func=cmd_get)

    query_parser = subparsers.add_parser("query", help="Retrieve findings with semantic + keyword search")
    query_parser.add_argument("--query", required=True, help="Query text")
    query_parser.add_argument("--project", help="Filter by project")
    query_parser.add_argument("--tags", action="append", help="Tag filter (repeatable)")
    query_parser.add_argument("--created-after", help="ISO timestamp lower bound")
    query_parser.add_argument("--created-before", help="ISO timestamp upper bound")
    query_parser.add_argument("--confidence-min", type=float, help="Minimum confidence")
    query_parser.add_argument("--semantic-k", type=int, help="Semantic candidate limit")
    query_parser.add_argument("--lexical-k", type=int, help="Keyword candidate limit")
    query_parser.add_argument("--final-k", type=int, help="Final returned results")
    query_parser.add_argument(
        "--safe-context",
        action="store_true",
        help="Render sanitized untrusted context block instead of JSON",
    )
    query_parser.set_defaults(func=cmd_query)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
