"""Custom exception types for CollabSessions.

Provides domain-specific exceptions that replace generic ValueError usage,
enabling callers to handle different error categories appropriately.
"""

from __future__ import annotations


class CollabError(Exception):
    """Base exception for all CollabSessions errors."""


class SessionNotFoundError(CollabError):
    """Raised when a session ID does not exist."""


class SessionNotActiveError(CollabError):
    """Raised when a session exists but is not in 'active' status."""


class SessionFullError(CollabError):
    """Raised when a session has reached its maximum agent capacity."""


class AgentNotFoundError(CollabError):
    """Raised when an agent ID does not exist."""


class AgentNotAuthorizedError(CollabError):
    """Raised when an agent attempts an action it is not permitted to do."""


class StateConflictError(CollabError):
    """Raised when a state update fails due to version mismatch."""


class ArtifactNotFoundError(CollabError):
    """Raised when an artifact ID does not exist."""


class TemplateNotFoundError(CollabError):
    """Raised when a template ID does not exist."""


class InvalidMessageTypeError(CollabError):
    """Raised when a message type is not in the allowed set."""


class MessageTooLongError(CollabError):
    """Raised when message content exceeds the configured maximum length."""


class InvalidRoleError(CollabError):
    """Raised when an agent role is not recognized."""


class DatabaseError(CollabError):
    """Raised when a database operation fails unexpectedly."""


class FilesystemError(CollabError):
    """Raised when a file or directory operation fails."""


class SecurityError(CollabError):
    """Raised when a security validation fails (e.g., path traversal, injection)."""


VALID_MESSAGE_TYPES = frozenset({
    "task", "result", "question", "answer", "ack",
    "update", "artifact", "system", "complete", "summary",
})

VALID_ROLES = frozenset({"orchestrator", "worker", "observer"})

VALID_SESSION_STATUSES = frozenset({"active", "paused", "completed", "terminated"})

VALID_AGENT_STATUSES = frozenset({"active", "inactive", "left"})

VALID_TASK_STATUSES = frozenset({"pending", "in_progress", "completed", "cancelled"})


def make_error_response(message: str, error_type: str = "error") -> dict:
    """Create a standardized error response dict for MCP tools.

    Args:
        message: Human-readable error description
        error_type: Machine-readable error category

    Returns:
        Dict with "success": False and error details
    """
    return {
        "success": False,
        "error": message,
        "error_type": error_type,
    }


def error_from_exception(exc: Exception) -> dict:
    """Convert a CollabSessions exception to a standardized error response.

    Args:
        exc: The exception to convert

    Returns:
        Dict suitable for MCP tool return
    """
    mapping = {
        SessionNotFoundError: "session_not_found",
        SessionNotActiveError: "session_not_active",
        SessionFullError: "session_full",
        AgentNotFoundError: "agent_not_found",
        AgentNotAuthorizedError: "agent_not_authorized",
        StateConflictError: "state_conflict",
        ArtifactNotFoundError: "artifact_not_found",
        TemplateNotFoundError: "template_not_found",
        InvalidMessageTypeError: "invalid_message_type",
        MessageTooLongError: "message_too_long",
        InvalidRoleError: "invalid_role",
        DatabaseError: "database_error",
        FilesystemError: "filesystem_error",
        SecurityError: "security_error",
    }
    error_type = mapping.get(type(exc), "unknown_error")
    return make_error_response(str(exc), error_type)
