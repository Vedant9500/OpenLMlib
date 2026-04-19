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
import sqlite3
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

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
from .notification import write_notification
from .notification import wait_for_notification, clear_notification

logger = logging.getLogger(__name__)

# Cached settings resolution to avoid re-parsing settings.json on every call
_cached_paths: Optional[tuple] = None
_cached_paths_mtime: float = 0.0


def _get_collab_paths() -> tuple[Path, Path]:
    """Get the collab DB path and sessions directory from settings.

    Caches the result and invalidates when the settings file changes.
    """
    global _cached_paths, _cached_paths_mtime

    settings_path_str = os.environ.get("OPENLMLIB_SETTINGS")
    if settings_path_str:
        settings_path = Path(settings_path_str)
    else:
        from openlmlib.settings import resolve_global_settings_path
        settings_path = resolve_global_settings_path()

    # Check cache validity
    try:
        current_mtime = settings_path.stat().st_mtime if settings_path.exists() else 0.0
    except OSError:
        current_mtime = 0.0

    if _cached_paths is not None and current_mtime == _cached_paths_mtime:
        return _cached_paths

    if settings_path.exists():
        import json
        with open(settings_path) as f:
            cfg = json.load(f)
        data_root_raw = cfg.get("data_root", "data")
        data_root = Path(data_root_raw)
        # Resolve relative paths against the settings file's parent directory,
        # so all MCP clients (VS Code, Antigravity, etc.) use the same DB.
        if not data_root.is_absolute():
            data_root = settings_path.parent / data_root
    else:
        data_root = Path("data")

    db_path = data_root / "collab_sessions.db"
    sessions_dir = data_root / "sessions"
    _cached_paths = (db_path, sessions_dir)
    _cached_paths_mtime = current_mtime
    return _cached_paths


def _get_sessions_dir() -> Path:
    """Get just the sessions directory (no DB connection needed)."""
    _, sessions_dir = _get_collab_paths()
    sessions_dir.mkdir(parents=True, exist_ok=True)
    return sessions_dir


def _get_settings_path() -> Path:
    """Get the OpenLMLib settings path."""
    settings_path_str = os.environ.get("OPENLMLIB_SETTINGS")
    if settings_path_str:
        return Path(settings_path_str)
    from openlmlib.settings import resolve_global_settings_path
    return resolve_global_settings_path()


@contextmanager
def _collab_connection():
    """Context manager for collab DB connections with auto-init and cleanup."""
    db_path, sessions_dir = _get_collab_paths()
    sessions_dir.mkdir(parents=True, exist_ok=True)

    try:
        from .db import get_thread_connection
        conn = get_thread_connection(db_path)
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
            raise DatabaseError(f"Failed to initialize collab database: {e}")
    yield conn, sessions_dir


def _get_collab_connection():
    """Get a connection to the collab database, initializing if needed.

    DEPRECATED: Use _collab_connection() context manager instead for new tools.
    Kept for backward compatibility during migration.
    """
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


def _require_reader_access(
    conn: sqlite3.Connection,
    session_id: str,
    agent_id: str,
) -> Dict:
    """Authorize a session-scoped read for a session member."""
    if not agent_id:
        raise SecurityError("agent_id is required for session reads")
    validate_agent_id(agent_id)

    session = collab_db.get_session(conn, session_id)
    if session is None:
        raise SessionNotFoundError(f"Session {session_id} not found")

    verify_agent_in_session(conn, agent_id, session_id)
    return session


collab_mcp = FastMCP("OpenLMlib CollabSessions")

__all__ = [
    "collab_mcp",
    "create_session",
    "join_session",
    "list_sessions",
    "get_session_state",
    "update_session_state",
    "send_message",
    "read_messages",
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
    "help_collab",
]

@collab_mcp.tool()
def create_session(
    title: str,
    task_description: str,
    plan: Optional[List[Dict]] = None,
    rules: Optional[Dict] = None,
    created_by: str = "orchestrator",
) -> Dict:
    """Create a new collaboration session for multi-agent research.

    AUTOMATIC TRIGGERS - Call this when:
    - Starting a new multi-agent research task
    - User asks to set up a collaboration session
    - You need to coordinate work across multiple agents

    WORKFLOW POSITION: First tool in any collaboration workflow.

    PARAMETERS:
    - title: Short descriptive title for the session
    - task_description: Detailed description of the research task
    - plan: Optional list of task dicts (step, task, assigned_to) - recommended for structured work
    - rules: Optional session rules (max_agents, require_assignment)
    - created_by: Your agent identifier (default: "orchestrator")

    After creation, use join_session for agents to join,
    then send_message to assign tasks.
    """
    try:
        if not title or not isinstance(title, str):
            return {"success": False, "error": "title is required", "error_type": "validation_error"}
        if not task_description or not isinstance(task_description, str):
            return {"success": False, "error": "task_description is required", "error_type": "validation_error"}

        safe_title = sanitize_content(title)
        safe_desc = sanitize_content(task_description)

        with _collab_connection() as (conn, sessions_dir):
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
                    "Use update_session_state to set the initial plan",
                    "Use send_message to assign tasks to agents",
                    "Use read_messages to monitor progress",
                ],
            }
    except Exception as e:
        return _handle_tool_error("create_session", e)


@collab_mcp.tool()
def join_session(
    session_id: str,
    model: str,
    capabilities: Optional[List[str]] = None,
) -> Dict:
    """Join an existing collaboration session as an agent.

    AUTOMATIC TRIGGERS - Call this when:
    - You've been assigned work in a session
    - You need to participate in an active collaboration
    - Starting work as a worker or specialist in a multi-agent setup

    WORKFLOW POSITION: Call after session is created and you have the session_id.

    PARAMETERS:
    - session_id: ID of the session to join
    - model: Your model identifier (e.g., 'gpt-codex', 'gemini-pro')
    - capabilities: Optional list of your capabilities (e.g., ['research', 'code_analysis'])

    After joining, read the session_context above to understand current state,
    then use read_messages to check for new messages.
    """
    try:
        validate_session_id(session_id)
        if not model or not isinstance(model, str):
            return {"success": False, "error": "model is required", "error_type": "validation_error"}

        with _collab_connection() as (conn, sessions_dir):
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
                    "Use read_messages to check for new messages",
                    "Use send_message to communicate with other agents",
                    "Use save_artifact to save your research outputs",
                ],
            }
    except Exception as e:
        return _handle_tool_error("join_session", e)


@collab_mcp.tool()
def list_sessions(
    status: Optional[str] = None,
    limit: int = 20,
) -> Dict:
    """List collaboration sessions. Browse sessions you've participated in.

    AUTOMATIC TRIGGERS - Call this when:
    - User asks to see their sessions
    - You want to find a specific session to rejoin
    - Checking what sessions are active

    FOR SESSION DETAILS, use session_context after finding the session_id.

    PARAMETERS:
    - status: Filter by status - "active", "completed", "terminated" (optional)
    - limit: Max sessions to return (default: 20, max: 100)
    """
    try:
        limit = max(1, min(limit, 100))
        with _collab_connection() as (conn, _):
            sessions = collab_db.list_sessions(conn, status=status, limit=limit)
            return {
                "sessions": sessions,
                "count": len(sessions),
            }
    except Exception as e:
        return _handle_tool_error("list_sessions", e)


