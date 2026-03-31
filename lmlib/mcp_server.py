from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from mcp.server.fastmcp import FastMCP

from .library import (
    add_finding,
    delete_finding,
    get_finding,
    health,
    init_library,
    list_findings,
    search_fts,
)


def _settings_path() -> Path:
    value = os.environ.get("LMLIB_SETTINGS", "config/settings.json")
    return Path(value)


mcp = FastMCP("LMlib")


@mcp.tool()
def lmlib_init() -> dict:
    """Initialize database, data directories, and vector index."""
    return init_library(_settings_path())


@mcp.tool()
def lmlib_add_finding(
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
    """Add a finding to LMlib. Requires confirm=true for writes."""
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
def lmlib_list_findings(limit: int = 50, offset: int = 0) -> dict:
    """List findings in LMlib."""
    return list_findings(_settings_path(), limit=limit, offset=offset)


@mcp.tool()
def lmlib_get_finding(finding_id: str) -> dict:
    """Get a finding by id."""
    return get_finding(_settings_path(), finding_id)


@mcp.tool()
def lmlib_search_fts(query: str, limit: int = 10) -> dict:
    """Search findings using SQLite FTS5."""
    return search_fts(_settings_path(), query, limit=limit)


@mcp.tool()
def lmlib_delete_finding(finding_id: str, confirm: bool = False) -> dict:
    """Delete a finding by id. Requires confirm=true for writes."""
    return delete_finding(_settings_path(), finding_id, confirm=confirm)


@mcp.tool()
def lmlib_health() -> dict:
    """Return database and vector index health info."""
    return health(_settings_path())


if __name__ == "__main__":
    mcp.run()
