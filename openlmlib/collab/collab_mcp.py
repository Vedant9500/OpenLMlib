"""MCP tools for CollabSessions.

Exposes collaboration session operations to any MCP-compatible LLM agent.
All tools include:
- Comprehensive error handling with structured error responses
- Input validation and security checks
- Logging of operations and errors
- Database connection lifecycle management
"""

from __future__ import annotations

import logging
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from .db import connect_collab_db, init_collab_db
from .session import (
    create_collab_session,
    join_collab_session,
    leave_collab_session,
    terminate_collab_session,
)
from .message_bus import MessageBus
from .artifact_store import ArtifactStore
from .state_manager import StateManager
from .context_compiler import ContextCompiler
from . import db as collab_db
from .errors import (
    AgentNotAuthorizedError,
    AgentNotFoundError,
    ArtifactNotFoundError,
    CollabError,
    DatabaseError,
    FilesystemError,
    InvalidMessageTypeError,
    MessageTooLongError,
    SecurityError,
    SessionFullError,
    SessionNotActiveError,
    SessionNotFoundError,
    StateConflictError,
    TemplateNotFoundError,
    error_from_exception,
)
from .security import (
    sanitize_content,
    validate_agent_id,
    validate_artifact_id,
    validate_message_content,
    validate_message_type,
    validate_safe_path,
    validate_session_id,
    verify_agent_in_session,
    verify_orchestrator,
    verify_session_exists_and_active,
)

logger = logging.getLogger(__name__)


def _get_collab_paths() -> tuple[Path, Path]:
    """Get the collab DB path and sessions directory from settings."""
    settings_path_str = os.environ.get("OPENLMLIB_SETTINGS")
    if settings_path_str:
        settings_path = Path(settings_path_str)
    else:
        from openlmlib.settings import resolve_global_settings_path
        settings_path = resolve_global_settings_path()

    if settings_path.exists():
        import json
        with open(settings_path) as f:
            cfg = json.load(f)
        data_root = Path(cfg.get("data_root", "data"))
    else:
        data_root = Path("data")

    db_path = data_root / "collab_sessions.db"
    sessions_dir = data_root / "sessions"
    return db_path, sessions_dir


def _get_settings_path() -> Path:
    """Get the OpenLMLib settings path."""
    settings_path_str = os.environ.get("OPENLMLIB_SETTINGS")
    if settings_path_str:
        return Path(settings_path_str)
    from openlmlib.settings import resolve_global_settings_path
    return resolve_global_settings_path()


def _get_collab_connection():
    """Get a connection to the collab database, initializing if needed."""
    db_path, sessions_dir = _get_collab_paths()
    sessions_dir.mkdir(parents=True, exist_ok=True)

    try:
        conn = connect_collab_db(db_path)
    except Exception as e:
        raise DatabaseError(f"Failed to connect to collab database: {e}")

    existing = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'"
    ).fetchone()
    if existing is None:
        try:
            init_collab_db(conn)
            logger.info("Initialized collab database schema at %s", db_path)
        except Exception as e:
            conn.close()
            raise DatabaseError(f"Failed to initialize collab database: {e}")

    return conn, sessions_dir


def _handle_tool_error(func_name: str, exc: Exception) -> Dict:
    """Convert any exception into a structured error response."""
    if isinstance(exc, CollabError):
        error_resp = error_from_exception(exc)
        logger.warning("CollabError in %s: %s", func_name, exc)
        return error_resp
    elif isinstance(exc, (sqlite3.OperationalError, sqlite3.DatabaseError)):
        logger.error("Database error in %s: %s", func_name, exc)
        return {
            "success": False,
            "error": f"Database error: {str(exc)}",
            "error_type": "database_error",
        }
    elif isinstance(exc, (OSError, IOError)):
        logger.error("Filesystem error in %s: %s", func_name, exc)
        return {
            "success": False,
            "error": f"Filesystem error: {str(exc)}",
            "error_type": "filesystem_error",
        }
    else:
        logger.error(
            "Unexpected error in %s: %s\n%s",
            func_name, exc, traceback.format_exc(),
        )
        return {
            "success": False,
            "error": f"Internal error: {str(exc)}",
            "error_type": "internal_error",
        }


import sqlite3

collab_mcp = FastMCP("OpenLMlib CollabSessions")


