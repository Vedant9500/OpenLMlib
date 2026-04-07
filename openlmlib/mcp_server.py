from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from mcp.server.fastmcp import FastMCP

from .library import (
    add_finding,
    delete_finding,
    evaluate_dataset,
    get_finding,
    health,
    init_library,
    list_findings,
    retrieve_findings,
    retrieve_prompt_context,
    search_fts,
)
from .runtime import get_runtime


def _settings_path() -> Path:
    value = os.environ.get("OPENLMLIB_SETTINGS")
    if value:
        return Path(value)
    from .settings import resolve_global_settings_path
    return resolve_global_settings_path()


mcp = FastMCP("OpenLMlib")

from .collab.collab_mcp import (
    collab_add_artifact,
    collab_create_session,
    collab_create_session_from_template,
    collab_export_to_library,
    collab_get_active_sessions_summary,
    collab_get_agent_sessions,
    collab_get_artifact,
    collab_get_openrouter_model_details,
    collab_get_recommended_models,
    collab_get_session_context,
    collab_get_session_relationships,
    collab_get_session_state,
    collab_get_session_statistics,
    collab_get_template,
    collab_grep_artifacts,
    collab_grep_messages,
    collab_help as collab_help,
    collab_join_session,
    collab_leave_session,
    collab_list_artifacts,
    collab_list_openrouter_models,
    collab_list_sessions,
    collab_list_templates,
    collab_read_message_range,
    collab_read_messages,
    collab_search_sessions,
    collab_send_message,
    collab_tail_messages,
    collab_terminate_session,
    collab_update_session_state,
)

mcp.tool()(collab_create_session)
mcp.tool()(collab_join_session)
mcp.tool()(collab_list_sessions)
mcp.tool()(collab_get_session_state)
mcp.tool()(collab_update_session_state)
mcp.tool()(collab_send_message)
mcp.tool()(collab_read_messages)
mcp.tool()(collab_tail_messages)
mcp.tool()(collab_read_message_range)
mcp.tool()(collab_grep_messages)
mcp.tool()(collab_get_session_context)
mcp.tool()(collab_add_artifact)
mcp.tool()(collab_list_artifacts)
mcp.tool()(collab_get_artifact)
mcp.tool()(collab_grep_artifacts)
mcp.tool()(collab_leave_session)
mcp.tool()(collab_terminate_session)
mcp.tool()(collab_export_to_library)
mcp.tool()(collab_list_templates)
mcp.tool()(collab_get_template)
mcp.tool()(collab_create_session_from_template)
mcp.tool()(collab_get_agent_sessions)
mcp.tool()(collab_get_active_sessions_summary)
mcp.tool()(collab_search_sessions)
mcp.tool()(collab_get_session_relationships)
mcp.tool()(collab_get_session_statistics)
mcp.tool()(collab_list_openrouter_models)
mcp.tool()(collab_get_openrouter_model_details)
mcp.tool()(collab_get_recommended_models)
mcp.tool()(collab_help)


def _ensure_runtime() -> None:
    """Pre-initialize the runtime so the first tool call isn't slow.

    This loads the embedding model, connects to the database, and warms
    up the vector store before any MCP tool is invoked.
    """
    try:
        get_runtime(_settings_path())
    except Exception:
        # If initialization fails, let individual tools handle it.
        pass


@mcp.tool()
def openlmlib_init() -> dict:
    """Initialize database, data directories, and vector index."""
    return init_library(_settings_path())


@mcp.tool()
def openlmlib_add_finding(
    project: str,
    claim: str,
    confidence: float,
    evidence: Optional[List[str]] = None,
    reasoning: str = "",
    caveats: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
    full_text: str = "",
    proposed_by: str = "",
    finding_id: Optional[str] = None,
    confirm: bool = False,
) -> dict:
    """Add a finding to OpenLMlib. Requires confirm=true for writes."""
    return add_finding(
        settings_path=_settings_path(),
        project=project,
        claim=claim,
        confidence=confidence,
        evidence=evidence,
        reasoning=reasoning,
        caveats=caveats,
        tags=tags,
        full_text=full_text,
        proposed_by=proposed_by,
        finding_id=finding_id,
        confirm=confirm,
    )


@mcp.tool()
def openlmlib_list_findings(limit: int = 50, offset: int = 0) -> dict:
    """List findings in OpenLMlib."""
    return list_findings(_settings_path(), limit=limit, offset=offset)


@mcp.tool()
def openlmlib_get_finding(finding_id: str) -> dict:
    """Get a finding by id."""
    return get_finding(_settings_path(), finding_id)


@mcp.tool()
def openlmlib_search_fts(query: str, limit: int = 10) -> dict:
    """Search findings using SQLite FTS5."""
    return search_fts(_settings_path(), query, limit=limit)