@collab_mcp.tool()
def collab_claim_task(session_id: str, agent_id: str, task_id: Optional[str] = None) -> Dict:
    """Claim a pending task in a collaboration session.

    AUTOMATIC TRIGGERS - Call this when:
    - You are a worker looking for your next task
    - You see pending tasks and want to take initiative
    - The orchestrator has not assigned you work
    
    If task_id is provided, claims that specific task.
    If task_id is omitted, claims the first available task from the earliest pending step.

    PARAMETERS:
    - session_id: Target session
    - agent_id: Your agent ID
    - task_id: Optional specific task to claim
    """
    try:
        validate_session_id(session_id)
        with _collab_connection() as (conn, sessions_dir):
            _require_reader_access(conn, session_id, agent_id)
            
            # Need datetime for started_at
            from datetime import datetime, timezone
            started_at = datetime.now(timezone.utc).isoformat()
            
            claimed = collab_db.claim_task(conn, session_id, agent_id, started_at, task_id)
            if not claimed:
                return {
                    "success": False,
                    "error": "No pending tasks available to claim",
                    "error_type": "no_tasks"
                }
                
            return {
                "success": True,
                "claimed_task": claimed
            }
    except Exception as e:
        return _handle_tool_error("collab_claim_task", e)
@collab_mcp.tool()
def get_session_state(session_id: str, agent_id: str) -> Dict:
    """Get the current state of a collaboration session - tasks, agents, and session state.

    AUTOMATIC TRIGGERS - Call this when:
    - You need to see the task list and assignments
    - Checking which agents are in the session
    - Reviewing session metadata (status, created_at, etc.)

    DIFFERENCE from session_context: This returns raw structured data
    (tasks, agents, state dict). Use get_session_context for a formatted narrative view.

    PARAMETERS:
    - session_id: ID of the session
    - agent_id: Your agent ID (must belong to the session)
    """
    try:
        validate_session_id(session_id)
        with _collab_connection() as (conn, sessions_dir):
            session = _require_reader_access(conn, session_id, agent_id)

            state = collab_db.get_session_state(conn, session_id)
            tasks = collab_db.get_session_tasks(conn, session_id)
            agents = collab_db.get_session_agents(conn, session_id)

            pending_count = sum(1 for t in tasks if t.get("status") == "pending" and t.get("assigned_to") in (None, "any"))

            return {
                "session": session,
                "state": state["state"] if state else {},
                "tasks": tasks,
                "agents": agents,
                "queue_depth": pending_count,
            }
    except Exception as e:
        return _handle_tool_error("get_session_state", e)


@collab_mcp.tool()
def update_session_state(
    session_id: str,
    state: Dict,
    orchestrator_id: str,
) -> Dict:
    """Update the session state. Orchestrator only. The only way to modify session state.

    AUTOMATIC TRIGGERS - Call this when:
    - You need to record progress updates
    - Setting the current phase of work
    - Storing session metadata (current step, active agents, etc.)

    ONLY the orchestrator can call this. State is versioned with optimistic concurrency
    to prevent conflicts. If update fails, retry with latest state.

    PARAMETERS:
    - session_id: Target session
    - state: New state dict (will be merged with existing state)
    - orchestrator_id: The orchestrator's agent ID (for authorization)
    """
    try:
        validate_session_id(session_id)
        validate_agent_id(orchestrator_id)
        with _collab_connection() as (conn, sessions_dir):
            verify_orchestrator(conn, session_id, orchestrator_id)

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
    except Exception as e:
        return _handle_tool_error("update_session_state", e)


@collab_mcp.tool()
def send_message(
    session_id: str,
    msg_type: str,
    content: str,
    to_agent: Optional[str] = None,
    metadata: Optional[Dict] = None,
    from_agent: str = "",
) -> Dict:
    # NOTE: from_agent should ideally be required for non-system calls
    """Send a message to a collaboration session. Core communication tool.

    AUTOMATIC TRIGGERS - Call this when:
    - Assigning work to an agent (msg_type="task")
    - Returning findings or completed work (msg_type="result")
    - Asking for clarification (msg_type="question")
    - Responding to a question (msg_type="answer")
    - Providing progress updates (msg_type="update")
    - Marking a task as done (msg_type="complete")

    MESSAGE TYPES:
    - task: Assign work to an agent
    - result: Return findings or completed work
    - question: Ask for clarification
    - answer: Respond to a question
    - ack: Acknowledge a message
    - update: Progress update
    - artifact: Reference a saved artifact
    - complete: Mark a task as done
    - system: System notification (auto-generated)

    WORKFLOW POSITION: Use throughout the session for all agent communication.

    PARAMETERS:
    - session_id: Target session
    - msg_type: Type of message (see above)
    - content: Message content
    - to_agent: Target agent ID (or None for broadcast)
    - from_agent: Your agent ID (required)
    - metadata: Optional metadata dict
    """
    try:
        validate_session_id(session_id)
        validate_message_type(msg_type)
        safe_content = sanitize_content(validate_message_content(content))

        if not from_agent:
            return {"success": False, "error": "from_agent is required", "error_type": "validation_error"}
        validate_agent_id(from_agent)
        if to_agent is not None and to_agent != "":
            validate_agent_id(to_agent)

        with _collab_connection() as (conn, sessions_dir):
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

            # Performance tracking hook
            if msg_type == "complete" and metadata and "task_id" in metadata:
                task_id = metadata["task_id"]
                # Mark DB status
                from .db import update_task_status, log_task_performance, get_session_tasks
                update_task_status(conn, task_id, "completed", completed_at=now)
                
                # Fetch task started_at to compute latency
                tasks = get_session_tasks(conn, session_id)
                task = next((t for t in tasks if t["task_id"] == task_id), None)
                latency_ms = 0
                if task and task.get("started_at"):
                    try:
                        start_ts = datetime.fromisoformat(task["started_at"].replace("Z", "+00:00")).timestamp()
                        end_ts = datetime.fromisoformat(now.replace("Z", "+00:00")).timestamp()
                        latency_ms = int((end_ts - start_ts) * 1000)
                    except ValueError:
                        pass
                
                # Extract model from agents table
                actor_model = "default"
                if from_agent:
                    from .context_compiler import _get_model_family
                    row = conn.execute("SELECT model FROM agents WHERE session_id = ? AND agent_id = ?", (session_id, from_agent)).fetchone()
                    if row:
                        actor_model = _get_model_family(row["model"])

                log_task_performance(
                    conn=conn,
                    session_id=session_id,
                    task_id=task_id,
                    agent_id=from_agent,
                    model_family=actor_model,
                    latency_ms=latency_ms,
                    is_success=True,
                    created_at=now,
                )

            # Write cross-process notification so other MCP instances wake up
            if not write_notification(
                sessions_dir=sessions_dir,
                session_id=session_id,
                sender=from_agent,
                msg_type=msg_type,
                seq=result["seq"],
                msg_id=result["msg_id"],
                timestamp=now,
            ):
                logger.warning(
                    "Notification write failed for %s — polling agents may miss "
                    "message %s (message was still sent to bus)",
                    session_id,
                    result["msg_id"],
                )

            return {
                "success": True,
                "msg_id": result["msg_id"],
                "seq": result["seq"],
                "session_id": session_id,
                "created_at": now,
            }
    except Exception as e:
        return _handle_tool_error("send_message", e)