@collab_mcp.tool()
def collab_create_session(
    title: str,
    task_description: str,
    plan: Optional[List[Dict]] = None,
    rules: Optional[Dict] = None,
    created_by: str = "orchestrator",
) -> Dict:
    """Create a new collaboration session for multi-agent research.

    Args:
        title: Short descriptive title for the session
        task_description: Detailed description of the research task
        plan: Optional list of task dicts, each with keys:
              - step (int): step number
              - task (str): task description
              - assigned_to (str, optional): agent ID or "any"
        rules: Optional session rules dict with keys like:
               - max_agents (int): max agents allowed (default 5)
               - require_assignment (bool): require task assignment
        created_by: Identifier for the creating agent

    Returns:
        Dict with session_id, agent_id, and session info
    """
    try:
        if not title or not isinstance(title, str):
            return {"success": False, "error": "title is required", "error_type": "validation_error"}
        if not task_description or not isinstance(task_description, str):
            return {"success": False, "error": "task_description is required", "error_type": "validation_error"}

        safe_title = sanitize_content(title)
        safe_desc = sanitize_content(task_description)

        conn, sessions_dir = _get_collab_connection()
        try:
            result = create_collab_session(
                conn=conn,
                sessions_dir=sessions_dir,
                title=safe_title,
                created_by=created_by,
                description=safe_desc,
                plan=plan,
                rules=rules,
            )
            logger.info("Session created: %s by %s", result["session_id"], created_by)
            return {
                "success": True,
                "session_id": result["session_id"],
                "your_agent_id": result["agent_id"],
                "title": result["title"],
                "status": result["status"],
                "sessions_dir": result["sessions_dir"],
                "next_steps": [
                    "Use collab_update_session_state to set the initial plan",
                    "Use collab_send_message to assign tasks to agents",
                    "Use collab_read_messages to monitor progress",
                ],
            }
        finally:
            conn.close()
    except Exception as e:
        return _handle_tool_error("collab_create_session", e)


@collab_mcp.tool()
def collab_join_session(
    session_id: str,
    model: str,
    capabilities: Optional[List[str]] = None,
) -> Dict:
    """Join an existing collaboration session.

    Args:
        session_id: ID of the session to join
        model: Your model identifier (e.g., 'gpt-codex', 'gemini-pro')
        capabilities: Optional list of your capabilities
                      (e.g., ['research', 'code_analysis'])

    Returns:
        Dict with your agent_id and session context
    """
    try:
        validate_session_id(session_id)
        if not model or not isinstance(model, str):
            return {"success": False, "error": "model is required", "error_type": "validation_error"}

        conn, sessions_dir = _get_collab_connection()
        try:
            verify_session_exists_and_active(conn, session_id)

            result = join_collab_session(
                conn=conn,
                sessions_dir=sessions_dir,
                session_id=session_id,
                model=model,
                capabilities=capabilities,
            )
            bus = MessageBus(conn, sessions_dir)
            compiler = ContextCompiler(
                conn,
                bus,
                ArtifactStore(conn, sessions_dir),
            )
            context = compiler.compile_context(session_id, result["agent_id"])
            context_str = compiler.format_context_for_prompt(context)

            logger.info("Agent %s joined session %s", result["agent_id"], session_id)
            return {
                "success": True,
                "agent_id": result["agent_id"],
                "session_id": result["session_id"],
                "role": result["role"],
                "session_context": context_str,
                "next_steps": [
                    "Read the session_context above to understand current state",
                    "Use collab_read_messages to check for new messages",
                    "Use collab_send_message to communicate with other agents",
                    "Use collab_add_artifact to save your research outputs",
                ],
            }
        finally:
            conn.close()
    except Exception as e:
        return _handle_tool_error("collab_join_session", e)


@collab_mcp.tool()
def collab_list_sessions(
    status: Optional[str] = None,
    limit: int = 20,
) -> Dict:
    """List collaboration sessions.

    Args:
        status: Filter by status (active, completed, terminated)
        limit: Maximum number of sessions to return

    Returns:
        Dict with list of sessions
    """
    try:
        limit = max(1, min(limit, 100))
        conn, _ = _get_collab_connection()
        try:
            sessions = collab_db.list_sessions(conn, status=status, limit=limit)
            return {
                "sessions": sessions,
                "count": len(sessions),
            }
        finally:
            conn.close()
    except Exception as e:
        return _handle_tool_error("collab_list_sessions", e)


@collab_mcp.tool()
def collab_get_session_state(session_id: str) -> Dict:
    """Get the current state of a collaboration session.

    Args:
        session_id: ID of the session

    Returns:
        Dict with session state, tasks, and agents
    """
    try:
        validate_session_id(session_id)
        conn, sessions_dir = _get_collab_connection()
        try:
            session = collab_db.get_session(conn, session_id)
            if session is None:
                return {"error": f"Session {session_id} not found", "error_type": "session_not_found", "success": False}

            state = collab_db.get_session_state(conn, session_id)
            tasks = collab_db.get_session_tasks(conn, session_id)
            agents = collab_db.get_session_agents(conn, session_id)

            return {
                "session": session,
                "state": state["state"] if state else {},
                "tasks": tasks,
                "agents": agents,
            }
        finally:
            conn.close()
    except Exception as e:
        return _handle_tool_error("collab_get_session_state", e)


