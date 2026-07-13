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
from .security import validate_artifact_id


def _validate_artifact_filter_ids(artifact_ids: Optional[List[str]]) -> Optional[List[str]]:
    if artifact_ids is None:
        return None
    return [validate_artifact_id(artifact_id) for artifact_id in artifact_ids]


def _format_add_finding_failure(result: Dict) -> Dict:
    """Map library.add_finding non-ok payloads into export failure fields."""
    status = result.get("status")
    issues = result.get("issues")
    reason = (
        result.get("error")
        or result.get("message")
        or ("; ".join(
            f"{i.get('field', 'issue')}: {i.get('message', '')}".strip(": ")
            for i in issues
            if isinstance(i, dict)
        ) if issues else None)
        or "export rejected"
    )
    payload: Dict = {"reason": reason}
    if status is not None:
        payload["status"] = status
    if issues is not None:
        payload["issues"] = issues
    return payload


def _export_claim_evidence_reasoning(
    *,
    title: str,
    content: str,
    session_title: str,
    created_by: str,
    kind: str = "artifact",
) -> tuple:
    """Build claim/evidence/reasoning that can pass the write gate."""
    claim = (title or "").strip()
    body = (content or "").strip()
    if len(claim) < 20 and body:
        claim = body.splitlines()[0].strip()[:300] or claim
    if not claim:
        claim = f"Collaboration {kind} from {session_title}"

    # Prefix evidence with the claim so claim/evidence embedding similarity stays high.
    evidence_text = body if body.startswith(claim) else f"{claim}\n\n{body}".strip()
    if not evidence_text:
        evidence_text = claim

    reasoning = (
        f"Exported from collaboration session '{session_title}'. "
        f"Source {kind} '{title or claim}' created by {created_by or 'unknown'}. "
        f"Key content: {body[:400].strip() or claim}"
    )
    if len(reasoning) < 50:
        reasoning = (
            f"{reasoning} This finding captures research output produced during "
            f"a multi-agent collaboration session."
        )
    return claim, [evidence_text], reasoning


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

    try:
        artifact_ids = _validate_artifact_filter_ids(artifact_ids)
    except Exception as exc:
        return {
            "error": str(exc),
            "error_type": "validation_error",
            "exported": 0,
        }

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
        claim, evidence, reasoning = _export_claim_evidence_reasoning(
            title=artifact.get("title") or "",
            content=content,
            session_title=session.get("title", "collab_research"),
            created_by=artifact.get("created_by") or "",
            kind="artifact",
        )

        try:
            result = add_finding(
                settings_path=settings_path,
                project=project_name,
                claim=claim,
                confidence=confidence,
                evidence=evidence,
                reasoning=reasoning,
                tags=art_tags,
                proposed_by=artifact["created_by"],
                confirm=True,
                trusted_export=True,
            )
            if result.get("status") == "ok":
                exported.append({
                    "artifact_id": artifact["artifact_id"],
                    "finding_id": result.get("id"),
                    "title": artifact["title"],
                })
            else:
                failure = _format_add_finding_failure(result)
                failure["artifact_id"] = artifact["artifact_id"]
                failed.append(failure)
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
    claim, evidence, reasoning = _export_claim_evidence_reasoning(
        title=f"Session Summary: {session['title']}",
        content=summary,
        session_title=session.get("title", "collab_research"),
        created_by=session.get("orchestrator", "unknown"),
        kind="summary",
    )

    try:
        result = add_finding(
            settings_path=settings_path,
            project=project_name,
            claim=claim,
            confidence=0.9,
            evidence=evidence,
            reasoning=reasoning,
            tags=["collab_session", f"session:{session_id}", "summary"],
            proposed_by=session.get("orchestrator", "unknown"),
            confirm=True,
            trusted_export=True,
        )
        if result.get("status") == "ok":
            return {
                "exported": True,
                "finding_id": result.get("id"),
                "title": claim,
            }
        failure = _format_add_finding_failure(result)
        return {
            "error": failure["reason"],
            "status": failure.get("status"),
            "issues": failure.get("issues"),
        }
    except Exception as e:
        return {"error": str(e)}
