"""Session lifecycle operations for CollabSessions.

High-level functions that orchestrate DB operations, file system
setup, message bus, and context compilation for session creation,
joining, leaving, and termination.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import sqlite3

from . import db
from .message_bus import MessageBus
from .artifact_store import ArtifactStore
from .state_manager import StateManager
from .context_compiler import ContextCompiler
from .errors import (
    AgentNotFoundError,
    SessionFullError,
    SessionNotActiveError,
    SessionNotFoundError,
)

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_session_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d")
    short = uuid.uuid4().hex[:8]
    return f"sess_{ts}_{short}"


def _generate_agent_id(model: str) -> str:
    short = uuid.uuid4().hex[:6]
    model_short = model.replace(" ", "-").replace("/", "-")[:20]
    return f"agent_{model_short}_{short}"


def _ensure_session_dirs(sessions_dir: Path, session_id: str) -> None:
    """Create all required directories for a session."""
    base = sessions_dir / session_id
    (base / "artifacts" / "shared").mkdir(parents=True, exist_ok=True)
    (base / "summaries").mkdir(parents=True, exist_ok=True)
    (base / "offsets").mkdir(parents=True, exist_ok=True)


def create_collab_session(
    conn: sqlite3.Connection,
    sessions_dir: Path,
    title: str,
    created_by: str,
    description: Optional[str] = None,
    plan: Optional[List[Dict]] = None,
    rules: Optional[Dict] = None,
    created_at: Optional[str] = None,
) -> Dict:
    """Create a new collaboration session.

    Args:
        conn: SQLite connection
        sessions_dir: Base directory for session files
        title: Session title
        created_by: Creator identifier (model name or agent ID)
        description: Optional session description
        plan: Optional list of task dicts with 'step', 'task', 'assigned_to'
        rules: Optional session rules dict
        created_at: Optional ISO timestamp (defaults to now)

    Returns:
        Dict with session_id, title, status, orchestrator, created_at
    """
    created_at = created_at or _now_iso()
    session_id = _generate_session_id()

    _ensure_session_dirs(sessions_dir, session_id)

    session_info = db.create_session(
        conn,
        session_id=session_id,
        title=title,
        created_by=created_by,
        created_at=created_at,
        description=description,
        orchestrator=created_by,
        rules=rules,
    )

    agent_id = _generate_agent_id(created_by)
    db.insert_agent(
        conn,
        agent_id=agent_id,
        session_id=session_id,
        model=created_by,
        role="orchestrator",
        joined_at=created_at,
        capabilities=["planning", "synthesis", "delegation"],
    )

    bus = MessageBus(conn, sessions_dir)
    bus.send(
        session_id=session_id,
        from_agent=agent_id,
        msg_type="system",
        content=f"Session created: {title}",
        created_at=created_at,
        metadata={"title": title, "description": description},
    )

    if plan:
        for step in plan:
            task_id = f"task_{uuid.uuid4().hex[:6]}"
            db.insert_task(
                conn,
                task_id=task_id,
                session_id=session_id,
                step_num=step.get("step", 0),
                description=step.get("task", ""),
                created_at=created_at,
                assigned_to=step.get("assigned_to"),
            )
            bus.send(
                session_id=session_id,
                from_agent=agent_id,
                msg_type="system",
                content=f"Task created: Step {step.get('step', '?')}: {step.get('task', '')}",
                created_at=created_at,
                metadata={"task_id": task_id, "step": step.get("step")},
            )

    return {
        **session_info,
        "agent_id": agent_id,
        "sessions_dir": str(sessions_dir / session_id),
    }


def join_collab_session(
    conn: sqlite3.Connection,
    sessions_dir: Path,
    session_id: str,
    model: str,
    role: str = "worker",
    capabilities: Optional[List[str]] = None,
    joined_at: Optional[str] = None,
) -> Dict:
    """Join an existing collaboration session.

    Args:
        conn: SQLite connection
        sessions_dir: Base directory for session files
        session_id: Session to join
        model: Model identifier
        role: Agent role (worker, observer)
        capabilities: Optional list of capabilities
        joined_at: Optional ISO timestamp

    Returns:
        Dict with agent_id, session info, and instructions
    """
    session = db.get_session(conn, session_id)
    if session is None:
        raise SessionNotFoundError(f"Session {session_id} not found")
    if session["status"] != "active":
        raise SessionNotActiveError(
            f"Session {session_id} is not active (status: {session['status']})"
        )

    rules = session.get("rules", {})
    max_agents = rules.get("max_agents", 10)
    current_agents = len(db.get_session_agents(conn, session_id))
    if current_agents >= max_agents:
        raise SessionFullError(
            f"Session is full ({current_agents}/{max_agents} agents)"
        )

    joined_at = joined_at or _now_iso()
    agent_id = _generate_agent_id(model)

    _ensure_session_dirs(sessions_dir, session_id)

    db.insert_agent(
        conn,
        agent_id=agent_id,
        session_id=session_id,
        model=model,
        role=role,
        joined_at=joined_at,
        capabilities=capabilities,
    )

    bus = MessageBus(conn, sessions_dir)
    bus.send(
        session_id=session_id,
        from_agent=agent_id,
        msg_type="system",
        content=f"Agent joined: {agent_id} ({model}) as {role}",
        created_at=joined_at,
        metadata={"agent_id": agent_id, "model": model, "role": role},
    )

    return {
        "agent_id": agent_id,
        "session_id": session_id,
        "session_title": session["title"],
        "role": role,
        "joined_at": joined_at,
        "sessions_dir": str(sessions_dir / session_id),
    }


def leave_collab_session(
    conn: sqlite3.Connection,
    sessions_dir: Path,
    agent_id: str,
    reason: Optional[str] = None,
    left_at: Optional[str] = None,
) -> bool:
    """Leave a collaboration session gracefully.

    Args:
        conn: SQLite connection
        sessions_dir: Base directory for session files
        agent_id: Agent leaving the session
        reason: Optional reason for leaving
        left_at: Optional ISO timestamp

    Returns:
        True if successfully left
    """
    left_at = left_at or _now_iso()

    agents = conn.execute(
        "SELECT session_id, model, role FROM agents WHERE agent_id = ?",
        (agent_id,),
    ).fetchone()
    if agents is None:
        raise AgentNotFoundError(f"Agent {agent_id} not found")

    session_id = agents["session_id"]
    model = agents["model"]

    db.update_agent_status(conn, agent_id, "left", left_at)

    bus = MessageBus(conn, sessions_dir)
    reason_str = f" (reason: {reason})" if reason else ""
    bus.send(
        session_id=session_id,
        from_agent=agent_id,
        msg_type="system",
        content=f"Agent left: {agent_id} ({model}){reason_str}",
        created_at=left_at,
        metadata={"agent_id": agent_id, "reason": reason},
    )

    return True


def terminate_collab_session(
    conn: sqlite3.Connection,
    sessions_dir: Path,
    session_id: str,
    summary: Optional[str] = None,
    terminated_at: Optional[str] = None,
) -> Dict:
    """Terminate a collaboration session.

    Args:
        conn: SQLite connection
        sessions_dir: Base directory for session files
        session_id: Session to terminate
        summary: Optional final summary text
        terminated_at: Optional ISO timestamp

    Returns:
        Dict with termination info
    """
    session = db.get_session(conn, session_id)
    if session is None:
        raise SessionNotFoundError(f"Session {session_id} not found")

    terminated_at = terminated_at or _now_iso()

    if not db.update_session_status(conn, session_id, "completed", terminated_at):
        raise SessionNotActiveError(
            f"Session {session_id} cannot be terminated (status: {session['status']})"
        )

    bus = MessageBus(conn, sessions_dir)
    orchestrator = session["orchestrator"]

    if summary:
        artifact_store = ArtifactStore(conn, sessions_dir)
        artifact_store.save_summary(session_id, summary, terminated_at)

    bus.send(
        session_id=session_id,
        from_agent=orchestrator,
        msg_type="system",
        content=f"Session completed: {session['title']}",
        created_at=terminated_at,
        metadata={"summary": summary},
    )

    db.update_agent_status(conn, orchestrator, "left", terminated_at)

    other_agents = db.get_session_agents(conn, session_id)
    for agent in other_agents:
        if agent["status"] == "active":
            db.update_agent_status(conn, agent["agent_id"], "inactive", terminated_at)

    return {
        "session_id": session_id,
        "status": "completed",
        "terminated_at": terminated_at,
        "summary_saved": bool(summary),
    }