@collab_mcp.tool()
def collab_update_session_state(
    session_id: str,
    state: Dict,
    orchestrator_id: str,
) -> Dict:
    """Update the session state (orchestrator only).

    This is the only way to modify session state. Only the orchestrator
    can call this. The state is versioned with optimistic concurrency.

    Args:
        session_id: Target session
        state: New state dict (will be merged with existing state)
        orchestrator_id: The orchestrator's agent ID (for authorization)

    Returns:
        Dict with updated state and version info
    """
    try:
        validate_session_id(session_id)
        validate_agent_id(orchestrator_id)
        conn, sessions_dir = _get_collab_connection()
        try:
            session = collab_db.get_session(conn, session_id)
            if session is None:
                return {"error": f"Session {session_id} not found", "error_type": "session_not_found", "success": False}

            if orchestrator_id != session["orchestrator"]:
                return {"error": "Only the orchestrator can update session state", "error_type": "agent_not_authorized", "success": False}

            sm = StateManager(conn)
            current = sm.get_state(session_id)
            if current is None:
                return {"error": "Session state not found", "error_type": "state_not_found", "success": False}

            merged = {**current["state"], **state}
            now = datetime.now(timezone.utc).isoformat()

            success = sm.update_state(
                session_id, merged, orchestrator_id, now, current["version"]
            )
            if not success:
                return {"error": "State was modified by another process, retry with updated state", "error_type": "state_conflict", "success": False}

            logger.info("Session state updated: %s version=%d", session_id, current["version"] + 1)
            return {
                "success": True,
                "session_id": session_id,
                "version": current["version"] + 1,
                "updated_at": now,
                "state": merged,
            }
        finally:
            conn.close()
    except Exception as e:
        return _handle_tool_error("collab_update_session_state", e)


@collab_mcp.tool()
def collab_send_message(
    session_id: str,
    msg_type: str,
    content: str,
    to_agent: Optional[str] = None,
    metadata: Optional[Dict] = None,
    from_agent: str = "",
) -> Dict:
    """Send a message to a collaboration session.

    Message types:
        task: Assign work to an agent
        result: Return findings or completed work
        question: Ask for clarification
        answer: Respond to a question
        ack: Acknowledge a message
        update: Progress update
        artifact: Reference a saved artifact
        complete: Mark a task as done
        system: System notification (auto-generated)

    Args:
        session_id: Target session
        msg_type: Type of message (task, result, question, answer, ack, update, artifact, complete, system)
        content: Message content
        to_agent: Target agent ID (or None for broadcast)
        metadata: Optional metadata dict
        from_agent: Your agent ID (required for non-orchestrator calls)

    Returns:
        Dict with message info
    """
    try:
        validate_session_id(session_id)
        validate_message_type(msg_type)
        safe_content = validate_message_content(content)

        if from_agent:
            validate_agent_id(from_agent)
        if to_agent:
            validate_agent_id(to_agent)

        conn, sessions_dir = _get_collab_connection()
        try:
            verify_session_exists_and_active(conn, session_id)

            if from_agent:
                verify_agent_in_session(conn, from_agent, session_id)

            now = datetime.now(timezone.utc).isoformat()

            bus = MessageBus(conn, sessions_dir)
            result = bus.send(
                session_id=session_id,
                from_agent=from_agent,
                msg_type=msg_type,
                content=safe_content,
                to_agent=to_agent,
                metadata=metadata,
                created_at=now,
            )

            sm = StateManager(conn)
            sm.bump_activity(session_id, now)

            return {
                "success": True,
                "msg_id": result["msg_id"],
                "seq": result["seq"],
                "session_id": session_id,
                "created_at": now,
            }
        finally:
            conn.close()
    except Exception as e:
        return _handle_tool_error("collab_send_message", e)


@collab_mcp.tool()
def collab_read_messages(
    session_id: str,
    limit: int = 50,
    msg_types: Optional[List[str]] = None,
    from_agent: Optional[str] = None,
    agent_id: str = "",
) -> Dict:
    """Read new messages from a session (offset-based, only returns unseen messages).

    Args:
        session_id: Session to read from
        limit: Max messages to return (default 50)
        msg_types: Filter by message types (optional)
        from_agent: Filter by sender (optional)
        agent_id: Your agent ID (for offset tracking)

    Returns:
        Dict with messages and your current offset
    """
    try:
        validate_session_id(session_id)
        limit = max(1, min(limit, 200))

        conn, sessions_dir = _get_collab_connection()
        try:
            verify_session_exists_and_active(conn, session_id)

            if agent_id:
                validate_agent_id(agent_id)
                verify_agent_in_session(conn, agent_id, session_id)

            bus = MessageBus(conn, sessions_dir)
            last_seq = bus.load_offset(session_id, agent_id) if agent_id else 0

            messages = bus.read_new(
                session_id=session_id,
                last_seq=last_seq,
                limit=limit,
                msg_types=msg_types,
                from_agent=from_agent,
            )

            if messages and agent_id:
                bus.save_offset(session_id, agent_id, messages[-1]["seq"])

            return {
                "messages": messages,
                "count": len(messages),
                "last_seq": messages[-1]["seq"] if messages else last_seq,
                "has_more": len(messages) >= limit,
            }
        finally:
            conn.close()
    except Exception as e:
        return _handle_tool_error("collab_read_messages", e)


