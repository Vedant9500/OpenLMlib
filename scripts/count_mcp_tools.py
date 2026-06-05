#!/usr/bin/env python3
"""Count and verify registered OpenLMlib MCP tools.

Run this with the same Python environment used by your MCP client config.
For a source checkout on Windows that usually means:

    .\\.venv\\Scripts\\python.exe scripts\\count_mcp_tools.py
"""
from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if (REPO_ROOT / "openlmlib" / "mcp_server.py").exists():
    sys.path.insert(0, str(REPO_ROOT))


EXPECTED_CORE = {
    "init_library",
    "save_finding",
    "list_findings",
    "get_finding",
    "search_findings",
    "retrieve_findings",
    "search_knowledge",
    "retrieve_context",
    "delete_finding",
    "health",
    "evaluate_retrieval",
    "start_research",
    "end_session",
    "check_context",
    "save_finding_auto",
    "get_usage_analytics",
    "help_library",
}

EXPECTED_MEMORY = {
    "session_start",
    "session_end",
    "log_observation",
    "query_memory",
    "search_memory",
    "memory_timeline",
    "get_observations",
    "inject_context",
    "session_recap",
    "topic_context",
    "ingest_git_history",
}

EXPECTED_COLLAB = {
    "create_session",
    "join_session",
    "list_sessions",
    "get_session_state",
    "update_session_state",
    "send_message",
    "read_messages",
    "poll_messages",
    "tail_messages",
    "read_message_range",
    "grep_messages",
    "session_context",
    "save_artifact",
    "list_artifacts",
    "get_artifact",
    "grep_artifacts",
    "leave_session",
    "terminate_session",
    "export_to_library",
    "list_templates",
    "get_template",
    "create_from_template",
    "get_agent_sessions",
    "sessions_summary",
    "search_sessions",
    "session_relationships",
    "session_statistics",
    "list_models",
    "get_model_details",
    "recommended_models",
    "get_co_scientist_scope_policy",
    "screen_co_scientist_scope",
    "get_hypothesis_packet_schema",
    "get_evidence_quality_rubric",
    "verify_co_scientist_citations",
    "validate_hypothesis_packet",
    "create_co_scientist_run",
    "submit_hypothesis",
    "list_hypotheses",
    "start_hypothesis_verification",
    "submit_verification",
    "get_co_scientist_report",
    "create_co_scientist_final_report",
    "export_co_scientist_findings",
    "evaluate_co_scientist_run",
    "get_co_scientist_benchmark_tasks",
    "compare_co_scientist_workflows",
    "help_collab",
}

EXPECTED_ALL = EXPECTED_CORE | EXPECTED_MEMORY | EXPECTED_COLLAB


def _print_group(label: str, expected: set[str], found: set[str]) -> None:
    present = sorted(expected & found)
    missing = sorted(expected - found)
    print(f"{label}: {len(present)}/{len(expected)}")
    if missing:
        print(f"  Missing {label.lower()} tools:")
        for name in missing:
            print(f"    - {name}")


def main() -> int:
    try:
        from openlmlib.mcp_server import (
            mcp,
            _register_collab_tools,
            _register_memory_tools,
        )

        _register_memory_tools()
        _register_collab_tools()
        import openlmlib
    except ImportError as exc:
        print("ERROR: failed to import openlmlib.mcp_server")
        print(f"  {exc}")
        print("Use the same Python executable that your MCP config points to.")
        return 1
    except Exception as exc:
        print(f"ERROR: failed to register MCP tools: {exc}")
        return 1

    found = set(mcp._tool_manager._tools)
    missing = sorted(EXPECTED_ALL - found)
    extra = sorted(found - EXPECTED_ALL)

    print(f"OpenLMlib import: {openlmlib.__file__}")
    print(f"Total MCP tools: {len(found)}")
    print(f"Expected minimum: {len(EXPECTED_ALL)}")
    _print_group("Core tools", EXPECTED_CORE, found)
    _print_group("Memory tools", EXPECTED_MEMORY, found)
    _print_group("Collab tools", EXPECTED_COLLAB, found)

    if extra:
        print("Extra registered tools not in this checker:")
        for name in extra:
            print(f"  - {name}")

    if missing:
        print("FAIL: one or more expected MCP tools are missing.")
        return 1

    print("OK: all expected MCP tools are registered.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
