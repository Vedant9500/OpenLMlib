from __future__ import annotations

import argparse
import json
from pathlib import Path
import traceback

from . import __version__
from .library import (
    add_finding,
    backup_library,
    get_finding,
    health,
    init_library,
    list_findings,
    rebuild_vector_index,
    restore_library,
    retrieve_findings,
    retrieve_prompt_context,
)
from .settings import load_settings


def _print_issues(issues) -> None:
    for issue in issues:
        prefix = "ERROR" if issue.severity == "error" else "WARN"
        print(f"{prefix}: {issue.field} - {issue.message}")


def cmd_init(args) -> int:
    result = init_library(Path(args.settings))
    print(result.get("message", "Initialized LMlib data layout and database"))
    return 0


def _check_python_deps() -> dict:
    checks = {}
    try:
        import numpy  # noqa: F401

        checks["numpy"] = "ok"
    except Exception as exc:
        checks["numpy"] = f"error: {exc}"

    try:
        import sentence_transformers  # noqa: F401

        checks["sentence_transformers"] = "ok"
    except Exception as exc:
        checks["sentence_transformers"] = f"error: {exc}"

    return checks


def _warm_embedding_model(settings_path: Path) -> dict:
    from .embeddings import EmbeddingCache, SentenceTransformerEmbedder

    settings = load_settings(settings_path)
    cache = EmbeddingCache(settings.embeddings_cache_path)
    embedder = SentenceTransformerEmbedder(
        settings.embedding_model,
        cache=cache,
        normalize=settings.embedding_metric == "cosine",
    )
    _ = embedder.encode(["lmlib setup warmup"])
    cache.save()
    return {"status": "ok", "model": settings.embedding_model}


def cmd_setup(args) -> int:
    settings_path = Path(args.settings)
    init_result = init_library(settings_path)
    if init_result.get("status") != "ok":
        print("ERROR: initialization failed")
        print(json.dumps(init_result, indent=2))
        return 1

    model_result = {"status": "skipped"}
    if not args.skip_model_warmup:
        try:
            model_result = _warm_embedding_model(settings_path)
        except Exception as exc:
            model_result = {
                "status": "error",
                "message": str(exc),
                "trace": traceback.format_exc(limit=1),
            }

    health_result = health(settings_path)
    rebuild_result = {"status": "not_required"}
    health_payload = health_result.get("health", {}) if isinstance(health_result, dict) else {}
    findings_count = int(health_payload.get("findings_count", 0) or 0)
    vector_count = int(health_payload.get("vector_count", 0) or 0)
    if findings_count > 0 and vector_count < findings_count:
        rebuild_result = rebuild_vector_index(settings_path)
        health_result = health(settings_path)

    output = {
        "status": "ok",
        "init": init_result,
        "model_warmup": model_result,
        "vector_rebuild": rebuild_result,
        "health": health_result,
    }
    print(json.dumps(output, indent=2))
    return 0 if model_result.get("status") in {"ok", "skipped"} else 1


def cmd_doctor(args) -> int:
    settings_path = Path(args.settings)
    checks = {
        "settings_path": str(settings_path),
        "deps": _check_python_deps(),
    }

    try:
        settings = load_settings(settings_path)
        checks["paths"] = {
            "data_root": str(settings.data_root),
            "db_path": str(settings.db_path),
            "vector_index_path": str(settings.vector_index_path),
            "findings_dir": str(settings.findings_dir),
        }
    except Exception as exc:
        checks["settings_error"] = str(exc)
        print(json.dumps({"status": "error", "checks": checks}, indent=2))
        return 1

    health_result = health(settings_path)
    checks["health"] = health_result

    if args.check_model:
        try:
            checks["model"] = _warm_embedding_model(settings_path)
        except Exception as exc:
            checks["model"] = {"status": "error", "message": str(exc)}

    dep_ok = all(value == "ok" for value in checks["deps"].values())
    health_ok = health_result.get("status") == "ok"
    model_ok = checks.get("model", {}).get("status") != "error"

    status = "ok" if dep_ok and health_ok and model_ok else "error"
    print(json.dumps({"status": status, "checks": checks}, indent=2))
    return 0 if status == "ok" else 1


def cmd_rebuild_index(args) -> int:
    result = rebuild_vector_index(Path(args.settings))
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") == "ok" else 1


def cmd_backup(args) -> int:
    output_dir = Path(args.output_dir) if args.output_dir else None
    result = backup_library(Path(args.settings), output_dir=output_dir)
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") == "ok" else 1


def cmd_restore(args) -> int:
    backup_dir = Path(args.backup_dir)
    result = restore_library(
        settings_path=Path(args.settings),
        backup_dir=backup_dir,
        confirm=args.confirm,
        create_pre_restore_backup=not args.no_pre_backup,
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") == "ok" else 1


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
    parser.add_argument("--version", action="version", version=f"lmlib {__version__}")
    parser.add_argument(
        "--settings",
        default="config/settings.json",
        help="Path to settings.json",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize database and storage")
    init_parser.set_defaults(func=cmd_init)

    setup_parser = subparsers.add_parser("setup", help="Bootstrap LMlib for first-time use")
    setup_parser.add_argument(
        "--skip-model-warmup",
        action="store_true",
        help="Skip one-time embedding model warmup/download",
    )
    setup_parser.set_defaults(func=cmd_setup)

    doctor_parser = subparsers.add_parser("doctor", help="Run environment and storage diagnostics")
    doctor_parser.add_argument(
        "--check-model",
        action="store_true",
        help="Attempt embedding model load as part of diagnostics",
    )
    doctor_parser.set_defaults(func=cmd_doctor)

    rebuild_parser = subparsers.add_parser(
        "rebuild-index",
        help="Rebuild vector index from stored findings",
    )
    rebuild_parser.set_defaults(func=cmd_rebuild_index)

    backup_parser = subparsers.add_parser(
        "backup",
        help="Create a timestamped backup of LMlib data",
    )
    backup_parser.add_argument(
        "--output-dir",
        help="Directory to write backup folder into (default: data/backups)",
    )
    backup_parser.set_defaults(func=cmd_backup)

    restore_parser = subparsers.add_parser(
        "restore",
        help="Restore LMlib data from a backup directory",
    )
    restore_parser.add_argument("--backup-dir", required=True, help="Backup directory path")
    restore_parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required to perform restore",
    )
    restore_parser.add_argument(
        "--no-pre-backup",
        action="store_true",
        help="Skip automatic pre-restore backup",
    )
    restore_parser.set_defaults(func=cmd_restore)

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