@collab_mcp.tool()
def collab_tail_messages(
    session_id: str,
    n: int = 20,
) -> Dict:
    """Read the last N messages from a session (quick status check).

    Args:
        session_id: Session to read from
        n: Number of messages (default 20)

    Returns:
        Dict with the last N messages
    """
    try:
        validate_session_id(session_id)
        n = max(1, min(n, 100))

        conn, sessions_dir = _get_collab_connection()
        try:
            verify_session_exists_and_active(conn, session_id)

            bus = MessageBus(conn, sessions_dir)
            messages = bus.tail(session_id, n)
            return {
                "messages": messages,
                "count": len(messages),
            }
        finally:
            conn.close()
    except Exception as e:
        return _handle_tool_error("collab_tail_messages", e)


@collab_mcp.tool()
def collab_read_message_range(
    session_id: str,
    start_seq: int,
    end_seq: int,
) -> Dict:
    """Read messages in a specific sequence range.

    Use this to zoom into a specific part of the conversation
    when you need more context than tail provides.

    Args:
        session_id: Session to read from
        start_seq: Starting sequence number (inclusive)
        end_seq: Ending sequence number (inclusive)

    Returns:
        Dict with messages in the specified range
    """
    try:
        validate_session_id(session_id)
        if start_seq < 0 or end_seq < 0:
            return {"success": False, "error": "Sequence numbers must be non-negative", "error_type": "validation_error"}
        if start_seq > end_seq:
            return {"success": False, "error": "start_seq must be <= end_seq", "error_type": "validation_error"}
        if end_seq - start_seq > 500:
            return {"success": False, "error": "Range too large (max 500 messages)", "error_type": "validation_error"}

        conn, sessions_dir = _get_collab_connection()
        try:
            bus = MessageBus(conn, sessions_dir)
            messages = bus.read_range(session_id, start_seq, end_seq)
            return {
                "messages": messages,
                "count": len(messages),
                "start_seq": start_seq,
                "end_seq": end_seq,
            }
        finally:
            conn.close()
    except Exception as e:
        return _handle_tool_error("collab_read_message_range", e)


@collab_mcp.tool()
def collab_grep_messages(
    session_id: str,
    pattern: str,
    limit: int = 50,
    msg_types: Optional[List[str]] = None,
) -> Dict:
    """Search session messages by keyword.

    Args:
        session_id: Session to search
        pattern: Search term (supports FTS5 syntax)
        limit: Max results (default 50)
        msg_types: Filter by message types (optional)

    Returns:
        Dict with matching messages
    """
    try:
        validate_session_id(session_id)
        if not pattern or not isinstance(pattern, str):
            return {"success": False, "error": "pattern is required", "error_type": "validation_error"}
        limit = max(1, min(limit, 100))

        conn, sessions_dir = _get_collab_connection()
        try:
            bus = MessageBus(conn, sessions_dir)
            messages = bus.grep(session_id, pattern, limit, msg_types)
            return {
                "messages": messages,
                "count": len(messages),
                "pattern": pattern,
            }
        finally:
            conn.close()
    except Exception as e:
        return _handle_tool_error("collab_grep_messages", e)


@collab_mcp.tool()
def collab_get_session_context(
    session_id: str,
    agent_id: str,
    max_messages: int = 20,
) -> Dict:
    """Get a compiled context view of the session (summary + recent messages + state + tasks + artifacts).

    This is the PRIMARY tool agents should use to understand session state.
    It compiles a complete, attribution-formatted view optimized for context windows.

    Args:
        session_id: Session to get context for
        agent_id: Your agent ID (for personalized context)
        max_messages: Max recent messages to include (default 20)

    Returns:
        Dict with structured context AND a prompt-ready formatted string
    """
    try:
        validate_session_id(session_id)
        validate_agent_id(agent_id)
        max_messages = max(1, min(max_messages, 100))

        conn, sessions_dir = _get_collab_connection()
        try:
            verify_session_exists_and_active(conn, session_id)
            verify_agent_in_session(conn, agent_id, session_id)

            bus = MessageBus(conn, sessions_dir)
            artifact_store = ArtifactStore(conn, sessions_dir)
            compiler = ContextCompiler(conn, bus, artifact_store)

            context = compiler.compile_context(session_id, agent_id, max_messages)
            formatted = compiler.format_context_for_prompt(context)

            return {
                "structured_context": context,
                "formatted_context": formatted,
            }
        finally:
            conn.close()
    except Exception as e:
        return _handle_tool_error("collab_get_session_context", e)


