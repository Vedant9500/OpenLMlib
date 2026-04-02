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


def _settings_path() -> Path:
    value = os.environ.get("OPENLMLIB_SETTINGS")
    if value:
        return Path(value)
    from .settings import resolve_global_settings_path
    return resolve_global_settings_path()


mcp = FastMCP("OpenLMlib")


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
    mcp.run()


if __name__ == "__main__":
    main()