@collab_mcp.tool()
def read_messages(
    session_id: str,
    agent_id: str,
    limit: int = 50,
    msg_types: Optional[List[str]] = None,
    from_agent: Optional[str] = None,
) -> Dict:
    """Read new messages from a session. Returns only unseen messages (offset-tracked).

    AUTOMATIC TRIGGERS - Call this when:
    - Checking for new messages after sending a response
    - Looking for task assignments or answers to your questions
    - Periodic status check during active collaboration

    DIFFERENCE from poll_messages: This returns immediately without waiting.
    Use poll_messages for blocking waits in autonomous agent loops.

    WORKFLOW POSITION: Call after sending messages, between work steps.

    PARAMETERS:
    - session_id: Session to read from
    - agent_id: Your agent ID (required for authorization and offset tracking)
    - limit: Max messages to return (default: 50, max: 200)
    - msg_types: Filter by message types like ["task", "answer"] (optional)
    - from_agent: Filter by specific sender (optional)
    """
    try:
        validate_session_id(session_id)
        limit = max(1, min(limit, 200))
        if not agent_id:
            return {"success": False, "error": "agent_id is required", "error_type": "validation_error"}

        with _collab_connection() as (conn, sessions_dir):
            _require_reader_access(conn, session_id, agent_id)

            bus = MessageBus(conn, sessions_dir)
            stored_last_seq = bus.load_offset(session_id, agent_id)

            messages = bus.read_new(
                session_id=session_id,
                last_seq=stored_last_seq,
                limit=limit,
                msg_types=msg_types,
                from_agent=from_agent,
            )

            offset_updated = not msg_types and from_agent is None
            if messages and offset_updated:
                bus.save_offset(session_id, agent_id, messages[-1]["seq"])

            return {
                "messages": messages,
                "count": len(messages),
                "last_seq": messages[-1]["seq"] if messages and offset_updated else stored_last_seq,
                "returned_last_seq": messages[-1]["seq"] if messages else stored_last_seq,
                "offset_updated": offset_updated,
                "has_more": len(messages) >= limit,
            }
    except Exception as e:
        return _handle_tool_error("read_messages", e)


@collab_mcp.tool()
def poll_messages(
    session_id: str,
    agent_id: str,
    timeout: float = 30.0,
    limit: int = 50,
    msg_types: Optional[List[str]] = None,
    from_agent: Optional[str] = None,
) -> Dict:
    """Wait for and read new messages from a session. AUTONOMOUS LOOP tool for agent communication.

    AUTOMATIC TRIGGERS - Call this when:
    - You're running an autonomous agent loop
    - Waiting for other agents to complete work
    - Need real-time collaboration without human intervention

    This tool BLOCKS until new messages arrive or the timeout expires.
    It is the primary mechanism for agents to run continuous collaboration.

    USAGE PATTERN FOR AUTONOMOUS AGENTS:
        1. Call poll_messages(session_id, agent_id, timeout=30)
        2. Process any returned messages
        3. Send responses via send_message
        4. Repeat from step 1 until the session is complete

    WORKFLOW POSITION: Main loop tool for autonomous agents.

    PARAMETERS:
    - session_id: Session to monitor
    - agent_id: Your agent ID
    - timeout: Max seconds to wait (default: 30, 0 = no wait)
    - limit: Max messages to return (default: 50)
    - msg_types: Filter by message types (optional)
    - from_agent: Filter by sender (optional)
    """
    import time as _time

    try:
        validate_session_id(session_id)
        limit = max(1, min(limit, 200))
        if not agent_id:
            return {"success": False, "error": "agent_id is required", "error_type": "validation_error"}

        with _collab_connection() as (conn, sessions_dir):
            _require_reader_access(conn, session_id, agent_id)

            # Check current status first
            session = collab_db.get_session(conn, session_id)
            if session is None:
                return {"success": False, "error": "Session not found", "error_type": "session_not_found"}

            session_status = session.get("status", "unknown")
            if session_status in ("completed", "terminated"):
                # Session ended — return immediately without waiting
                return {
                    "success": True,
                    "messages": [],
                    "count": 0,
                    "waited_seconds": 0.0,
                    "timed_out": False,
                    "last_seq": 0,
                    "session_status": session_status,
                    "note": f"Session is {session_status}, no more messages expected",
                }

            bus = MessageBus(conn, sessions_dir)
            stored_last_seq = bus.load_offset(session_id, agent_id)

            # Check if messages already exist since our last read
            existing = bus.read_new(
                session_id=session_id,
                last_seq=stored_last_seq,
                limit=limit,
                msg_types=msg_types,
                from_agent=from_agent,
            )
            if existing:
                # Messages already available — return immediately, no blocking
                new_last_seq = existing[-1]["seq"]
                bus.save_offset(session_id, agent_id, new_last_seq)
                return {
                    "success": True,
                    "messages": existing,
                    "count": len(existing),
                    "waited_seconds": 0.0,
                    "timed_out": False,
                    "last_seq": new_last_seq,
                    "session_status": session_status,
                    "has_more": len(existing) >= limit,
                }

        # No new messages — wait for a notification signal without holding DB lock
        if timeout == 0:
            return {
                "success": True,
                "messages": [],
                "count": 0,
                "waited_seconds": 0.0,
                "timed_out": True,
                "last_seq": stored_last_seq,
                "session_status": session_status,
            }

        start = _time.monotonic()
        notify = wait_for_notification(
            sessions_dir=sessions_dir,
            session_id=session_id,
            timeout=timeout,
            poll_interval=0.3,
            last_seq=stored_last_seq,
        )
        waited = _time.monotonic() - start

        # Re-acquire connection to read results
        with _collab_connection() as (conn, sessions_dir):
            bus = MessageBus(conn, sessions_dir)
            
            # Re-check session status after waiting
            session = collab_db.get_session(conn, session_id)
            session_status = session.get("status", "unknown") if session else "unknown"

            if session_status in ("completed", "terminated"):
                return {
                    "success": True,
                    "messages": [],
                    "count": 0,
                    "waited_seconds": round(waited, 2),
                    "timed_out": False,
                    "last_seq": stored_last_seq,
                    "session_status": session_status,
                    "note": f"Session is now {session_status}",
                }

            # ALWAYS read new messages, even on timeout, to avoid missing any
            messages = bus.read_new(
                session_id=session_id,
                last_seq=stored_last_seq,
                limit=limit,
                msg_types=msg_types,
                from_agent=from_agent,
            )

            if messages:
                new_last_seq = messages[-1]["seq"]
                bus.save_offset(session_id, agent_id, new_last_seq)
            else:
                new_last_seq = stored_last_seq

            is_timeout = not messages and notify is None

            return {
                "success": True,
                "messages": messages,
                "count": len(messages),
                "waited_seconds": round(waited, 2),
                "timed_out": is_timeout,
                "last_seq": new_last_seq,
                "session_status": session_status,
                "has_more": len(messages) >= limit,
                "notification_from": notify.get("sender") if notify else None,
                "notification_type": notify.get("msg_type") if notify else None,
            }
    except Exception as e:
        return _handle_tool_error("poll_messages", e)


