"""Export bridge: CollabSessions → OpenLMLib main library.

Transfers completed session artifacts as findings in the main library,
preserving provenance, tags, and session context.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from ..library import add_finding
from .db import get_session, get_session_artifacts
from .artifact_store import ArtifactStore


def export_session_to_library(
    settings_path: Path,
    session_id: str,
    collab_conn,
    sessions_dir: Path,
    project: Optional[str] = None,
    confidence: float = 0.8,
    tags: Optional[List[str]] = None,
    artifact_ids: Optional[List[str]] = None,
) -> Dict:
    """Export session artifacts as findings in the main OpenLMLib library.

    Args:
        settings_path: Path to OpenLMLib settings file
        session_id: Session to export from
        collab_conn: SQLite connection to collab database
        sessions_dir: Sessions directory path
        project: Project name for findings (defaults to session title)
        confidence: Default confidence score for exported findings
        tags: Additional tags to apply to all exported findings
        artifact_ids: Specific artifacts to export (None = all)

    Returns:
        Dict with export results
    """
    session = get_session(collab_conn, session_id)
    if session is None:
        return {"error": f"Session {session_id} not found", "exported": 0}

    store = ArtifactStore(collab_conn, sessions_dir)
    artifacts = store.list_artifacts(session_id)

    if artifact_ids:
        artifacts = [a for a in artifacts if a["artifact_id"] in artifact_ids]

    if not artifacts:
        return {"error": "No artifacts to export", "exported": 0}

    exported = []
    failed = []
    base_tags = tags or []
    session_tags = [f"session:{session_id}", "collab_session"]
    project_name = project or session.get("title", "collab_research")

    for artifact in artifacts:
        content = store.get_content_by_id(session_id, artifact["artifact_id"])
        if content is None:
            failed.append({
                "artifact_id": artifact["artifact_id"],
                "reason": "Content file not found",
            })
            continue

        art_tags = list(set(
            base_tags + session_tags + (artifact.get("tags") or [])
        ))

        try:
            result = add_finding(
                settings_path=settings_path,
                project=project_name,
                claim=artifact["title"],
                confidence=confidence,
                evidence=[content],
                reasoning=f"Generated in collaboration session '{session['title']}'. "
                          f"Created by {artifact['created_by']}.",
                tags=art_tags,
                proposed_by=artifact["created_by"],
                confirm=True,
            )
            if result.get("status") == "ok":
                exported.append({
                    "artifact_id": artifact["artifact_id"],
                    "finding_id": result.get("id"),
                    "title": artifact["title"],
                })
            else:
                failed.append({
                    "artifact_id": artifact["artifact_id"],
                    "reason": result.get("error", "Unknown error"),
                })
        except Exception as e:
            failed.append({
                "artifact_id": artifact["artifact_id"],
                "reason": str(e),
            })

    return {
        "session_id": session_id,
        "session_title": session["title"],
        "project": project_name,
        "exported": len(exported),
        "failed": len(failed),
        "findings": exported,
        "failures": failed,
    }


def export_session_summary_as_finding(
    settings_path: Path,
    session_id: str,
    collab_conn,
    sessions_dir: Path,
    project: Optional[str] = None,
) -> Dict:
    """Export the session summary as a single finding.

    Args:
        settings_path: Path to OpenLMLib settings file
        session_id: Session to export
        collab_conn: SQLite connection to collab database
        sessions_dir: Sessions directory path
        project: Project name (defaults to session title)

    Returns:
        Dict with export result
    """
    session = get_session(collab_conn, session_id)
    if session is None:
        return {"error": f"Session {session_id} not found"}

    store = ArtifactStore(collab_conn, sessions_dir)
    summary = store.get_latest_summary(session_id)
    if summary is None:
        return {"error": "No session summary available"}

    project_name = project or session.get("title", "collab_research")

    try:
        result = add_finding(
            settings_path=settings_path,
            project=project_name,
            claim=f"Session Summary: {session['title']}",
            confidence=0.9,
            evidence=[summary],
            reasoning=f"Complete summary of collaboration session '{session['title']}'.",
            tags=["collab_session", f"session:{session_id}", "summary"],
            proposed_by=session.get("orchestrator", "unknown"),
            confirm=True,
        )
        if result.get("status") == "ok":
            return {
                "exported": True,
                "finding_id": result.get("id"),
                "title": f"Session Summary: {session['title']}",
            }
        return {"error": result.get("error", "Unknown error")}
    except Exception as e:
        return {"error": str(e)}
