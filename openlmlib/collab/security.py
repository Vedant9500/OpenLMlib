"""Input validation and security utilities for CollabSessions.

Integrates sanitization.py for prompt injection mitigation, validates
all inputs at MCP tool boundaries, enforces session access control,
and prevents path traversal attacks.
"""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import Optional

from . import db
from .errors import (
    AgentNotFoundError,
    AgentNotAuthorizedError,
    InvalidMessageTypeError,
    MessageTooLongError,
    SecurityError,
    SessionNotFoundError,
    SessionNotActiveError,
    VALID_MESSAGE_TYPES,
)

SESSION_ID_RE = re.compile(r"^sess_\d{8}_[a-f0-9]{8}$")
AGENT_ID_RE = re.compile(r"^agent_[a-zA-Z0-9_\-]{1,30}_[a-f0-9]{4,10}$")
ARTIFACT_ID_RE = re.compile(r"^art_[a-f0-9]{8}$")
TASK_ID_RE = re.compile(r"^task_[a-f0-9]{6}$")


def validate_session_id(session_id: str) -> str:
    """Validate and return a safe session ID.

    Raises:
        SecurityError: If session_id format is invalid
    """
    if not session_id or not isinstance(session_id, str):
        raise SecurityError("session_id is required")
    if ".." in session_id or "/" in session_id or "\\" in session_id:
        raise SecurityError("session_id contains path traversal characters")
    if len(session_id) > 64:
        raise SecurityError("session_id is too long")
    return session_id.strip()


def validate_agent_id(agent_id: str) -> str:
    """Validate and return a safe agent ID.

    Raises:
        SecurityError: If agent_id format is invalid
    """
    if not agent_id or not isinstance(agent_id, str):
        raise SecurityError("agent_id is required")
    if ".." in agent_id or "/" in agent_id or "\\" in agent_id:
        raise SecurityError("agent_id contains path traversal characters")
    if len(agent_id) > 64:
        raise SecurityError("agent_id is too long")
    return agent_id.strip()


def validate_artifact_id(artifact_id: str) -> str:
    """Validate artifact ID format."""
    if not artifact_id or not isinstance(artifact_id, str):
        raise SecurityError("artifact_id is required")
    if ".." in artifact_id or "/" in artifact_id or "\\" in artifact_id:
        raise SecurityError("artifact_id contains path traversal characters")
    return artifact_id.strip()


def validate_message_type(msg_type: str) -> str:
    """Validate message type against allowed values.

    Raises:
        InvalidMessageTypeError: If msg_type is not valid
    """
    if msg_type not in VALID_MESSAGE_TYPES:
        raise InvalidMessageTypeError(
            f"Invalid message type: {msg_type}. "
            f"Allowed: {sorted(VALID_MESSAGE_TYPES)}"
        )
    return msg_type


def validate_message_content(content: str, max_length: int = 8000) -> str:
    """Validate message content length.

    Raises:
        MessageTooLongError: If content exceeds max_length
    """
    if content is None:
        return ""
    if not isinstance(content, str):
        content = str(content)
    if len(content) > max_length:
        raise MessageTooLongError(
            f"Message content too long: {len(content)} > {max_length}"
        )
    return content


def sanitize_content(content: str) -> str:
    """Sanitize content to prevent prompt injection.

    Uses the existing sanitization.py module.
    """
    from openlmlib.sanitization import sanitize_text
    return sanitize_text(content)


def verify_agent_in_session(
    conn: sqlite3.Connection,
    agent_id: str,
    session_id: str,
) -> dict:
    """Verify that an agent is a member of the given session.

    Raises:
        AgentNotFoundError: If agent does not exist
        AgentNotAuthorizedError: If agent is not in this session
    """
    row = conn.execute(
        "SELECT agent_id, session_id, role, status FROM agents WHERE agent_id = ?",
        (agent_id,),
    ).fetchone()
    if row is None:
        raise AgentNotFoundError(f"Agent {agent_id} not found")
    if row["session_id"] != session_id:
        raise AgentNotAuthorizedError(
            f"Agent {agent_id} is not a member of session {session_id}"
        )
    return {
        "agent_id": row["agent_id"],
        "role": row["role"],
        "status": row["status"],
    }


def verify_session_exists_and_active(
    conn: sqlite3.Connection,
    session_id: str,
) -> dict:
    """Verify session exists and is active.

    Raises:
        SessionNotFoundError: If session does not exist
        SessionNotActiveError: If session is not active
    """
    session = db.get_session(conn, session_id)
    if session is None:
        raise SessionNotFoundError(f"Session {session_id} not found")
    if session["status"] != "active":
        raise SessionNotActiveError(
            f"Session {session_id} is not active (status: {session['status']})"
        )
    return session


def verify_orchestrator(
    conn: sqlite3.Connection,
    session_id: str,
    agent_id: str,
) -> dict:
    """Verify that an agent is the orchestrator of the session.

    Raises:
        SessionNotFoundError: If session does not exist
        AgentNotAuthorizedError: If agent is not the orchestrator
    """
    session = verify_session_exists_and_active(conn, session_id)
    if session["orchestrator"] != agent_id:
        raise AgentNotAuthorizedError(
            f"Only the orchestrator can perform this action. "
            f"Orchestrator: {session['orchestrator']}, Requested by: {agent_id}"
        )
    return session


def validate_safe_path(base: Path, target: str) -> Path:
    """Ensure a resolved path stays within the base directory.

    Prevents path traversal attacks via crafted filenames.

    Raises:
        SecurityError: If resolved path escapes base directory
    """
    resolved = (base / target).resolve()
    base_resolved = base.resolve()
    try:
        # Python 3.9+: resolved.is_relative_to(base_resolved)
        # Fallback for older Python
        common = os.path.commonpath([resolved, base_resolved])
        if common != str(base_resolved):
            raise SecurityError(
                f"Path traversal detected: {target} resolves outside {base}"
            )
    except ValueError:
        # Paths are on different drives (Windows) or no common path
        raise SecurityError(
            f"Path traversal detected: {target} resolves outside {base}"
        )
    return resolved