@collab_mcp.tool()
def tail_messages(
    session_id: str,
    agent_id: str,
    n: int = 20,
) -> Dict:
    """Read the last N messages from a session. Quick status check without offset tracking.

    AUTOMATIC TRIGGERS - Call this when:
    - You just joined and want to see recent activity
    - Quick glance at what's happening without tracking offsets
    - Checking session state before full context load

    DIFFERENCE from read_messages: This does NOT track your read offset
    and always returns the most recent N messages regardless of what you've seen.
    Use read_messages for tracking unseen messages.

    PARAMETERS:
    - session_id: Session to read from
    - agent_id: Your agent ID (must belong to the session)
    - n: Number of messages (default: 20, max: 100)
    """
    try:
        validate_session_id(session_id)
        n = max(1, min(n, 100))

        with _collab_connection() as (conn, sessions_dir):
            _require_reader_access(conn, session_id, agent_id)

            bus = MessageBus(conn, sessions_dir)
            messages = bus.tail(session_id, n)
            return {
                "messages": messages,
                "count": len(messages),
            }
    except Exception as e:
        return _handle_tool_error("tail_messages", e)


@collab_mcp.tool()
def read_message_range(
    session_id: str,
    start_seq: int,
    end_seq: int,
    agent_id: str,
) -> Dict:
    """Read messages in a specific sequence range. Zoom into a conversation section.

    AUTOMATIC TRIGGERS - Call this when:
    - You need context from a specific point in the conversation
    - A message references an earlier seq number
    - You want to review a specific exchange between agents

    DIFFERENCE from read_messages: This reads a specific range by sequence
    numbers, not just "new" messages. Use for targeted context retrieval.

    PARAMETERS:
    - session_id: Session to read from
    - start_seq: Starting sequence number (inclusive) - get from message metadata
    - end_seq: Ending sequence number (exclusive) - max range is 500 messages
    - agent_id: Your agent ID (must belong to the session)
    """
    try:
        validate_session_id(session_id)
        if start_seq < 0 or end_seq < 0:
            return {"success": False, "error": "Sequence numbers must be non-negative", "error_type": "validation_error"}
        if start_seq > end_seq:
            return {"success": False, "error": "start_seq must be <= end_seq", "error_type": "validation_error"}
        if end_seq - start_seq > 500:
            return {"success": False, "error": "Range too large (max 500 messages)", "error_type": "validation_error"}

        with _collab_connection() as (conn, sessions_dir):
            _require_reader_access(conn, session_id, agent_id)
            bus = MessageBus(conn, sessions_dir)
            messages = bus.read_range(session_id, start_seq, end_seq)
            return {
                "messages": messages,
                "count": len(messages),
                "start_seq": start_seq,
                "end_seq": end_seq,
            }
    except Exception as e:
        return _handle_tool_error("read_message_range", e)


@collab_mcp.tool()
def grep_messages(
    session_id: str,
    pattern: str,
    agent_id: str,
    limit: int = 50,
    msg_types: Optional[List[str]] = None,
) -> Dict:
    """Search session messages by keyword. FTS5 full-text search across all messages.

    AUTOMATIC TRIGGERS - Call this when:
    - Looking for a specific topic, decision, or finding mentioned earlier
    - You don't know the sequence number but remember keywords
    - Checking if a topic has been discussed in the session

    SEARCH TIPS: Use simple keywords. FTS5 supports: "word1 word2" (AND), "word1 OR word2".
    Avoid complex syntax - use plain phrases.

    PARAMETERS:
    - session_id: Session to search
    - pattern: Search term (use simple keywords)
    - agent_id: Your agent ID (must belong to the session)
    - limit: Max results (default: 50, max: 100)
    - msg_types: Filter by message types like ["result", "artifact"] (optional)
    """
    try:
        validate_session_id(session_id)
        if not pattern or not isinstance(pattern, str):
            return {"success": False, "error": "pattern is required", "error_type": "validation_error"}
        limit = max(1, min(limit, 100))

        with _collab_connection() as (conn, sessions_dir):
            _require_reader_access(conn, session_id, agent_id)
            bus = MessageBus(conn, sessions_dir)
            try:
                messages = bus.grep(session_id, pattern, limit, msg_types)
            except sqlite3.OperationalError as fts_err:
                # FTS5 syntax error from malformed user input
                return {
                    "success": False,
                    "error": f"Invalid search pattern: {fts_err}. Use simple keywords or quote phrases.",
                    "error_type": "validation_error",
                }
            return {
                "messages": messages,
                "count": len(messages),
                "pattern": pattern,
            }
    except Exception as e:
        return _handle_tool_error("grep_messages", e)


@collab_mcp.tool()
def session_context(
    session_id: str,
    agent_id: str,
    max_messages: int = 5,
) -> Dict:
    """Get a compiled context view of the session. PRIMARY tool for understanding session state.

    AUTOMATIC TRIGGERS - Call this when:
    - Joining a session and you need to understand current state
    - Before starting work to see what's been done
    - After being assigned a task to understand context
    - Whenever you're unsure about session status

    This is the GO-TO tool for session understanding. Returns summary + recent messages
    + state + tasks + artifacts in a formatted view optimized for context windows.

    WORKFLOW POSITION: Call after joining, before starting work, and periodically.

    PARAMETERS:
    - session_id: Session to get context for
    - agent_id: Your agent ID
    - max_messages: Max recent messages to include (default: 20)
    """
    try:
        validate_session_id(session_id)
        max_messages = max(1, min(max_messages, 200))

        with _collab_connection() as (conn, sessions_dir):
            verify_session_exists_and_active(conn, session_id)

            if agent_id is not None and agent_id != "":
                validate_agent_id(agent_id)
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
    except Exception as e:
        return _handle_tool_error("session_context", e)


@collab_mcp.tool()
def save_artifact(
    session_id: str,
    title: str,
    content: str,
    created_by: str,
    artifact_type: Optional[str] = None,
    tags: Optional[List[str]] = None,
    shared: bool = False,
) -> Dict:
    """Save a research artifact (finding, analysis, summary) to the session.

    AUTOMATIC TRIGGERS - Call this when:
    - You complete a significant analysis or research summary
    - You've written important code or documentation
    - You want to save a detailed analysis (beyond a simple message)
    - Completing a major deliverable

    Use this for SIGNIFICANT work products, not for inline messages.
    Artifacts are stored as files with metadata indexed in SQLite.

    WORKFLOW POSITION: Call after completing substantial work.

    PARAMETERS:
    - session_id: Target session
    - title: Descriptive title for the artifact
    - content: Full artifact content (markdown recommended)
    - created_by: Your agent ID
    - artifact_type: Type like 'research_summary', 'analysis', 'code', 'data'
    - tags: Tags for categorization
    - shared: If True, save to shared directory (default: False)
    """
    try:
        validate_session_id(session_id)
        validate_agent_id(created_by)
        if not title or not isinstance(title, str):
            return {"success": False, "error": "title is required", "error_type": "validation_error"}
        if not content or not isinstance(content, str):
            return {"success": False, "error": "content is required", "error_type": "validation_error"}

        safe_title = sanitize_content(title)

        with _collab_connection() as (conn, sessions_dir):
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
    except Exception as e:
        return _handle_tool_error("save_artifact", e)