@mcp.tool()
def openlmlib_retrieve(
    query: str,
    project: Optional[str] = None,
    tags: Optional[List[str]] = None,
    created_after: Optional[str] = None,
    created_before: Optional[str] = None,
    confidence_min: Optional[float] = None,
    semantic_k: Optional[int] = None,
    lexical_k: Optional[int] = None,
    final_k: Optional[int] = None,
) -> dict:
    """Run dual-index retrieval (semantic + lexical) with optional filters."""
    return retrieve_findings(
        settings_path=_settings_path(),
        query=query,
        project=project,
        tags=tags,
        created_after=created_after,
        created_before=created_before,
        confidence_min=confidence_min,
        semantic_k=semantic_k,
        lexical_k=lexical_k,
        final_k=final_k,
    )


@mcp.tool()
def openlmlib_retrieve_context(
    query: str,
    project: Optional[str] = None,
    tags: Optional[List[str]] = None,
    confidence_min: Optional[float] = None,
    final_k: Optional[int] = None,
) -> dict:
    """Retrieve findings and return sanitized untrusted context block for LLM prompts."""
    return retrieve_prompt_context(
        settings_path=_settings_path(),
        query=query,
        project=project,
        tags=tags,
        confidence_min=confidence_min,
        final_k=final_k,
    )


@mcp.tool()
def openlmlib_delete_finding(finding_id: str, confirm: bool = False) -> dict:
    """Delete a finding by id. Requires confirm=true for writes."""
    return delete_finding(_settings_path(), finding_id, confirm=confirm)


@mcp.tool()
def openlmlib_health() -> dict:
    """Return database and vector index health info."""
    return health(_settings_path())


@mcp.tool()
def openlmlib_evaluate_dataset(dataset_path: str = "config/eval_queries.json", final_k: int = 10) -> dict:
    """Run retrieval evaluation metrics on a local dataset file."""
    return evaluate_dataset(
        settings_path=_settings_path(),
        dataset_path=Path(dataset_path),
        final_k=final_k,
    )