@collab_mcp.tool()
def collab_add_artifact(
    session_id: str,
    title: str,
    content: str,
    created_by: str,
    artifact_type: Optional[str] = None,
    tags: Optional[List[str]] = None,
    shared: bool = False,
) -> Dict:
    """Save a research artifact (finding, analysis, summary) to the session.

    Artifacts are stored as files with metadata indexed in SQLite.
    Use this for significant work products, not for inline messages.

    Args:
        session_id: Target session
        title: Descriptive title for the artifact
        content: Full artifact content (markdown recommended)
        created_by: Your agent ID
        artifact_type: Optional type (research_summary, analysis, code, data, etc.)
        tags: Optional tags for categorization
        shared: If True, save to shared directory (default: False, saves to your workspace)

    Returns:
        Dict with artifact info
    """
    try:
        validate_session_id(session_id)
        validate_agent_id(created_by)
        if not title or not isinstance(title, str):
            return {"success": False, "error": "title is required", "error_type": "validation_error"}
        if not content or not isinstance(content, str):
            return {"success": False, "error": "content is required", "error_type": "validation_error"}

        safe_title = sanitize_content(title)

        conn, sessions_dir = _get_collab_connection()
        try:
            verify_session_exists_and_active(conn, session_id)
            verify_agent_in_session(conn, created_by, session_id)

            now = datetime.now(timezone.utc).isoformat()

            store = ArtifactStore(conn, sessions_dir)
            result = store.save(
                session_id=session_id,
                created_by=created_by,
                title=safe_title,
                content=content,
                created_at=now,
                artifact_type=artifact_type,
                tags=tags,
                shared=shared,
            )

            bus = MessageBus(conn, sessions_dir)
            bus.send(
                session_id=session_id,
                from_agent=created_by,
                msg_type="artifact",
                content=f"Saved artifact: {safe_title}",
                created_at=now,
                to_agent=None,
                metadata={
                    "artifact_id": result["artifact_id"],
                    "title": safe_title,
                    "word_count": result["word_count"],
                },
            )

            logger.info("Artifact added: %s to session %s by %s", result["artifact_id"], session_id, created_by)
            return {
                "success": True,
                "artifact_id": result["artifact_id"],
                "title": result["title"],
                "word_count": result["word_count"],
                "file_path": result["file_path"],
                "shared": result["shared"],
            }
        finally:
            conn.close()
    except Exception as e:
        return _handle_tool_error("collab_add_artifact", e)


@collab_mcp.tool()
def collab_list_artifacts(
    session_id: str,
    created_by: Optional[str] = None,
    artifact_type: Optional[str] = None,
) -> Dict:
    """List artifacts in a session.

    Args:
        session_id: Target session
        created_by: Filter by creator agent (optional)
        artifact_type: Filter by type (optional)

    Returns:
        Dict with list of artifacts
    """
    try:
        validate_session_id(session_id)
        conn, sessions_dir = _get_collab_connection()
        try:
            verify_session_exists_and_active(conn, session_id)

            store = ArtifactStore(conn, sessions_dir)
            artifacts = store.list_artifacts(session_id, created_by, artifact_type)
            return {
                "artifacts": artifacts,
                "count": len(artifacts),
            }
        finally:
            conn.close()
    except Exception as e:
        return _handle_tool_error("collab_list_artifacts", e)


@collab_mcp.tool()
def collab_get_artifact(
    session_id: str,
    artifact_id: str,
) -> Dict:
    """Get the full content of a specific artifact.

    Args:
        session_id: Session containing the artifact
        artifact_id: ID of the artifact to retrieve

    Returns:
        Dict with artifact content and metadata
    """
    try:
        validate_session_id(session_id)
        validate_artifact_id(artifact_id)

        conn, sessions_dir = _get_collab_connection()
        try:
            store = ArtifactStore(conn, sessions_dir)
            content = store.get_content_by_id(session_id, artifact_id)
            if content is None:
                return {"error": f"Artifact {artifact_id} not found in session {session_id}", "error_type": "artifact_not_found", "success": False}

            artifacts = store.list_artifacts(session_id)
            metadata = next(
                (a for a in artifacts if a["artifact_id"] == artifact_id), {}
            )

            return {
                "artifact_id": artifact_id,
                "content": content,
                "metadata": metadata,
            }
        finally:
            conn.close()
    except Exception as e:
        return _handle_tool_error("collab_get_artifact", e)


@collab_mcp.tool()
def collab_grep_artifacts(
    session_id: str,
    pattern: str,
    created_by: Optional[str] = None,
) -> Dict:
    """Search artifact content by keyword.

    Args:
        session_id: Session to search
        pattern: Search term
        created_by: Filter by creator (optional)

    Returns:
        Dict with matching artifacts and their matching lines
    """
    try:
        validate_session_id(session_id)
        if not pattern or not isinstance(pattern, str):
            return {"success": False, "error": "pattern is required", "error_type": "validation_error"}

        conn, sessions_dir = _get_collab_connection()
        try:
            store = ArtifactStore(conn, sessions_dir)
            matches = store.grep_artifacts(session_id, pattern, created_by)
            return {
                "matches": matches,
                "count": len(matches),
                "pattern": pattern,
            }
        finally:
            conn.close()
    except Exception as e:
        return _handle_tool_error("collab_grep_artifacts", e)