@collab_mcp.tool()
def list_artifacts(
    session_id: str,
    agent_id: str,
    created_by: Optional[str] = None,
    artifact_type: Optional[str] = None,
) -> Dict:
    """List artifacts in a session. Browse saved work products, analyses, and summaries.

    AUTOMATIC TRIGGERS - Call this when:
    - Checking what work has been saved in the session
    - Looking for a specific analysis or report
    - Before creating a new artifact to avoid duplicates

    FOR ARTIFACT CONTENT, use get_artifact after finding the artifact_id.

    PARAMETERS:
    - session_id: Target session
    - agent_id: Your agent ID (must belong to the session)
    - created_by: Filter by creator agent (optional) - "show artifacts by agent X"
    - artifact_type: Filter by type like "research_summary", "analysis", "code" (optional)
    """
    try:
        validate_session_id(session_id)
        with _collab_connection() as (conn, sessions_dir):
            _require_reader_access(conn, session_id, agent_id)

            store = ArtifactStore(conn, sessions_dir)
            artifacts = store.list_artifacts(session_id, created_by, artifact_type)
            return {
                "artifacts": artifacts,
                "count": len(artifacts),
            }
    except Exception as e:
        return _handle_tool_error("list_artifacts", e)


@collab_mcp.tool()
def get_artifact(
    session_id: str,
    artifact_id: str,
    agent_id: str,
) -> Dict:
    """Get the full content of a specific artifact. Retrieve saved analysis or report.

    AUTOMATIC TRIGGERS - Call this when:
    - You have an artifact_id from list_artifacts or a message reference
    - Need to review another agent's completed work
    - Reading detailed analysis that was saved as an artifact

    WORKFLOW POSITION: Call after finding the artifact_id from list_artifacts or messages.

    PARAMETERS:
    - session_id: Session containing the artifact
    - artifact_id: ID of the artifact (e.g., "art_001")
    - agent_id: Your agent ID (must belong to the session)
    """
    try:
        validate_session_id(session_id)
        validate_artifact_id(artifact_id)

        with _collab_connection() as (conn, sessions_dir):
            _require_reader_access(conn, session_id, agent_id)
            store = ArtifactStore(conn, sessions_dir)
            content = store.get_content_by_id(session_id, artifact_id)
            if content is None:
                return {"error": f"Artifact {artifact_id} not found in session {session_id}", "error_type": "artifact_not_found", "success": False}

            metadata = store.get_artifact(session_id, artifact_id) or {}

            return {
                "artifact_id": artifact_id,
                "content": content,
                "metadata": metadata,
            }
    except Exception as e:
        return _handle_tool_error("get_artifact", e)


@collab_mcp.tool()
def grep_artifacts(
    session_id: str,
    pattern: str,
    agent_id: str,
    created_by: Optional[str] = None,
) -> Dict:
    """Search artifact content by keyword. Find saved work by topic or term.

    AUTOMATIC TRIGGERS - Call this when:
    - Looking for artifacts mentioning a specific topic
    - Need to find prior analysis on a subject
    - Searching across all saved work products in the session

    PARAMETERS:
    - session_id: Session to search
    - pattern: Search term (use simple keywords)
    - agent_id: Your agent ID (must belong to the session)
    - created_by: Filter by creator agent (optional)
    """
    try:
        validate_session_id(session_id)
        if not pattern or not isinstance(pattern, str):
            return {"success": False, "error": "pattern is required", "error_type": "validation_error"}

        with _collab_connection() as (conn, sessions_dir):
            _require_reader_access(conn, session_id, agent_id)
            store = ArtifactStore(conn, sessions_dir)
            matches = store.grep_artifacts(session_id, pattern, created_by)
            return {
                "matches": matches,
                "count": len(matches),
                "pattern": pattern,
            }
    except Exception as e:
        return _handle_tool_error("grep_artifacts", e)


@collab_mcp.tool()
def leave_session(
    session_id: str,
    agent_id: str,
    reason: Optional[str] = None,
) -> Dict:
    """Leave a collaboration session gracefully. Clean exit for an agent.

    AUTOMATIC TRIGGERS - Call this when:
    - Your assigned tasks are complete
    - You're done with this session and moving to other work
    - User asks you to leave the session

    DIFFERENCE from terminate_session: This is for individual agents leaving.
    Only the orchestrator should call terminate_session to end the entire session.

    PARAMETERS:
    - session_id: Session to leave
    - agent_id: Your agent ID
    - reason: Optional reason for leaving (helps other agents understand)
    """
    try:
        validate_session_id(session_id)
        validate_agent_id(agent_id)

        with _collab_connection() as (conn, sessions_dir):
            verify_agent_in_session(conn, agent_id, session_id)

            leave_collab_session(conn, sessions_dir, agent_id, reason)
            logger.info("Agent %s left session %s", agent_id, session_id)
            return {
                "success": True,
                "agent_id": agent_id,
                "session_id": session_id,
                "status": "left",
            }
    except Exception as e:
        return _handle_tool_error("leave_session", e)


@collab_mcp.tool()
def terminate_session(
    session_id: str,
    orchestrator_id: str,
    summary: Optional[str] = None,
) -> Dict:
    """Terminate and complete a collaboration session. Orchestrator only.

    AUTOMATIC TRIGGERS - Call this when:
    - All tasks in the session are completed
    - You want to formally end the collaboration
    - Session goal has been achieved

    Only the orchestrator should call this.
    All artifacts are preserved and can be exported to the main library.

    WORKFLOW POSITION: Last tool in collaboration workflow (before export).

    PARAMETERS:
    - session_id: Session to terminate
    - orchestrator_id: The orchestrator's agent ID
    - summary: Optional final summary of the session's work

    After termination, use export_to_library to persist findings.
    """
    try:
        validate_session_id(session_id)
        validate_agent_id(orchestrator_id)

        with _collab_connection() as (conn, sessions_dir):
            verify_orchestrator(conn, session_id, orchestrator_id)
            result = terminate_collab_session(conn, sessions_dir, session_id, summary)
            logger.info("Session terminated: %s", session_id)
            return {
                "success": True,
                "session_id": result["session_id"],
                "status": result["status"],
                "terminated_at": result["terminated_at"],
                "summary_saved": result["summary_saved"],
                "next_steps": [
                    "Use export_to_library to export artifacts to the main library",
                    f"Session files are preserved at: data/sessions/{session_id}/",
                ],
            }
    except Exception as e:
        return _handle_tool_error("terminate_session", e)


@collab_mcp.tool()
def export_to_library(
    session_id: str,
    project: Optional[str] = None,
    confidence: float = 0.8,
    tags: Optional[List[str]] = None,
    artifact_ids: Optional[List[str]] = None,
    include_summary: bool = True,
) -> Dict:
    """Export session artifacts as findings in the main OpenLMLib library.

    AUTOMATIC TRIGGERS - Call this when:
    - A collaboration session is completed
    - You want to persist session work to the main knowledge base
    - Future sessions might need this knowledge

    After a session completes, use this to permanently store the
    research outputs in the main library for future retrieval.

    WORKFLOW POSITION: After session termination, before starting new work.

    PARAMETERS:
    - session_id: Completed session to export
    - project: Project name for findings (defaults to session title)
    - confidence: Default confidence 0.0-1.0 (default: 0.8)
    - tags: Additional tags to apply to all findings
    - artifact_ids: Specific artifacts to export (None = all)
    - include_summary: Also export the session summary as a finding (default: True)
    """
    try:
        validate_session_id(session_id)
        confidence = max(0.0, min(confidence, 1.0))

        with _collab_connection() as (conn, sessions_dir):
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
    except Exception as e:
        return _handle_tool_error("export_to_library", e)


