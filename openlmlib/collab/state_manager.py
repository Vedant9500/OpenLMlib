"""State manager for CollabSessions.

Provides versioned, single-writer (orchestrator-only) session state
management with optimistic concurrency control.
"""

from __future__ import annotations

from typing import Dict, Optional

import sqlite3

from . import db


class StateManager:
    """Versioned session state with single-writer enforcement."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get_state(self, session_id: str) -> Optional[Dict]:
        """Get current session state."""
        return db.get_session_state(self.conn, session_id)

    def update_state(
        self,
        session_id: str,
        state: Dict,
        updated_by: str,
        updated_at: str,
        expected_version: Optional[int] = None,
    ) -> bool:
        """Update session state with version check.

        Returns True if update succeeded, False on version mismatch.
        """
        return db.update_session_state(
            self.conn, session_id, state, updated_by, updated_at, expected_version
        )

    def update_task_state(
        self,
        session_id: str,
        task_id: str,
        status: str,
        started_at: Optional[str] = None,
        completed_at: Optional[str] = None,
    ) -> None:
        """Update a task's status."""
        db.update_task_status(self.conn, task_id, status, started_at, completed_at)

    def bump_activity(self, session_id: str, updated_at: str) -> None:
        """Update the last_activity timestamp in session state."""
        current = self.get_state(session_id)
        if current:
            state = current["state"]
            state["last_activity"] = updated_at
            self.update_state(session_id, state, "system", updated_at, current["version"])
