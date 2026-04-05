"""CollabSessions: Multi-agent collaboration subsystem for OpenLMLib."""

from .db import (
    connect_collab_db,
    init_collab_db,
    create_session,
    get_session,
    list_sessions,
    update_session_status,
    insert_agent,
    get_session_agents,
    insert_message,
    get_messages,
    get_messages_since,
    get_messages_tail,
    grep_messages,
    get_message_range,
    insert_task,
    update_task_status,
    get_session_tasks,
    insert_artifact,
    get_session_artifacts,
    get_session_state,
    update_session_state,
)
from .session import (
    create_collab_session,
    join_collab_session,
    leave_collab_session,
    terminate_collab_session,
)
from .message_bus import MessageBus
from .context_compiler import ContextCompiler
from .artifact_store import ArtifactStore
from .state_manager import StateManager

__all__ = [
    "connect_collab_db",
    "init_collab_db",
    "create_collab_session",
    "join_collab_session",
    "leave_collab_session",
    "terminate_collab_session",
    "MessageBus",
    "ContextCompiler",
    "ArtifactStore",
    "StateManager",
    "create_session",
    "get_session",
    "list_sessions",
    "update_session_status",
    "insert_agent",
    "get_session_agents",
    "insert_message",
    "get_messages",
    "get_messages_since",
    "get_messages_tail",
    "grep_messages",
    "get_message_range",
    "insert_task",
    "update_task_status",
    "get_session_tasks",
    "insert_artifact",
    "get_session_artifacts",
    "get_session_state",
    "update_session_state",
]
