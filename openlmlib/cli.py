from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import traceback

from . import __version__
from .library import (
    add_finding,
    archive_finding,
    backup_library,
    evaluate_dataset,
    find_stale_findings,
    generate_cluster_summary,
    get_failure_ledger,
    get_finding,
    get_maintenance_summary,
    health,
    init_library,
    list_findings,
    log_finding_failure,
    mark_findings_for_review,
    rebuild_vector_index,
    restore_finding,
    restore_library,
    retrieve_findings,
    retrieve_findings_enhanced,
    retrieve_prompt_context,
    run_consolidation,
)
from .mcp_setup import (
    available_clients,
    install_client_configs,
    install_or_refresh_default_client_configs,
    normalize_client_ids,
)
from .settings import load_settings, resolve_global_settings_path


def _print_issues(issues) -> None:
    for issue in issues:
        prefix = "ERROR" if issue.severity == "error" else "WARN"
        print(f"{prefix}: {issue.field} - {issue.message}")


def _interactive_terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _requested_client_ids(args) -> list[str]:
    return normalize_client_ids(getattr(args, "ide", None))


def _run_mcp_setup(settings_path: Path, requested_client_ids: list[str]) -> dict:
    if requested_client_ids:
        return install_client_configs(requested_client_ids, settings_path=settings_path)

    if not _interactive_terminal():
        result = install_or_refresh_default_client_configs(settings_path=settings_path)
        result["message"] = (
            "Non-interactive shell; refreshed MCP configs for existing clients "
            "(or installed VS Code default)."
        )
        return result

    from .tui_setup import run_interactive_setup

    return run_interactive_setup(settings_path)


def _print_setup_summary(output: dict) -> None:
    init_result = output.get("init", {})
    model_result = output.get("model_warmup", {})
    rebuild_result = output.get("vector_rebuild", {})
    health_result = output.get("health", {}).get("health", {})
    mcp_result = output.get("mcp_config", {})

    print("OpenLMlib setup")
    print(f"Settings: {output.get('settings_path', '')}")
    print(f"Database: {init_result.get('db_path', '')}")

    model_status = model_result.get("status", "unknown")
    print(f"Model warmup: {model_status}")

    if rebuild_result.get("status") == "ok":
        print(f"Vector index rebuild: rebuilt {rebuild_result.get('rebuilt', 0)} items")
    else:
        print(f"Vector index rebuild: {rebuild_result.get('status', 'not_required')}")

    print(
        "Health: "
        f"{health_result.get('findings_count', 0)} findings, "
        f"{health_result.get('vector_count', 0)} vectors"
    )

    if mcp_result.get("status") == "skipped":
        print(f"MCP install: {mcp_result.get('message', 'skipped')}")
    elif mcp_result.get("status") in {"ok", "partial", "error"}:
        successful = [item.get("label") for item in mcp_result.get("results", []) if item.get("status") == "ok"]
        failed = [item.get("label") for item in mcp_result.get("results", []) if item.get("status") != "ok"]
        print(f"MCP install: {mcp_result.get('status')}")
        if successful:
            print(f"Installed for: {', '.join(str(value) for value in successful)}")
        if failed:
            print(f"Needs attention: {', '.join(str(value) for value in failed)}")


def cmd_init(args) -> int:
    result = init_library(Path(args.settings))
    print(result.get("message", "Initialized OpenLMlib data layout and database"))
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
    _ = embedder.encode(["openlmlib setup warmup"])
    cache.save()
    return {"status": "ok", "model": settings.embedding_model}


def cmd_setup(args) -> int:
    settings_path = Path(args.settings)
    try:
        requested_client_ids = _requested_client_ids(args)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 1

    if _interactive_terminal():
        from .tui_setup import run_interactive_setup
        result = run_interactive_setup(settings_path)
        if result.get("status") == "ok":
            return 0
        print(f"ERROR: {result.get('message', 'unknown error')}")
        return 1

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

    mcp_result = {"status": "skipped", "results": []}
    if not args.skip_mcp_config:
        mcp_result = _run_mcp_setup(settings_path, requested_client_ids)

    output = {
        "status": "ok",
        "settings_path": str(settings_path),
        "init": init_result,
        "model_warmup": model_result,
        "vector_rebuild": rebuild_result,
        "health": health_result,
        "mcp_config": mcp_result,
    }
    print(json.dumps(output, indent=2))

    mcp_ok = mcp_result.get("status") in {"ok", "skipped"}
    return 0 if model_result.get("status") in {"ok", "skipped"} and mcp_ok else 1


