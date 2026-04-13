"""
SQLite storage layer for memory injection system.

Manages sessions, observations, and summaries in SQLite database.
Provides schema initialization and CRUD operations for memory data.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


class MemoryStorage:
    """SQLite storage for memory injection system."""

    def __init__(self, conn):
        """
        Initialize memory storage.

        Args:
            conn: SQLite connection object
        """
        self.conn = conn
        self._init_schema()

    def _init_schema(self):
        """Initialize memory tables and indexes."""
        cursor = self.conn.cursor()

        # Enable foreign key constraints
        cursor.execute("PRAGMA foreign_keys = ON")

        # Sessions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memory_sessions (
                session_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                ended_at TEXT,
                user_id TEXT,
                summary TEXT,
                observation_count INTEGER DEFAULT 0
            )
        """)

        # Observations table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memory_observations (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                tool_name TEXT,
                tool_input TEXT,
                tool_output TEXT,
                compressed_summary TEXT,
                tags TEXT,
                embedding_id TEXT,
                facts TEXT,
                concepts TEXT,
                obs_type TEXT,
                FOREIGN KEY (session_id) REFERENCES memory_sessions(session_id) ON DELETE CASCADE
            )
        """)

        # Summaries table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memory_summaries (
                session_id TEXT PRIMARY KEY,
                summary TEXT NOT NULL,
                key_facts TEXT,
                concepts TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES memory_sessions(session_id) ON DELETE CASCADE
            )
        """)

        # Indexes for performance
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_obs_session
            ON memory_observations(session_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_obs_timestamp
            ON memory_observations(timestamp)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_obs_tool
            ON memory_observations(tool_name)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_obs_type
            ON memory_observations(obs_type)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_obs_embedding
            ON memory_observations(embedding_id)
        """)

        self.conn.commit()
        logger.info("Memory storage schema initialized")

    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            logger.debug("Memory storage connection closed")

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - closes connection."""
        self.close()
        return False

    def create_session(
        self,
        session_id: str,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a new session record.

        Args:
            session_id: Unique session identifier
            user_id: Optional user/agent identifier

        Returns:
            Session metadata dict
        """
        cursor = self.conn.cursor()
        created_at = datetime.now(timezone.utc).isoformat()

        cursor.execute(
            """
            INSERT INTO memory_sessions (session_id, created_at, user_id, observation_count)
            VALUES (?, ?, ?, 0)
            """,
            (session_id, created_at, user_id)
        )

        self.conn.commit()

        return {
            "session_id": session_id,
            "created_at": created_at,
            "user_id": user_id,
            "observation_count": 0
        }

    def end_session(self, session_id: str) -> bool:
        """
        Mark a session as ended.

        Args:
            session_id: Session identifier

        Returns:
            True if session was found and ended
        """
        cursor = self.conn.cursor()
        ended_at = datetime.now(timezone.utc).isoformat()

        cursor.execute(
            """
            UPDATE memory_sessions
            SET ended_at = ?
            WHERE session_id = ? AND ended_at IS NULL
            """,
            (ended_at, session_id)
        )

        self.conn.commit()
        return cursor.rowcount > 0

    def add_observation(self, observation: Dict[str, Any]) -> str:
        """
        Add an observation record.

        Args:
            observation: Observation data dict with keys:
                - session_id (required)
                - tool_name (optional)
                - tool_input (optional)
                - tool_output (optional)
                - tags (optional, list)

        Returns:
            Observation ID
        """
        cursor = self.conn.cursor()

        obs_id = observation.get("id", f"obs_{uuid4().hex[:12]}")
        session_id = observation["session_id"]
        timestamp = observation.get(
            "timestamp", datetime.now(timezone.utc).isoformat()
        )
        tool_name = observation.get("tool_name")
        tool_input = observation.get("tool_input")
        tool_output = observation.get("tool_output")
        tags = json.dumps(observation.get("tags", []))

        cursor.execute(
            """
            INSERT INTO memory_observations
            (id, session_id, timestamp, tool_name, tool_input, tool_output, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (obs_id, session_id, timestamp, tool_name, tool_input, tool_output, tags)
        )

        # Update session observation count
        cursor.execute(
            """
            UPDATE memory_sessions
            SET observation_count = observation_count + 1
            WHERE session_id = ?
            """,
            (session_id,)
        )

        self.conn.commit()

        logger.debug(f"Added observation {obs_id} for session {session_id}")
        return obs_id

    def update_observation_compression(
        self,
        obs_id: str,
        compressed: Dict[str, Any]
    ) -> bool:
        """
        Update observation with compressed summary data.

        Args:
            obs_id: Observation ID
            compressed: Compressed summary dict with keys:
                - title, subtitle, narrative, facts, concepts, type

        Returns:
            True if observation was updated
        """
        cursor = self.conn.cursor()

        cursor.execute(
            """
            UPDATE memory_observations
            SET compressed_summary = ?,
                facts = ?,
                concepts = ?,
                obs_type = ?
            WHERE id = ?
            """,
            (
                compressed.get("narrative"),
                json.dumps(compressed.get("facts", [])),
                json.dumps(compressed.get("concepts", [])),
                compressed.get("type"),
                obs_id
            )
        )

        self.conn.commit()
        return cursor.rowcount > 0

    def get_session_observations(
        self,
        session_id: str,
        limit: int = 100,
        include_compressed: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Get observations for a session.

        Args:
            session_id: Session identifier
            limit: Max observations to return
            include_compressed: Whether to include compressed summaries

        Returns:
            List of observation dicts
        """
        cursor = self.conn.cursor()

        if include_compressed:
            cursor.execute(
                """
                SELECT id, session_id, timestamp, tool_name,
                       tool_input, tool_output, compressed_summary,
                       tags, facts, concepts, obs_type
                FROM memory_observations
                WHERE session_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (session_id, limit)
            )
        else:
            cursor.execute(
                """
                SELECT id, session_id, timestamp, tool_name,
                       tool_input, tool_output
                FROM memory_observations
                WHERE session_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (session_id, limit)
            )

        rows = cursor.fetchall()
        observations = []

        for row in rows:
            obs = {
                "id": row[0],
                "session_id": row[1],
                "timestamp": row[2],
                "tool_name": row[3],
                "tool_input": row[4],
                "tool_output": row[5],
            }

            if include_compressed and len(row) > 6:
                obs["compressed_summary"] = row[6]
                obs["tags"] = json.loads(row[7]) if row[7] else []
                obs["facts"] = json.loads(row[8]) if row[8] else []
                obs["concepts"] = json.loads(row[9]) if row[9] else []
                obs["obs_type"] = row[10]

            observations.append(obs)

        # Reverse to get chronological order
        observations.reverse()
        return observations

    def get_observations_by_ids(
        self,
        ids: List[str]
    ) -> List[Dict[str, Any]]:
        """
        Get observations by their IDs.

        Args:
            ids: List of observation IDs

        Returns:
            List of observation dicts
        """
        if not ids:
            return []

        cursor = self.conn.cursor()
        placeholders = ",".join("?" * len(ids))

        cursor.execute(
            f"""
            SELECT id, session_id, timestamp, tool_name,
                   tool_input, tool_output, compressed_summary,
                   tags, facts, concepts, obs_type
            FROM memory_observations
            WHERE id IN ({placeholders})
            ORDER BY timestamp ASC
            """,
            ids
        )

        rows = cursor.fetchall()
        observations = []

        for row in rows:
            observations.append({
                "id": row[0],
                "session_id": row[1],
                "timestamp": row[2],
                "tool_name": row[3],
                "tool_input": row[4],
                "tool_output": row[5],
                "compressed_summary": row[6],
                "tags": json.loads(row[7]) if row[7] else [],
                "facts": json.loads(row[8]) if row[8] else [],
                "concepts": json.loads(row[9]) if row[9] else [],
                "obs_type": row[10],
            })

        return observations

    def save_summary(
        self,
        session_id: str,
        summary: Dict[str, Any]
    ) -> bool:
        """
        Save session summary.

        Args:
            session_id: Session identifier
            summary: Summary dict with keys:
                - summary, key_facts, concepts

        Returns:
            True if summary was saved
        """
        cursor = self.conn.cursor()
        created_at = datetime.now(timezone.utc).isoformat()

        # Upsert summary
        cursor.execute(
            """
            INSERT OR REPLACE INTO memory_summaries
            (session_id, summary, key_facts, concepts, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                session_id,
                summary.get("summary", ""),
                json.dumps(summary.get("key_facts", [])),
                json.dumps(summary.get("concepts", [])),
                created_at
            )
        )

        self.conn.commit()
        return cursor.rowcount > 0

    def get_session_summary(
        self,
        session_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get summary for a session.

        Args:
            session_id: Session identifier

        Returns:
            Summary dict or None if not found
        """
        cursor = self.conn.cursor()

        cursor.execute(
            """
            SELECT session_id, summary, key_facts, concepts, created_at
            FROM memory_summaries
            WHERE session_id = ?
            """,
            (session_id,)
        )

        row = cursor.fetchone()
        if not row:
            return None

        return {
            "session_id": row[0],
            "summary": row[1],
            "key_facts": json.loads(row[2]) if row[2] else [],
            "concepts": json.loads(row[3]) if row[3] else [],
            "created_at": row[4],
        }

    def search_observations(
        self,
        query: str,
        limit: int = 50,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Search observations by query text.

        Args:
            query: Search query string
            limit: Max results to return
            filters: Optional filter dict (tool_name, obs_type, session_id)

        Returns:
            List of matching observation dicts
        """
        cursor = self.conn.cursor()

        # Build query with optional filters
        where_clauses = []
        params = []

        if filters:
            if filters.get("tool_name"):
                where_clauses.append("tool_name = ?")
                params.append(filters["tool_name"])
            if filters.get("obs_type"):
                where_clauses.append("obs_type = ?")
                params.append(filters["obs_type"])
            if filters.get("session_id"):
                where_clauses.append("session_id = ?")
                params.append(filters["session_id"])

        # Add text search (escape LIKE special characters)
        if query:
            where_clauses.append(
                "(tool_output LIKE ? OR compressed_summary LIKE ? OR tool_input LIKE ?)"
            )
            search_pattern = f"%{self._escape_like(query)}%"
            params.extend([search_pattern, search_pattern, search_pattern])

        where_sql = (
            "WHERE " + " AND ".join(where_clauses)
            if where_clauses
            else ""
        )

        cursor.execute(
            f"""
            SELECT id, session_id, timestamp, tool_name,
                   tool_input, tool_output, compressed_summary,
                   tags, facts, concepts, obs_type
            FROM memory_observations
            {where_sql}
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            params + [limit]
        )

        rows = cursor.fetchall()
        observations = []

        for row in rows:
            observations.append({
                "id": row[0],
                "session_id": row[1],
                "timestamp": row[2],
                "tool_name": row[3],
                "tool_input": row[4],
                "tool_output": row[5],
                "compressed_summary": row[6],
                "tags": json.loads(row[7]) if row[7] else [],
                "facts": json.loads(row[8]) if row[8] else [],
                "concepts": json.loads(row[9]) if row[9] else [],
                "obs_type": row[10],
            })

        return observations

    def get_recent_observations(
        self,
        limit: int = 50,
        session_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get most recent observations across all sessions or a specific session.

        Args:
            limit: Max observations to return
            session_id: Optional session filter

        Returns:
            List of observation dicts
        """
        cursor = self.conn.cursor()

        if session_id:
            cursor.execute(
                """
                SELECT id, session_id, timestamp, tool_name,
                       tool_input, tool_output, compressed_summary,
                       tags, facts, concepts, obs_type
                FROM memory_observations
                WHERE session_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (session_id, limit)
            )
        else:
            cursor.execute(
                """
                SELECT id, session_id, timestamp, tool_name,
                       tool_input, tool_output, compressed_summary,
                       tags, facts, concepts, obs_type
                FROM memory_observations
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (limit,)
            )

        rows = cursor.fetchall()
        observations = []

        for row in rows:
            observations.append({
                "id": row[0],
                "session_id": row[1],
                "timestamp": row[2],
                "tool_name": row[3],
                "tool_input": row[4],
                "tool_output": row[5],
                "compressed_summary": row[6],
                "tags": json.loads(row[7]) if row[7] else [],
                "facts": json.loads(row[8]) if row[8] else [],
                "concepts": json.loads(row[9]) if row[9] else [],
                "obs_type": row[10],
            })

        # Reverse to get chronological order
        observations.reverse()
        return observations

    def _escape_like(self, s: str) -> str:
        """Escape LIKE special characters to prevent wildcard matching."""
        return s.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')

    def get_session_stats(self, session_id: str) -> Dict[str, Any]:
        """
        Get statistics for a session.

        Args:
            session_id: Session identifier

        Returns:
            Stats dict with observation counts and types
        """
        cursor = self.conn.cursor()

        # Get session info
        cursor.execute(
            """
            SELECT session_id, created_at, ended_at, user_id, observation_count
            FROM memory_sessions
            WHERE session_id = ?
            """,
            (session_id,)
        )

        session_row = cursor.fetchone()
        if not session_row:
            return {"error": "Session not found"}

        # Get observation type breakdown
        cursor.execute(
            """
            SELECT obs_type, COUNT(*) as count
            FROM memory_observations
            WHERE session_id = ?
            GROUP BY obs_type
            ORDER BY count DESC
            """,
            (session_id,)
        )

        type_counts = {}
        for row in cursor.fetchall():
            type_counts[row[0] or "unknown"] = row[1]

        return {
            "session_id": session_row[0],
            "created_at": session_row[1],
            "ended_at": session_row[2],
            "user_id": session_row[3],
            "observation_count": session_row[4],
            "type_breakdown": type_counts,
        }

    def cleanup_old_sessions(self, max_age_days: int = 30) -> int:
        """
        Clean up sessions older than max_age_days.
        Uses ON DELETE CASCADE for dependent tables.

        Args:
            max_age_days: Maximum age in days

        Returns:
            Number of sessions cleaned up
        """
        from datetime import timedelta

        cursor = self.conn.cursor()
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=max_age_days)
        ).isoformat()

        # Get old session IDs
        cursor.execute(
            """
            SELECT session_id FROM memory_sessions
            WHERE created_at < ? AND ended_at IS NOT NULL
            """,
            (cutoff,)
        )

        old_session_ids = [row[0] for row in cursor.fetchall()]

        if not old_session_ids:
            return 0

        # Delete sessions (CASCADE deletes observations and summaries)
        placeholders = ",".join("?" * len(old_session_ids))
        cursor.execute(
            f"""
            DELETE FROM memory_sessions
            WHERE session_id IN ({placeholders})
            """,
            old_session_ids
        )

        self.conn.commit()
        count = len(old_session_ids)
        logger.info(f"Cleaned up {count} old sessions")
        return count