@collab_mcp.tool()
def collab_leave_session(
    session_id: str,
    agent_id: str,
    reason: Optional[str] = None,
) -> Dict:
    """Leave a collaboration session gracefully.

    Args:
        session_id: Session to leave
        agent_id: Your agent ID
        reason: Optional reason for leaving

    Returns:
        Dict with confirmation
    """
    try:
        validate_session_id(session_id)
        validate_agent_id(agent_id)

        conn, sessions_dir = _get_collab_connection()
        try:
            verify_agent_in_session(conn, agent_id, session_id)

            leave_collab_session(conn, sessions_dir, agent_id, reason)
            logger.info("Agent %s left session %s", agent_id, session_id)
            return {
                "success": True,
                "agent_id": agent_id,
                "session_id": session_id,
                "status": "left",
            }
        finally:
            conn.close()
    except Exception as e:
        return _handle_tool_error("collab_leave_session", e)


@collab_mcp.tool()
def collab_terminate_session(
    session_id: str,
    summary: Optional[str] = None,
) -> Dict:
    """Terminate and complete a collaboration session.

    Only the orchestrator should call this.
    All artifacts are preserved and can be exported to the main library.

    Args:
        session_id: Session to terminate
        summary: Optional final summary of the session's work

    Returns:
        Dict with termination confirmation
    """
    try:
        validate_session_id(session_id)

        conn, sessions_dir = _get_collab_connection()
        try:
            result = terminate_collab_session(conn, sessions_dir, session_id, summary)
            logger.info("Session terminated: %s", session_id)
            return {
                "success": True,
                "session_id": result["session_id"],
                "status": result["status"],
                "terminated_at": result["terminated_at"],
                "summary_saved": result["summary_saved"],
                "next_steps": [
                    "Use collab_export_to_library to export artifacts to the main library",
                    f"Session files are preserved at: data/sessions/{session_id}/",
                ],
            }
        finally:
            conn.close()
    except Exception as e:
        return _handle_tool_error("collab_terminate_session", e)


@collab_mcp.tool()
def collab_export_to_library(
    session_id: str,
    project: Optional[str] = None,
    confidence: float = 0.8,
    tags: Optional[List[str]] = None,
    artifact_ids: Optional[List[str]] = None,
    include_summary: bool = True,
) -> Dict:
    """Export session artifacts as findings in the main OpenLMLib library.

    After a session completes, use this to permanently store the
    research outputs in the main library for future retrieval.

    Args:
        session_id: Completed session to export
        project: Project name for findings (defaults to session title)
        confidence: Default confidence score (default 0.8)
        tags: Additional tags to apply to all findings
        artifact_ids: Specific artifacts to export (None = all)
        include_summary: Also export the session summary as a finding

    Returns:
        Dict with export results (exported count, failures, finding IDs)
    """
    try:
        validate_session_id(session_id)
        confidence = max(0.0, min(confidence, 1.0))

        conn, sessions_dir = _get_collab_connection()
        try:
            settings_path = _get_settings_path()
            from .export_bridge import export_session_to_library, export_session_summary_as_finding

            result = export_session_to_library(
                settings_path=settings_path,
                session_id=session_id,
                collab_conn=conn,
                sessions_dir=sessions_dir,
                project=project,
                confidence=confidence,
                tags=tags,
                artifact_ids=artifact_ids,
            )

            summary_result = None
            if include_summary and result.get("exported", 0) > 0:
                summary_result = export_session_summary_as_finding(
                    settings_path=settings_path,
                    session_id=session_id,
                    collab_conn=conn,
                    sessions_dir=sessions_dir,
                    project=project,
                )

            result["summary_exported"] = summary_result
            logger.info("Exported %d artifacts from session %s to library", result.get("exported", 0), session_id)
            return result
        finally:
            conn.close()
    except Exception as e:
        return _handle_tool_error("collab_export_to_library", e)


@collab_mcp.tool()
def collab_list_templates() -> Dict:
    """List available session templates for quick session creation.

    Templates provide predefined plans and rules for common research
    patterns like deep research, code review, market analysis, etc.

    Returns:
        Dict with list of templates
    """
    try:
        from .templates import list_templates
        return {
            "templates": list_templates(),
            "count": len(list_templates()),
        }
    except Exception as e:
        return _handle_tool_error("collab_list_templates", e)


@collab_mcp.tool()
def collab_get_template(template_id: str) -> Dict:
    """Get details of a specific session template.

    Args:
        template_id: Template identifier (e.g., 'deep_research', 'code_review')

    Returns:
        Dict with template details including plan and rules
    """
    try:
        from .templates import get_template
        template = get_template(template_id)
        if template is None:
            return {"error": f"Template '{template_id}' not found", "error_type": "template_not_found", "success": False}
        return template
    except Exception as e:
        return _handle_tool_error("collab_get_template", e)