@collab_mcp.tool()
def list_templates() -> Dict:
    """List available session templates. Pre-built plans for common research patterns.

    AUTOMATIC TRIGGERS - Call this when:
    - Starting a new session and want a structured plan
    - User asks to use a template
    - Looking for recommended workflows (deep_research, code_review, etc.)

    After finding a template, use create_from_template to start.
    """
    try:
        from .templates import list_templates
        templates = list_templates()
        return {
            "templates": templates,
            "count": len(templates),
        }
    except Exception as e:
        return _handle_tool_error("list_templates", e)


@collab_mcp.tool()
def get_template(template_id: str) -> Dict:
    """Get details of a specific session template. See the plan and rules before using.

    AUTOMATIC TRIGGERS - Call this when:
    - You want to review a template before creating a session
    - Checking what tasks are in a template's plan
    - User asks about a specific template

    PARAMETERS:
    - template_id: Template identifier (e.g., 'deep_research', 'code_review')
    """
    try:
        from .templates import get_template
        template = get_template(template_id)
        if template is None:
            return {"error": f"Template '{template_id}' not found", "error_type": "template_not_found", "success": False}
        return template
    except Exception as e:
        return _handle_tool_error("get_template", e)


@collab_mcp.tool()
def create_from_template(
    template_id: str,
    title: str,
    task_description: str,
    created_by: str = "orchestrator",
) -> Dict:
    """Create a session from a predefined template. Structured plan + rules in one step.

    AUTOMATIC TRIGGERS - Call this when:
    - User asks to start a session with a template
    - You want a pre-built plan instead of creating tasks manually
    - Starting common workflows (deep research, code review, etc.)

    WORKFLOW POSITION: Alternative to create_session when you want a structured plan.

    PARAMETERS:
    - template_id: Template to use (e.g., 'deep_research', 'code_review')
    - title: Session title
    - task_description: Specific task description for this session
    - created_by: Creator identifier (default: "orchestrator")
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

        with _collab_connection() as (conn, sessions_dir):
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
                    "Use session_context to understand the plan",
                    "Use send_message to assign tasks to agents",
                    "Agents can join using join_session",
                ],
            }
    except Exception as e:
        return _handle_tool_error("create_from_template", e)


@collab_mcp.tool()
def get_agent_sessions(
    agent_id: str,
    requesting_agent_id: str,
    status: Optional[str] = None,
) -> Dict:
    """Get all sessions an agent has participated in. Track agent's work history.

    AUTOMATIC TRIGGERS - Call this when:
    - User asks "what sessions have I been in?"
    - Looking for past work by a specific agent
    - Finding related sessions to continue work

    PARAMETERS:
    - agent_id: Agent identifier
    - requesting_agent_id: Must match agent_id (agents can only inspect their own sessions)
    - status: Filter by session status - "active", "completed", "terminated" (optional)
    """
    try:
        validate_agent_id(agent_id)
        validate_agent_id(requesting_agent_id)
        if agent_id != requesting_agent_id:
            return {
                "success": False,
                "error": "Agents can only inspect their own session membership",
                "error_type": "agent_not_authorized",
            }
        with _collab_connection() as (conn, _):
            from .multi_session import get_agent_sessions
            sessions = get_agent_sessions(conn, agent_id, status)
            return {
                "agent_id": agent_id,
                "sessions": sessions,
                "count": len(sessions),
            }
    except Exception as e:
        return _handle_tool_error("get_agent_sessions", e)


@collab_mcp.tool()
def sessions_summary(agent_id: str) -> Dict:
    """Get a summary of all active sessions. Quick overview of ongoing work.

    AUTOMATIC TRIGGERS - Call this when:
    - User asks "what's happening?" or "what sessions are active?"
    - Checking workload before joining a new session
    - Getting a high-level view of all current collaboration work

    PARAMETERS:
    - agent_id: Your agent ID (summary is scoped to sessions you joined)
    """
    try:
        validate_agent_id(agent_id)
        with _collab_connection() as (conn, _):
            from .multi_session import get_active_sessions_summary
            return get_active_sessions_summary(conn, agent_id=agent_id)
    except Exception as e:
        return _handle_tool_error("sessions_summary", e)


@collab_mcp.tool()
def search_sessions(
    query: str,
    agent_id: str,
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
        validate_agent_id(agent_id)
        limit = max(1, min(limit, 100))

        with _collab_connection() as (conn, _):
            from .multi_session import search_sessions_by_content
            results = search_sessions_by_content(conn, query, limit, status, agent_id=agent_id)
            return {
                "query": query,
                "results": results,
                "count": len(results),
            }
    except Exception as e:
        return _handle_tool_error("search_sessions", e)


@collab_mcp.tool()
def session_relationships(session_id: str, agent_id: str) -> Dict:
    """Find sessions related to a given session. Discover cross-session context.

    AUTOMATIC TRIGGERS - Call this when:
    - "What other sessions is this related to?"
    - Looking for prior work by the same team
    - Finding sessions that share agents or orchestrator

    Identifies related sessions based on shared agents or same orchestrator.

    PARAMETERS:
    - session_id: Base session to find relationships for
    - agent_id: Your agent ID (must belong to the session)
    """
    try:
        validate_session_id(session_id)
        validate_agent_id(agent_id)
        with _collab_connection() as (conn, _):
            _require_reader_access(conn, session_id, agent_id)
            from .multi_session import get_session_relationships
            return get_session_relationships(conn, session_id, agent_id=agent_id)
    except Exception as e:
        return _handle_tool_error("session_relationships", e)


@collab_mcp.tool()
def session_statistics(session_id: str, agent_id: str) -> Dict:
    """Get detailed statistics for a session. Messages, agents, artifacts, and timing.

    AUTOMATIC TRIGGERS - Call this when:
    - "How active was this session?"
    - Measuring session productivity
    - Comparing sessions by message volume

    Includes message counts, breakdown by type and agent, artifact count, and time range.

    PARAMETERS:
    - session_id: Session to get statistics for
    - agent_id: Your agent ID (must belong to the session)
    """
    try:
        validate_session_id(session_id)
        validate_agent_id(agent_id)
        with _collab_connection() as (conn, _):
            _require_reader_access(conn, session_id, agent_id)
            from .multi_session import get_session_statistics
            return get_session_statistics(conn, session_id)
    except Exception as e:
        return _handle_tool_error("session_statistics", e)


@collab_mcp.tool()
def list_models(
    search: Optional[str] = None,
    provider: Optional[str] = None,
    max_price_per_million: Optional[float] = None,
    context_length_min: Optional[int] = None,
    is_free: bool = False,
    force_refresh: bool = False,
) -> Dict:
    """Browse available models from OpenRouter API. Filter by provider, price, or context size.

    AUTOMATIC TRIGGERS - Call this when:
    - User asks what models are available
    - Choosing a model for a collab session
    - Comparing model pricing or context limits

    Requires OPENROUTER_API_KEY environment variable. Results cached for 1 hour.

    PARAMETERS:
    - search: Search term in model name or description (optional)
    - provider: Filter by provider like 'openai', 'anthropic', 'google' (optional)
    - max_price_per_million: Max combined input+output price per 1M tokens (optional)
    - context_length_min: Minimum context length in tokens (optional)
    - is_free: Only include free models (default: False)
    - force_refresh: Force fresh API call, ignoring cache (default: False)
    """
    try:
        sessions_dir = _get_sessions_dir()
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
    except Exception as e:
        return _handle_tool_error("list_models", e)


@collab_mcp.tool()
def get_model_details(model_id: str) -> Dict:
    """Get detailed information about a specific OpenRouter model. Pricing, context, description.

    AUTOMATIC TRIGGERS - Call this when:
    - You have a model ID and need full details
    - Checking pricing or context limits for a specific model
    - Evaluating if a model is suitable for a task

    Use list_models first to find model IDs.

    PARAMETERS:
    - model_id: Full model ID (e.g., 'anthropic/claude-sonnet-4')
    """
    try:
        sessions_dir = _get_sessions_dir()
        from .openrouter_client import fetch_openrouter_models, format_model_summary

        result = fetch_openrouter_models(sessions_dir, force_refresh=False)
        if result.get("error"):
            return result

        models = result["models"]
        model = next((m for m in models if m.get("id") == model_id), None)
        if model is None:
            return {"error": f"Model '{model_id}' not found. Use list_models to see available models.", "error_type": "model_not_found", "success": False}

        return {
            "model": model,
            "summary": format_model_summary(model),
        }
    except Exception as e:
        return _handle_tool_error("get_model_details", e)


@collab_mcp.tool()
def recommended_models(task_type: str) -> Dict:
    """Get recommended OpenRouter models for a specific task type. Pre-filtered best choices.

    AUTOMATIC TRIGGERS - Call this when:
    - "What model should I use for X?"
    - Choosing models for a session without browsing the full catalog
    - User asks for model recommendations

    Task types: research, coding, analysis, writing, summarization, orchestrator, worker.

    PARAMETERS:
    - task_type: What the model will be used for
    """
    try:
        sessions_dir = _get_sessions_dir()
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
    except Exception as e:
        return _handle_tool_error("recommended_models", e)


@collab_mcp.tool()
def help_collab(tool_name: Optional[str] = None) -> Dict:
    """Get help about all collab MCP tools or a specific tool.

    Call this with no arguments to see all available tools and their purposes.
    Call with a specific tool_name to get detailed usage instructions.

    Args:
        tool_name: Optional specific tool name to get help for
                   (e.g., 'create_session')

    Returns:
        Dict with tool descriptions and usage information
    """
    tools_info = {
        "create_session": {
            "description": "Create a new collaboration session for multi-agent research. First tool in collaboration workflow.",
            "args": {
                "title": "Short descriptive title for the session",
                "task_description": "Detailed description of the research task",
                "plan": "Optional list of task dicts with step, task, assigned_to",
                "rules": "Optional session rules dict (max_agents, require_assignment)",
                "created_by": "Identifier for the creating agent (default: 'orchestrator')",
            },
            "returns": "Dict with session_id, agent_id, and session info",
        },
        "join_session": {
            "description": "Join an existing collaboration session as an agent.",
            "args": {
                "session_id": "ID of the session to join",
                "model": "Your model identifier (e.g., 'gpt-codex', 'gemini-pro')",
                "capabilities": "Optional list of your capabilities",
            },
            "returns": "Dict with your agent_id and session context",
        },
        "list_sessions": {
            "description": "List collaboration sessions.",
            "args": {
                "status": "Filter by status (active, completed, terminated)",
                "limit": "Maximum number of sessions to return (default: 20)",
            },
            "returns": "Dict with list of sessions",
        },
        "get_session_state": {
            "description": "Get the current state of a collaboration session.",
            "args": {
                "session_id": "ID of the session",
                "agent_id": "Your agent ID (must belong to the session)",
            },
            "returns": "Dict with session state, tasks, and agents",
        },
        "update_session_state": {
            "description": "Update the session state (orchestrator only).",
            "args": {
                "session_id": "Target session",
                "state": "New state dict (will be merged with existing state)",
                "orchestrator_id": "The orchestrator's agent ID (for authorization)",
            },
            "returns": "Dict with updated state and version info",
        },
        "send_message": {
            "description": "Send a message to a collaboration session. Core communication tool.",
            "args": {
                "session_id": "Target session",
                "msg_type": "Type: task, result, question, answer, ack, update, artifact, complete, system",
                "content": "Message content",
                "to_agent": "Target agent ID (or None for broadcast)",
                "metadata": "Optional metadata dict",
                "from_agent": "Your agent ID (required)",
            },
            "returns": "Dict with message info",
        },
        "read_messages": {
            "description": "Read new messages from a session (offset-based, only returns unseen messages).",
            "args": {
                "session_id": "Session to read from",
                "agent_id": "Your agent ID (required for authorization and offset tracking)",
                "limit": "Max messages to return (default: 50)",
                "msg_types": "Filter by message types (optional)",
                "from_agent": "Filter by sender (optional)",
            },
            "returns": "Dict with messages and your current offset",
        },
        "poll_messages": {
            "description": "Wait for and read new messages (AUTONOMOUS LOOP tool). Blocks until new messages arrive. Use for continuous agent communication.",
            "args": {
                "session_id": "Session to monitor",
                "agent_id": "Your agent ID (required for offset tracking)",
                "timeout": "Max seconds to wait (default: 30, 0 = no wait)",
                "limit": "Max messages to return (default: 50)",
                "msg_types": "Filter by message types (optional)",
                "from_agent": "Filter by sender (optional)",
            },
            "usage": "Call in loop: poll → process → respond → repeat. Runs until session completes.",
            "returns": "Dict with messages, waited_seconds, timed_out flag, and session_status",
        },
        "tail_messages": {
            "description": "Read the last N messages from a session (quick status check).",
            "args": {
                "session_id": "Session to read from",
                "agent_id": "Your agent ID (must belong to the session)",
                "n": "Number of messages (default: 20)",
            },
            "returns": "Dict with the last N messages",
        },
        "read_message_range": {
            "description": "Read messages in a specific sequence range.",
            "args": {
                "session_id": "Session to read from",
                "start_seq": "Starting sequence number (inclusive)",
                "end_seq": "Ending sequence number (exclusive)",
                "agent_id": "Your agent ID (must belong to the session)",
            },
            "returns": "Dict with messages in the specified range",
        },
        "grep_messages": {
            "description": "Search session messages by keyword.",
            "args": {
                "session_id": "Session to search",
                "pattern": "Search term (supports FTS5 syntax)",
                "agent_id": "Your agent ID (must belong to the session)",
                "limit": "Max results (default: 50)",
                "msg_types": "Filter by message types (optional)",
            },
            "returns": "Dict with matching messages",
        },
        "session_context": {
            "description": "Get compiled context view of session. PRIMARY tool for understanding session state.",
            "args": {
                "session_id": "Session to get context for",
                "agent_id": "Your agent ID (for personalized context)",
                "max_messages": "Max recent messages to include (default: 20)",
            },
            "returns": "Dict with structured context AND a prompt-ready formatted string",
        },
        "save_artifact": {
            "description": "Save a research artifact (finding, analysis, summary) to the session.",
            "args": {
                "session_id": "Target session",
                "title": "Descriptive title for the artifact",
                "content": "Full artifact content (markdown recommended)",
                "created_by": "Your agent ID",
                "artifact_type": "Optional type (research_summary, analysis, code, data, etc.)",
                "tags": "Optional tags for categorization",
                "shared": "If True, save to shared directory (default: False)",
            },
            "returns": "Dict with artifact info",
        },
        "list_artifacts": {
            "description": "List artifacts in a session.",
            "args": {
                "session_id": "Target session",
                "agent_id": "Your agent ID (must belong to the session)",
                "created_by": "Filter by creator agent (optional)",
                "artifact_type": "Filter by type (optional)",
            },
            "returns": "Dict with list of artifacts",
        },
        "get_artifact": {
            "description": "Get the full content of a specific artifact.",
            "args": {
                "session_id": "Session containing the artifact",
                "artifact_id": "ID of the artifact to retrieve",
                "agent_id": "Your agent ID (must belong to the session)",
            },
            "returns": "Dict with artifact content and metadata",
        },
        "grep_artifacts": {
            "description": "Search artifact content by keyword.",
            "args": {
                "session_id": "Session to search",
                "pattern": "Search term",
                "agent_id": "Your agent ID (must belong to the session)",
                "created_by": "Filter by creator (optional)",
            },
            "returns": "Dict with matching artifacts and their matching lines",
        },
        "leave_session": {
            "description": "Leave a collaboration session gracefully.",
            "args": {
                "session_id": "Session to leave",
                "agent_id": "Your agent ID",
                "reason": "Optional reason for leaving",
            },
            "returns": "Dict with confirmation",
        },
        "terminate_session": {
            "description": "Terminate and complete a collaboration session (orchestrator only).",
            "args": {
                "session_id": "Session to terminate",
                "orchestrator_id": "The orchestrator's agent ID",
                "summary": "Optional final summary of the session's work",
            },
            "returns": "Dict with termination confirmation",
        },
        "export_to_library": {
            "description": "Export session artifacts as findings in the main OpenLMLib library.",
            "args": {
                "session_id": "Completed session to export",
                "project": "Project name for findings (defaults to session title)",
                "confidence": "Default confidence score (default: 0.8)",
                "tags": "Additional tags to apply to all findings",
                "artifact_ids": "Specific artifacts to export (None = all)",
                "include_summary": "Also export the session summary as a finding",
            },
            "returns": "Dict with export results",
        },
        "list_templates": {
            "description": "List available session templates for quick session creation.",
            "args": {},
            "returns": "Dict with list of templates",
        },
        "get_template": {
            "description": "Get details of a specific session template.",
            "args": {
                "template_id": "Template identifier (e.g., 'deep_research', 'code_review')",
            },
            "returns": "Dict with template details including plan and rules",
        },
        "create_from_template": {
            "description": "Create a session from a predefined template.",
            "args": {
                "template_id": "Template to use (e.g., 'deep_research', 'code_review')",
                "title": "Session title",
                "task_description": "Specific task description for this session",
                "created_by": "Creator identifier",
            },
            "returns": "Dict with session info",
        },
        "get_agent_sessions": {
            "description": "Get all sessions an agent has participated in.",
            "args": {
                "agent_id": "Agent identifier",
                "requesting_agent_id": "Must match agent_id",
                "status": "Filter by session status (optional)",
            },
            "returns": "Dict with list of sessions and participation info",
        },
        "sessions_summary": {
            "description": "Get a summary of all active sessions.",
            "args": {
                "agent_id": "Your agent ID (summary is scoped to sessions you joined)",
            },
            "returns": "Dict with counts of active sessions, agents, and messages",
        },
        "search_sessions": {
            "description": "Search across all sessions by message content using FTS5.",
            "args": {
                "query": "Search query (supports FTS5 syntax)",
                "agent_id": "Your agent ID (search is scoped to sessions you joined)",
                "status": "Filter by session status (optional)",
                "limit": "Max results (default: 20)",
            },
            "returns": "Dict with matching sessions ranked by relevance",
        },
        "session_relationships": {
            "description": "Find sessions related to a given session.",
            "args": {
                "session_id": "Base session to find relationships for",
                "agent_id": "Your agent ID (must belong to the base session)",
            },
            "returns": "Dict with related sessions grouped by relationship type",
        },
        "session_statistics": {
            "description": "Get detailed statistics for a session.",
            "args": {
                "session_id": "Session to get statistics for",
                "agent_id": "Your agent ID (must belong to the session)",
            },
            "returns": "Dict with session statistics",
        },
        "list_models": {
            "description": "List available models from OpenRouter API.",
            "args": {
                "search": "Search term in model name or description",
                "provider": "Filter by provider (e.g., 'openai', 'anthropic', 'google')",
                "max_price_per_million": "Max combined input+output price per 1M tokens",
                "context_length_min": "Minimum context length in tokens",
                "is_free": "Only include free models",
                "force_refresh": "Force fresh API call, ignoring cache",
            },
            "returns": "Dict with list of available models and their details",
        },
        "get_model_details": {
            "description": "Get detailed information about a specific OpenRouter model.",
            "args": {
                "model_id": "Full model ID (e.g., 'anthropic/claude-sonnet-4')",
            },
            "returns": "Dict with model details including pricing, context, and description",
        },
        "recommended_models": {
            "description": "Get recommended OpenRouter models for a specific task type.",
            "args": {
                "task_type": "Task type (research, coding, analysis, writing, summarization, orchestrator, worker)",
            },
            "returns": "Dict with recommended model IDs and their details",
        },
        "help_collab": {
            "description": "Get help about all collab MCP tools or a specific tool (this tool).",
            "args": {
                "tool_name": "Optional specific tool name to get help for",
            },
            "returns": "Dict with tool descriptions and usage information",
        },
    }

    if tool_name:
        if tool_name in tools_info:
            return {
                "tool": tool_name,
                **tools_info[tool_name],
            }
        else:
            return {
                "error": f"Tool '{tool_name}' not found",
                "available_tools": sorted(tools_info.keys()),
            }

    categories = {
        "Session Management": [
            "create_session",
            "join_session",
            "list_sessions",
            "leave_session",
            "terminate_session",
        ],
        "Messaging": [
            "send_message",
            "read_messages",
            "tail_messages",
            "read_message_range",
            "grep_messages",
        ],
        "Context & State": [
            "session_context",
            "get_session_state",
            "update_session_state",
        ],
        "Artifacts": [
            "save_artifact",
            "list_artifacts",
            "get_artifact",
            "grep_artifacts",
        ],
        "Templates": [
            "list_templates",
            "get_template",
            "create_from_template",
        ],
        "Export": [
            "export_to_library",
        ],
        "Multi-Session": [
            "get_agent_sessions",
            "sessions_summary",
            "search_sessions",
            "session_relationships",
            "session_statistics",
        ],
        "Model Discovery": [
            "list_models",
            "get_model_details",
            "recommended_models",
        ],
        "Help": [
            "help_collab",
        ],
    }

    return {
        "description": "OpenLMlib CollabSessions MCP Tools - Multi-agent collaboration tools",
        "total_tools": len(tools_info),
        "categories": {
            cat: [
                {"name": name, "description": tools_info[name]["description"]}
                for name in names
            ]
            for cat, names in categories.items()
        },
        "usage": "Call help_collab with tool_name='<tool>' for detailed usage of a specific tool",
    }