@mcp.tool()
def openlmlib_help(tool_name: Optional[str] = None) -> dict:
    """Get help about all OpenLMlib MCP tools or a specific tool.

    Call this with no arguments to see all available tools organized by category.
    Call with a specific tool_name to get detailed usage instructions.

    Args:
        tool_name: Optional specific tool name to get help for
                   (e.g., 'openlmlib_add_finding', 'collab_create_session')

    Returns:
        Dict with tool descriptions and usage information
    """
    core_tools = {
        "openlmlib_init": {
            "description": "Initialize database, data directories, and vector index.",
            "args": {},
            "returns": "Dict with initialization status",
        },
        "openlmlib_add_finding": {
            "description": "Add a finding to OpenLMLib.",
            "args": {
                "project": "Project name",
                "claim": "The claim/finding text",
                "confidence": "Confidence score (0.0-1.0)",
                "evidence": "Optional list of evidence strings",
                "reasoning": "Reasoning behind the finding",
                "caveats": "Optional list of caveats",
                "tags": "Optional tags for categorization",
                "full_text": "Full text of the finding",
                "proposed_by": "Who proposed this finding",
                "finding_id": "Optional specific finding ID",
                "confirm": "Must be True for writes (safety)",
            },
            "returns": "Dict with finding info",
        },
        "openlmlib_list_findings": {
            "description": "List findings in OpenLMLib.",
            "args": {
                "limit": "Max findings to return (default: 50)",
                "offset": "Offset for pagination (default: 0)",
            },
            "returns": "Dict with list of findings",
        },
        "openlmlib_get_finding": {
            "description": "Get a finding by id.",
            "args": {
                "finding_id": "ID of the finding to retrieve",
            },
            "returns": "Dict with finding details",
        },
        "openlmlib_search_fts": {
            "description": "Search findings using SQLite FTS5 full-text search.",
            "args": {
                "query": "Search query",
                "limit": "Max results (default: 10)",
            },
            "returns": "Dict with matching findings",
        },
        "openlmlib_retrieve": {
            "description": "Run dual-index retrieval (semantic + lexical) with optional filters.",
            "args": {
                "query": "Search query",
                "project": "Filter by project (optional)",
                "tags": "Filter by tags (optional)",
                "created_after": "Filter by creation date (optional)",
                "created_before": "Filter by creation date (optional)",
                "confidence_min": "Minimum confidence score (optional)",
                "semantic_k": "Number of semantic results (optional)",
                "lexical_k": "Number of lexical results (optional)",
                "final_k": "Final number of results (optional)",
            },
            "returns": "Dict with retrieved findings",
        },
        "openlmlib_retrieve_context": {
            "description": "Retrieve findings and return sanitized untrusted context block for LLM prompts.",
            "args": {
                "query": "Search query",
                "project": "Filter by project (optional)",
                "tags": "Filter by tags (optional)",
                "confidence_min": "Minimum confidence score (optional)",
                "final_k": "Final number of results (optional)",
            },
            "returns": "Dict with sanitized context",
        },
        "openlmlib_delete_finding": {
            "description": "Delete a finding by id.",
            "args": {
                "finding_id": "ID of the finding to delete",
                "confirm": "Must be True for writes (safety)",
            },
            "returns": "Dict with deletion status",
        },
        "openlmlib_health": {
            "description": "Return database and vector index health info.",
            "args": {},
            "returns": "Dict with health status",
        },
        "openlmlib_evaluate_dataset": {
            "description": "Run retrieval evaluation metrics on a local dataset file.",
            "args": {
                "dataset_path": "Path to dataset file (default: 'config/eval_queries.json')",
                "final_k": "Final number of results (default: 10)",
            },
            "returns": "Dict with evaluation metrics",
        },
    }

    collab_tools_summary = {
        "collab_create_session": "Create a new collaboration session for multi-agent research.",
        "collab_join_session": "Join an existing collaboration session.",
        "collab_list_sessions": "List collaboration sessions.",
        "collab_get_session_state": "Get the current state of a collaboration session for a joined agent.",
        "collab_update_session_state": "Update the session state (orchestrator only).",
        "collab_send_message": "Send a message to a collaboration session.",
        "collab_read_messages": "Read new messages from a joined session (offset-based).",
        "collab_tail_messages": "Read the last N messages from a joined session (quick status check).",
        "collab_read_message_range": "Read messages in a specific sequence range from a joined session.",
        "collab_grep_messages": "Search messages in a joined session by keyword.",
        "collab_get_session_context": "Get a compiled context view of the session (PRIMARY tool for understanding session state).",
        "collab_add_artifact": "Save a research artifact (finding, analysis, summary) to the session.",
        "collab_list_artifacts": "List artifacts in a joined session.",
        "collab_get_artifact": "Get the full content of a specific artifact from a joined session.",
        "collab_grep_artifacts": "Search artifact content in a joined session by keyword.",
        "collab_leave_session": "Leave a collaboration session gracefully.",
        "collab_terminate_session": "Terminate and complete a collaboration session (orchestrator only).",
        "collab_export_to_library": "Export session artifacts as findings in the main OpenLMLib library.",
        "collab_list_templates": "List available session templates for quick session creation.",
        "collab_get_template": "Get details of a specific session template.",
        "collab_create_session_from_template": "Create a session from a predefined template.",
        "collab_get_agent_sessions": "Get all sessions the requesting agent has participated in.",
        "collab_get_active_sessions_summary": "Get a summary of active sessions joined by the requesting agent.",
        "collab_search_sessions": "Search joined sessions by message content using FTS5.",
        "collab_get_session_relationships": "Find sessions related to a joined session.",
        "collab_get_session_statistics": "Get detailed statistics for a joined session.",
        "collab_list_openrouter_models": "List available models from OpenRouter API.",
        "collab_get_openrouter_model_details": "Get detailed information about a specific OpenRouter model.",
        "collab_get_recommended_models": "Get recommended OpenRouter models for a specific task type.",
        "collab_help": "Get help about collab MCP tools.",
    }

    if tool_name:
        if tool_name in core_tools:
            return {"tool": tool_name, **core_tools[tool_name]}
        elif tool_name in collab_tools_summary:
            return {
                "tool": tool_name,
                "description": collab_tools_summary[tool_name],
                "note": f"Use collab_help(tool_name='{tool_name}') for detailed usage information",
            }
        else:
            return {
                "error": f"Tool '{tool_name}' not found",
                "available_core_tools": sorted(core_tools.keys()),
                "available_collab_tools": sorted(collab_tools_summary.keys()),
            }

    return {
        "description": "OpenLMlib MCP Server - Knowledge management and multi-agent collaboration tools",
        "categories": {
            "Core Library Tools": {
                "description": "Manage findings in the OpenLMLib knowledge base",
                "tools": {name: info["description"] for name, info in core_tools.items()},
            },
            "CollabSession Tools": {
                "description": "Multi-agent collaboration session management (30 tools)",
                "summary": collab_tools_summary,
                "note": "Use collab_help() for detailed collab tool documentation",
            },
        },
        "usage": [
            "Call openlmlib_help(tool_name='<tool>') for detailed usage of a core tool",
            "Call collab_help(tool_name='<tool>') for detailed usage of a collab tool",
        ],
    }


def main() -> None:
    import argparse
    import sys
    
    parser = argparse.ArgumentParser(description="OpenLMlib MCP Server", add_help=False)
    parser.add_argument("--dir", type=str, help="Base directory of the OpenLMlib project")
    parser.add_argument("--settings", type=str, help="Absolute path to settings.json")
    
    args, unknown = parser.parse_known_args()
    
    if args.settings:
        os.environ["OPENLMLIB_SETTINGS"] = args.settings
    elif args.dir:
        os.environ["OPENLMLIB_SETTINGS"] = str(Path(args.dir) / "config" / "settings.json")
        
    sys.argv = [sys.argv[0]] + unknown

    # Pre-warm the runtime before the MCP server starts accepting tool calls.
    # This ensures the embedding model is loaded and ready, avoiding a cold
    # start penalty on the first user request.
    _ensure_runtime()

    mcp.run()


if __name__ == "__main__":
    main()