@collab_mcp.tool()
def collab_create_session_from_template(
    template_id: str,
    title: str,
    task_description: str,
    created_by: str = "orchestrator",
) -> Dict:
    """Create a session from a predefined template.

    The template provides the plan (tasks) and rules for the session.

    Args:
        template_id: Template to use (e.g., 'deep_research', 'code_review')
        title: Session title
        task_description: Specific task description for this session
        created_by: Creator identifier

    Returns:
        Dict with session info
    """
    try:
        if not title or not isinstance(title, str):
            return {"success": False, "error": "title is required", "error_type": "validation_error"}

        from .templates import get_template
        template = get_template(template_id)
        if template is None:
            return {"error": f"Template '{template_id}' not found", "error_type": "template_not_found", "success": False}

        safe_title = sanitize_content(title)
        safe_desc = sanitize_content(task_description)

        conn, sessions_dir = _get_collab_connection()
        try:
            result = create_collab_session(
                conn=conn,
                sessions_dir=sessions_dir,
                title=safe_title,
                created_by=created_by,
                description=safe_desc,
                plan=template["plan"],
                rules=template["rules"],
            )
            logger.info("Session created from template %s: %s", template_id, result["session_id"])
            return {
                "success": True,
                "session_id": result["session_id"],
                "your_agent_id": result["agent_id"],
                "template": template_id,
                "title": result["title"],
                "plan_steps": len(template["plan"]),
                "next_steps": [
                    "Use collab_get_session_context to understand the plan",
                    "Use collab_send_message to assign tasks to agents",
                    "Agents can join using collab_join_session",
                ],
            }
        finally:
            conn.close()
    except Exception as e:
        return _handle_tool_error("collab_create_session_from_template", e)


@collab_mcp.tool()
def collab_get_agent_sessions(
    agent_id: str,
    status: Optional[str] = None,
) -> Dict:
    """Get all sessions an agent has participated in.

    Useful for tracking an agent's work across multiple sessions.

    Args:
        agent_id: Agent identifier
        status: Filter by session status (optional)

    Returns:
        Dict with list of sessions and participation info
    """
    try:
        validate_agent_id(agent_id)
        conn, _ = _get_collab_connection()
        try:
            from .multi_session import get_agent_sessions
            sessions = get_agent_sessions(conn, agent_id, status)
            return {
                "agent_id": agent_id,
                "sessions": sessions,
                "count": len(sessions),
            }
        finally:
            conn.close()
    except Exception as e:
        return _handle_tool_error("collab_get_agent_sessions", e)


@collab_mcp.tool()
def collab_get_active_sessions_summary() -> Dict:
    """Get a summary of all active sessions.

    Returns counts of active sessions, agents, and messages.
    """
    try:
        conn, _ = _get_collab_connection()
        try:
            from .multi_session import get_active_sessions_summary
            return get_active_sessions_summary(conn)
        finally:
            conn.close()
    except Exception as e:
        return _handle_tool_error("collab_get_active_sessions_summary", e)


@collab_mcp.tool()
def collab_search_sessions(
    query: str,
    status: Optional[str] = None,
    limit: int = 20,
) -> Dict:
    """Search across all sessions by message content.

    Uses FTS5 full-text search to find sessions matching the query.

    Args:
        query: Search query (supports FTS5 syntax)
        status: Filter by session status (optional)
        limit: Max results (default 20)

    Returns:
        Dict with matching sessions ranked by relevance
    """
    try:
        if not query or not isinstance(query, str):
            return {"success": False, "error": "query is required", "error_type": "validation_error"}
        limit = max(1, min(limit, 100))

        conn, _ = _get_collab_connection()
        try:
            from .multi_session import search_sessions_by_content
            results = search_sessions_by_content(conn, query, limit, status)
            return {
                "query": query,
                "results": results,
                "count": len(results),
            }
        finally:
            conn.close()
    except Exception as e:
        return _handle_tool_error("collab_search_sessions", e)


@collab_mcp.tool()
def collab_get_session_relationships(session_id: str) -> Dict:
    """Find sessions related to a given session.

    Identifies related sessions based on shared agents or same orchestrator.

    Args:
        session_id: Base session to find relationships for

    Returns:
        Dict with related sessions grouped by relationship type
    """
    try:
        validate_session_id(session_id)
        conn, _ = _get_collab_connection()
        try:
            from .multi_session import get_session_relationships
            return get_session_relationships(conn, session_id)
        finally:
            conn.close()
    except Exception as e:
        return _handle_tool_error("collab_get_session_relationships", e)