def cmd_mcp_config(args) -> int:
    if args.list_ides:
        for client in available_clients():
            print(f"{client.id} - {client.label}")
        return 0

    try:
        requested_client_ids = _requested_client_ids(args)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 1

    if args.refresh_defaults and not requested_client_ids:
        result = install_or_refresh_default_client_configs(settings_path=Path(args.settings))
    else:
        result = _run_mcp_setup(Path(args.settings), requested_client_ids)
    if not (_interactive_terminal() and not requested_client_ids):
        print(json.dumps(result, indent=2))
    return 0 if result.get("status") in {"ok", "skipped"} else 1


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


def cmd_query_enhanced(args) -> int:
    result = retrieve_findings_enhanced(
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
        rerank=not args.no_rerank,
        rerank_top_k=args.rerank_top_k,
        expand_query=args.expand,
        decompose=not args.no_decompose,
        deduplicate=not args.no_dedup,
        dedup_threshold=args.dedup_threshold,
        pack_context=args.pack,
        max_context_tokens=args.max_tokens,
        reasoning_trace=not args.no_trace,
    )
    if result.get("status") != "ok":
        print("ERROR: retrieval failed")
        return 1

    print(json.dumps(result, indent=2))
    return 0


def cmd_maintenance(args) -> int:
    result = get_maintenance_summary(
        settings_path=Path(args.settings),
        validity_days=args.validity_days,
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") == "ok" else 1


def cmd_stale(args) -> int:
    result = find_stale_findings(
        settings_path=Path(args.settings),
        validity_days=args.validity_days,
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") == "ok" else 1


def cmd_consolidate(args) -> int:
    result = run_consolidation(
        settings_path=Path(args.settings),
        similarity_threshold=args.threshold,
        project=args.project,
        auto_consolidate=args.auto,
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") == "ok" else 1


def cmd_failure(args) -> int:
    if args.ledger:
        result = get_failure_ledger(
            settings_path=Path(args.settings),
            finding_id=args.finding_id,
            limit=args.limit,
        )
        print(json.dumps(result, indent=2))
        return 0 if result.get("status") == "ok" else 1

    result = log_finding_failure(
        settings_path=Path(args.settings),
        finding_id=args.finding_id,
        task_id=args.task_id,
        failure_reason=args.reason,
        confidence_decay=args.decay,
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") == "ok" else 1


def cmd_archive(args) -> int:
    if args.restore:
        result = restore_finding(
            settings_path=Path(args.settings),
            finding_id=args.finding_id,
        )
    else:
        result = archive_finding(
            settings_path=Path(args.settings),
            finding_id=args.finding_id,
            reason=args.reason or "",
            confirm=args.confirm,
        )
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") == "ok" else 1


def cmd_eval(args) -> int:
    result = evaluate_dataset(
        settings_path=Path(args.settings),
        dataset_path=Path(args.dataset),
        final_k=args.final_k,
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") == "ok" else 1


# ── CollabSessions CLI commands ──────────────────────────────────────────

def _get_collab_paths(settings_path: Path) -> tuple:
    """Get collab DB path and sessions directory from settings."""
    if settings_path.exists():
        with open(settings_path) as f:
            cfg = json.load(f)
        data_root = Path(cfg.get("data_root", "data"))
    else:
        data_root = Path("data")
    return data_root / "collab_sessions.db", data_root / "sessions"


def _collab_connection(settings_path: Path):
    """Get an initialized collab DB connection."""
    from openlmlib.collab.db import connect_collab_db, init_collab_db
    db_path, sessions_dir = _get_collab_paths(settings_path)
    sessions_dir.mkdir(parents=True, exist_ok=True)
    conn = connect_collab_db(db_path)
    existing = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'"
    ).fetchone()
    if existing is None:
        init_collab_db(conn)
    return conn, sessions_dir


def cmd_collab_create(args) -> int:
    from openlmlib.collab.session import create_collab_session
    conn, sessions_dir = _collab_connection(Path(args.settings))
    try:
        plan = None
        if args.plan:
            with open(args.plan) as f:
                plan = json.load(f)
        rules = None
        if args.rules:
            with open(args.rules) as f:
                rules = json.load(f)
        result = create_collab_session(
            conn, sessions_dir,
            title=args.title,
            created_by=args.by,
            description=args.task,
            plan=plan,
            rules=rules,
        )
        print(json.dumps(result, indent=2))
        return 0
    finally:
        conn.close()


def cmd_collab_list(args) -> int:
    from openlmlib.collab.db import list_sessions
    conn, _ = _collab_connection(Path(args.settings))
    try:
        sessions = list_sessions(conn, status=args.status, limit=args.limit)
        print(json.dumps({"sessions": sessions, "count": len(sessions)}, indent=2))
        return 0
    finally:
        conn.close()


def cmd_collab_join(args) -> int:
    from openlmlib.collab.session import join_collab_session
    conn, sessions_dir = _collab_connection(Path(args.settings))
    try:
        result = join_collab_session(
            conn, sessions_dir,
            session_id=args.session_id,
            model=args.model,
            capabilities=args.capabilities,
        )
        print(json.dumps(result, indent=2))
        return 0
    finally:
        conn.close()


def cmd_collab_state(args) -> int:
    from openlmlib.collab.db import get_session, get_session_state, get_session_tasks, get_session_agents
    conn, _ = _collab_connection(Path(args.settings))
    try:
        session = get_session(conn, args.session_id)
        if session is None:
            print(f"Session {args.session_id} not found")
            return 1
        state = get_session_state(conn, args.session_id)
        tasks = get_session_tasks(conn, args.session_id)
        agents = get_session_agents(conn, args.session_id)
        output = {
            "session": session,
            "state": state["state"] if state else {},
            "tasks": tasks,
            "agents": agents,
        }
        print(json.dumps(output, indent=2))
        return 0
    finally:
        conn.close()


def cmd_collab_messages(args) -> int:
    from openlmlib.collab.db import get_messages
    conn, _ = _collab_connection(Path(args.settings))
    try:
        msg_types = [args.msg_type] if args.msg_type else None
        messages = get_messages(
            conn, args.session_id,
            limit=args.limit,
            msg_types=msg_types,
            from_agent=args.from_agent,
        )
        for msg in messages:
            to = msg.get("to_agent") or "all"
            print(f"[{msg['seq']}] [{msg['from_agent']} → {to}] [{msg['msg_type']}] {msg['content']}")
        print(f"\n{len(messages)} messages")
        return 0
    finally:
        conn.close()


def cmd_collab_tail(args) -> int:
    from openlmlib.collab.db import get_messages_tail
    conn, _ = _collab_connection(Path(args.settings))
    try:
        messages = get_messages_tail(conn, args.session_id, args.lines)
        for msg in messages:
            to = msg.get("to_agent") or "all"
            print(f"[{msg['seq']}] [{msg['from_agent']} → {to}] [{msg['msg_type']}] {msg['content']}")
        print(f"\n{len(messages)} messages")
        return 0
    finally:
        conn.close()


def cmd_collab_grep(args) -> int:
    from openlmlib.collab.db import grep_messages
    conn, _ = _collab_connection(Path(args.settings))
    try:
        messages = grep_messages(conn, args.session_id, args.pattern, args.limit)
        for msg in messages:
            to = msg.get("to_agent") or "all"
            print(f"[{msg['seq']}] [{msg['from_agent']} → {to}] [{msg['msg_type']}] {msg['content']}")
        print(f"\n{len(messages)} matches")
        return 0
    finally:
        conn.close()


def cmd_collab_artifacts(args) -> int:
    from openlmlib.collab.db import get_session_artifacts
    conn, _ = _collab_connection(Path(args.settings))
    try:
        artifacts = get_session_artifacts(
            conn, args.session_id,
            created_by=args.agent,
            artifact_type=args.type,
        )
        for art in artifacts:
            tags = f" [{', '.join(art['tags'])}]" if art.get("tags") else ""
            print(f"  {art['artifact_id']}: {art['title']} "
                  f"(by {art['created_by']}, {art.get('word_count', '?')} words){tags}")
        print(f"\n{len(artifacts)} artifacts")
        return 0
    finally:
        conn.close()


def cmd_collab_timeline(args) -> int:
    from openlmlib.collab.db import get_messages
    conn, _ = _collab_connection(Path(args.settings))
    try:
        messages = get_messages(conn, args.session_id, limit=args.limit)
        for msg in messages:
            to = msg.get("to_agent") or "all"
            ts = msg.get("created_at", "")[:19]
            print(f"{ts} [{msg['from_agent']} → {to}] [{msg['msg_type']}]")
            print(f"  {msg['content'][:120]}")
            print()
        print(f"{len(messages)} messages in timeline")
        return 0
    finally:
        conn.close()


def cmd_collab_compact(args) -> int:
    from openlmlib.collab.db import get_session_state, get_max_seq
    from openlmlib.collab.message_bus import MessageBus
    from openlmlib.collab.artifact_store import ArtifactStore
    from openlmlib.collab.state_manager import StateManager
    from openlmlib.collab.compactor import SessionCompactor
    conn, sessions_dir = _collab_connection(Path(args.settings))
    try:
        state = get_session_state(conn, args.session_id)
        if state is None:
            print(f"Session {args.session_id} not found")
            return 1
        last_seq = state["state"].get("last_compact_seq", 0)
        bus = MessageBus(conn, sessions_dir)
        store = ArtifactStore(conn, sessions_dir)
        sm = StateManager(conn)
        compactor = SessionCompactor(conn, sessions_dir, bus, store, sm)
        result = compactor.compact_session(args.session_id, last_seq)
        if result:
            print(json.dumps(result, indent=2))
        else:
            print("No messages to summarize")
        return 0
    finally:
        conn.close()


def cmd_collab_terminate(args) -> int:
    from openlmlib.collab.session import terminate_collab_session
    conn, sessions_dir = _collab_connection(Path(args.settings))
    try:
        result = terminate_collab_session(
            conn, sessions_dir,
            session_id=args.session_id,
            summary=args.summary,
        )
        print(json.dumps(result, indent=2))
        return 0
    finally:
        conn.close()


def cmd_collab_export(args) -> int:
    import shutil
    from openlmlib.collab.db import get_session
    conn, sessions_dir = _collab_connection(Path(args.settings))
    try:
        session = get_session(conn, args.session_id)
        if session is None:
            print(f"Session {args.session_id} not found")
            return 1
        src = sessions_dir / args.session_id
        dst = Path(args.output_dir) / args.session_id
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dst, dirs_exist_ok=True)
            print(f"Exported session to {dst}")
            return 0
        else:
            print(f"Session directory not found: {src}")
            return 1
    finally:
        conn.close()


def cmd_collab_inspect(args) -> int:
    from openlmlib.collab.db import (
        get_session, get_session_state, get_session_tasks,
        get_session_agents, get_session_artifacts, get_max_seq,
    )
    conn, _ = _collab_connection(Path(args.settings))
    try:
        session = get_session(conn, args.session_id)
        if session is None:
            print(f"Session {args.session_id} not found")
            return 1
        state = get_session_state(conn, args.session_id)
        tasks = get_session_tasks(conn, args.session_id)
        agents = get_session_agents(conn, args.session_id)
        artifacts = get_session_artifacts(conn, args.session_id)
        msg_count = get_max_seq(conn, args.session_id)

        print(f"Session: {session['title']}")
        print(f"ID: {session['session_id']}")
        print(f"Status: {session['status']}")
        print(f"Orchestrator: {session['orchestrator']}")
        print(f"Created: {session['created_at']}")
        print(f"Messages: {msg_count}")
        print(f"Agents: {len(agents)} ({len([a for a in agents if a['status'] == 'active'])} active)")
        print(f"Tasks: {len(tasks)} ({len([t for t in tasks if t['status'] == 'completed'])} completed)")
        print(f"Artifacts: {len(artifacts)}")
        if state:
            s = state["state"]
            print(f"Phase: {s.get('current_phase', 'unknown')}")
            print(f"Last activity: {s.get('last_activity', 'unknown')}")
        return 0
    finally:
        conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OpenLMlib CLI")
    parser.add_argument("--version", action="version", version=f"openlmlib {__version__}")
    parser.add_argument(
        "--settings",
        default=str(resolve_global_settings_path()),
        help="Path to settings.json",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize database and storage")
    init_parser.set_defaults(func=cmd_init)

    mcp_config_parser = subparsers.add_parser("mcp-config", help="Configure MCP client connections interactively")
    mcp_config_parser.add_argument(
        "--ide",
        action="append",
        help="IDE/client to configure. Repeat or pass a comma-separated list.",
    )
    mcp_config_parser.add_argument(
        "--list-ides",
        action="store_true",
        help="List supported IDE/client identifiers and exit.",
    )
    mcp_config_parser.add_argument(
        "--refresh-defaults",
        action="store_true",
        help="Refresh existing client MCP entries, or install VS Code config if none exist.",
    )
    mcp_config_parser.set_defaults(func=cmd_mcp_config)

    setup_parser = subparsers.add_parser("setup", help="Bootstrap OpenLMlib for first-time use")
    setup_parser.add_argument(
        "--skip-model-warmup",
        action="store_true",
        help="Skip one-time embedding model warmup/download",
    )
    setup_parser.add_argument(
        "--skip-mcp-config",
        action="store_true",
        help="Skip the global MCP installation step.",
    )
    setup_parser.add_argument(
        "--ide",
        action="append",
        help="IDE/client to configure globally. Repeat or pass a comma-separated list.",
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
        help="Create a timestamped backup of OpenLMlib data",
    )
    backup_parser.add_argument(
        "--output-dir",
        help="Directory to write backup folder into (default: data/backups)",
    )
    backup_parser.set_defaults(func=cmd_backup)

    restore_parser = subparsers.add_parser(
        "restore",
        help="Restore OpenLMlib data from a backup directory",
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

    query_enhanced_parser = subparsers.add_parser(
        "query-enhanced",
        help="Retrieve findings with Phase 4 enhancements (reranking, expansion, decomposition, packing)",
    )
    query_enhanced_parser.add_argument("--query", required=True, help="Query text")
    query_enhanced_parser.add_argument("--project", help="Filter by project")
    query_enhanced_parser.add_argument("--tags", action="append", help="Tag filter (repeatable)")
    query_enhanced_parser.add_argument("--created-after", help="ISO timestamp lower bound")
    query_enhanced_parser.add_argument("--created-before", help="ISO timestamp upper bound")
    query_enhanced_parser.add_argument("--confidence-min", type=float, help="Minimum confidence")
    query_enhanced_parser.add_argument("--semantic-k", type=int, help="Semantic candidate limit")
    query_enhanced_parser.add_argument("--lexical-k", type=int, help="Keyword candidate limit")
    query_enhanced_parser.add_argument("--final-k", type=int, help="Final returned results")
    query_enhanced_parser.add_argument(
        "--no-rerank",
        action="store_true",
        help="Disable cross-encoder reranking",
    )
    query_enhanced_parser.add_argument(
        "--rerank-top-k",
        type=int,
        help="Top-k results after reranking",
    )
    query_enhanced_parser.add_argument(
        "--expand",
        action="store_true",
        help="Enable query expansion (multiple variants)",
    )
    query_enhanced_parser.add_argument(
        "--no-decompose",
        action="store_true",
        help="Disable document decomposition",
    )
    query_enhanced_parser.add_argument(
        "--pack",
        action="store_true",
        help="Enable position-aware context packing",
    )
    query_enhanced_parser.add_argument(
        "--max-tokens",
        type=int,
        default=4000,
        help="Maximum context tokens for packing",
    )
    query_enhanced_parser.add_argument(
        "--no-dedup",
        action="store_true",
        help="Disable cross-project deduplication",
    )
    query_enhanced_parser.add_argument(
        "--dedup-threshold",
        type=float,
        default=0.85,
        help="Similarity threshold for deduplication (0.0-1.0)",
    )
    query_enhanced_parser.add_argument(
        "--no-trace",
        action="store_true",
        help="Disable reasoning trace output",
    )
    query_enhanced_parser.set_defaults(func=cmd_query_enhanced)

    eval_parser = subparsers.add_parser("eval", help="Run retrieval evaluation on a query dataset")
    eval_parser.add_argument(
        "--dataset",
        default="config/eval_queries.json",
        help="Path to evaluation dataset JSON",
    )
    eval_parser.add_argument(
        "--final-k",
        type=int,
        default=10,
        help="Top-k results to evaluate against expected IDs",
    )
    eval_parser.set_defaults(func=cmd_eval)

    # Phase 5: Maintenance commands
    maint_parser = subparsers.add_parser("maintenance", help="Get library maintenance summary")
    maint_parser.add_argument(
        "--validity-days",
        type=int,
        help="Override validity window in days",
    )
    maint_parser.set_defaults(func=cmd_maintenance)

    stale_parser = subparsers.add_parser("stale", help="Find stale findings needing review")
    stale_parser.add_argument(
        "--validity-days",
        type=int,
        help="Override validity window in days",
    )
    stale_parser.set_defaults(func=cmd_stale)

    consolidate_parser = subparsers.add_parser("consolidate", help="Find and merge similar findings")
    consolidate_parser.add_argument(
        "--threshold",
        type=float,
        default=0.85,
        help="Similarity threshold for grouping (0.0-1.0)",
    )
    consolidate_parser.add_argument(
        "--project",
        help="Filter by project",
    )
    consolidate_parser.add_argument(
        "--auto",
        action="store_true",
        help="Automatically consolidate similar findings",
    )
    consolidate_parser.set_defaults(func=cmd_consolidate)

    failure_parser = subparsers.add_parser("failure", help="Log or view finding failures")
    failure_parser.add_argument(
        "--finding-id",
        help="Finding ID to log failure for or view ledger",
    )
    failure_parser.add_argument(
        "--task-id",
        help="Task ID that failed",
    )
    failure_parser.add_argument(
        "--reason",
        help="Failure reason description",
    )
    failure_parser.add_argument(
        "--decay",
        type=float,
        help="Confidence decay factor (default 0.9)",
    )
    failure_parser.add_argument(
        "--ledger",
        action="store_true",
        help="View failure ledger instead of logging",
    )
    failure_parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Max ledger entries to return",
    )
    failure_parser.set_defaults(func=cmd_failure)

    archive_parser = subparsers.add_parser("archive", help="Archive or restore findings")
    archive_parser.add_argument(
        "--finding-id",
        required=True,
        help="Finding ID to archive or restore",
    )
    archive_parser.add_argument(
        "--reason",
        help="Reason for archiving",
    )
    archive_parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required to perform archive",
    )
    archive_parser.add_argument(
        "--restore",
        action="store_true",
        help="Restore an archived finding instead of archiving",
    )
    archive_parser.set_defaults(func=cmd_archive)

    # ── CollabSessions sub-commands ──────────────────────────────────────
    collab_parser = subparsers.add_parser(
        "collab", help="Multi-agent collaboration sessions"
    )
    collab_sub = collab_parser.add_subparsers(dest="collab_command", required=True)

    # collab create
    collab_create_p = collab_sub.add_parser("create", help="Create a new collaboration session")
    collab_create_p.add_argument("--title", required=True, help="Session title")
    collab_create_p.add_argument("--task", required=True, help="Task description")
    collab_create_p.add_argument("--plan", help="JSON file with task plan")
    collab_create_p.add_argument("--rules", help="JSON file with session rules")
    collab_create_p.add_argument("--by", default="user", help="Creator identifier")
    collab_create_p.set_defaults(func=cmd_collab_create)

    # collab list
    collab_list_p = collab_sub.add_parser("list", help="List collaboration sessions")
    collab_list_p.add_argument("--status", help="Filter by status (active, completed, terminated)")
    collab_list_p.add_argument("--limit", type=int, default=20, help="Max sessions to show")
    collab_list_p.set_defaults(func=cmd_collab_list)

    # collab join
    collab_join_p = collab_sub.add_parser("join", help="Join an existing session")
    collab_join_p.add_argument("session_id", help="Session ID to join")
    collab_join_p.add_argument("--model", required=True, help="Your model identifier")
    collab_join_p.add_argument("--capabilities", action="append", help="Capabilities (repeatable)")
    collab_join_p.set_defaults(func=cmd_collab_join)

    # collab state
    collab_state_p = collab_sub.add_parser("state", help="Get session state")
    collab_state_p.add_argument("session_id", help="Session ID")
    collab_state_p.set_defaults(func=cmd_collab_state)

    # collab messages
    collab_msgs_p = collab_sub.add_parser("messages", help="View session messages")
    collab_msgs_p.add_argument("session_id", help="Session ID")
    collab_msgs_p.add_argument("--limit", type=int, default=20, help="Max messages")
    collab_msgs_p.add_argument("--type", dest="msg_type", help="Filter by message type")
    collab_msgs_p.add_argument("--from", dest="from_agent", help="Filter by sender")
    collab_msgs_p.set_defaults(func=cmd_collab_messages)

    # collab tail
    collab_tail_p = collab_sub.add_parser("tail", help="View last N messages")
    collab_tail_p.add_argument("session_id", help="Session ID")
    collab_tail_p.add_argument("--lines", type=int, default=20, help="Number of messages")
    collab_tail_p.set_defaults(func=cmd_collab_tail)

    # collab grep
    collab_grep_p = collab_sub.add_parser("grep", help="Search session messages")
    collab_grep_p.add_argument("session_id", help="Session ID")
    collab_grep_p.add_argument("pattern", help="Search pattern")
    collab_grep_p.add_argument("--limit", type=int, default=50, help="Max results")
    collab_grep_p.set_defaults(func=cmd_collab_grep)

    # collab artifacts
    collab_artifacts_p = collab_sub.add_parser("artifacts", help="List session artifacts")
    collab_artifacts_p.add_argument("session_id", help="Session ID")
    collab_artifacts_p.add_argument("--agent", help="Filter by creator")
    collab_artifacts_p.add_argument("--type", help="Filter by type")
    collab_artifacts_p.set_defaults(func=cmd_collab_artifacts)

    # collab timeline
    collab_timeline_p = collab_sub.add_parser("timeline", help="Chronological session view")
    collab_timeline_p.add_argument("session_id", help="Session ID")
    collab_timeline_p.add_argument("--limit", type=int, default=50, help="Max messages")
    collab_timeline_p.set_defaults(func=cmd_collab_timeline)

    # collab compact
    collab_compact_p = collab_sub.add_parser("compact", help="Force session summarization")
    collab_compact_p.add_argument("session_id", help="Session ID")
    collab_compact_p.set_defaults(func=cmd_collab_compact)

    # collab terminate
    collab_term_p = collab_sub.add_parser("terminate", help="End a session")
    collab_term_p.add_argument("session_id", help="Session ID")
    collab_term_p.add_argument("--summary", help="Final summary text")
    collab_term_p.set_defaults(func=cmd_collab_terminate)

    # collab export
    collab_export_p = collab_sub.add_parser("export", help="Export session artifacts")
    collab_export_p.add_argument("session_id", help="Session ID")
    collab_export_p.add_argument("--output-dir", required=True, help="Output directory")
    collab_export_p.set_defaults(func=cmd_collab_export)

    # collab inspect
    collab_inspect_p = collab_sub.add_parser("inspect", help="Full session overview")
    collab_inspect_p.add_argument("session_id", help="Session ID")
    collab_inspect_p.set_defaults(func=cmd_collab_inspect)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