@collab_mcp.tool()
def collab_get_session_statistics(session_id: str) -> Dict:
    """Get detailed statistics for a session.

    Includes message counts, breakdown by type and agent,
    artifact count, and time range.

    Args:
        session_id: Session to get statistics for

    Returns:
        Dict with session statistics
    """
    try:
        validate_session_id(session_id)
        conn, _ = _get_collab_connection()
        try:
            from .multi_session import get_session_statistics
            return get_session_statistics(conn, session_id)
        finally:
            conn.close()
    except Exception as e:
        return _handle_tool_error("collab_get_session_statistics", e)


@collab_mcp.tool()
def collab_list_openrouter_models(
    search: Optional[str] = None,
    provider: Optional[str] = None,
    max_price_per_million: Optional[float] = None,
    context_length_min: Optional[int] = None,
    is_free: bool = False,
    force_refresh: bool = False,
) -> Dict:
    """List available models from OpenRouter API.

    Fetches the current model catalog and optionally filters by criteria.
    Results are cached for 1 hour to avoid excessive API calls.
    Requires OPENROUTER_API_KEY environment variable.

    Args:
        search: Search term in model name or description
        provider: Filter by provider (e.g., 'openai', 'anthropic', 'google')
        max_price_per_million: Max combined input+output price per 1M tokens
        context_length_min: Minimum context length in tokens
        is_free: Only include free models
        force_refresh: Force fresh API call, ignoring cache

    Returns:
        Dict with list of available models and their details
    """
    try:
        conn, sessions_dir = _get_collab_connection()
        try:
            from .openrouter_client import fetch_openrouter_models, filter_models, format_model_summary

            result = fetch_openrouter_models(sessions_dir, force_refresh)
            if result.get("error"):
                return result

            models = result["models"]
            if search or provider or max_price_per_million is not None or context_length_min is not None or is_free:
                models = filter_models(
                    models,
                    search=search,
                    provider=provider,
                    max_price_per_million=max_price_per_million,
                    context_length_min=context_length_min,
                    is_free=is_free,
                )

            return {
                "models": [
                    {
                        "id": m.get("id"),
                        "name": m.get("name"),
                        "pricing": m.get("pricing", {}),
                        "context_length": m.get("context_length"),
                        "top_provider": m.get("top_provider"),
                    }
                    for m in models
                ],
                "count": len(models),
                "source": result.get("source", "unknown"),
            }
        finally:
            conn.close()
    except Exception as e:
        return _handle_tool_error("collab_list_openrouter_models", e)


@collab_mcp.tool()
def collab_get_openrouter_model_details(model_id: str) -> Dict:
    """Get detailed information about a specific OpenRouter model.

    Args:
        model_id: Full model ID (e.g., 'anthropic/claude-sonnet-4')

    Returns:
        Dict with model details including pricing, context, and description
    """
    try:
        conn, sessions_dir = _get_collab_connection()
        try:
            from .openrouter_client import fetch_openrouter_models, format_model_summary

            result = fetch_openrouter_models(sessions_dir, force_refresh=False)
            if result.get("error"):
                return result

            models = result["models"]
            model = next((m for m in models if m.get("id") == model_id), None)
            if model is None:
                return {"error": f"Model '{model_id}' not found. Use collab_list_openrouter_models to see available models.", "error_type": "model_not_found", "success": False}

            return {
                "model": model,
                "summary": format_model_summary(model),
            }
        finally:
            conn.close()
    except Exception as e:
        return _handle_tool_error("collab_get_openrouter_model_details", e)


@collab_mcp.tool()
def collab_get_recommended_models(task_type: str) -> Dict:
    """Get recommended OpenRouter models for a specific task type.

    Recommendations are based on model capabilities and typical use cases.

    Args:
        task_type: Task type (research, coding, analysis, writing, summarization, orchestrator, worker)

    Returns:
        Dict with recommended model IDs and their details
    """
    try:
        conn, sessions_dir = _get_collab_connection()
        try:
            from .openrouter_client import get_recommended_models_for_task, fetch_openrouter_models, format_model_summary

            recommended_ids = get_recommended_models_for_task(task_type)
            result = fetch_openrouter_models(sessions_dir, force_refresh=False)

            if result.get("error"):
                return {
                    "task_type": task_type,
                    "recommended_ids": recommended_ids,
                    "error": result.get("error"),
                    "note": "Set OPENROUTER_API_KEY to get live model details",
                }

            models_map = {m.get("id"): m for m in result.get("models", [])}
            recommendations = []
            for model_id in recommended_ids:
                model = models_map.get(model_id)
                if model:
                    recommendations.append({
                        "id": model_id,
                        "name": model.get("name"),
                        "pricing": model.get("pricing", {}),
                        "context_length": model.get("context_length"),
                        "summary": format_model_summary(model),
                    })
                else:
                    recommendations.append({"id": model_id, "note": "Not found in current catalog"})

            return {
                "task_type": task_type,
                "recommended_models": recommendations,
                "count": len(recommendations),
            }
        finally:
            conn.close()
    except Exception as e:
        return _handle_tool_error("collab_get_recommended_models", e)
