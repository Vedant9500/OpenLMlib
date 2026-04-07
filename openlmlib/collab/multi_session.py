"""Multi-session support for CollabSessions.

Provides cross-session queries, session linking, and agent
participation tracking across multiple sessions.
"""

from __future__ import annotations

import sqlite3
from typing import Dict, List, Optional


def get_agent_sessions(conn: sqlite3.Connection, agent_id: str, status: Optional[str] = None) -> List[Dict]:
    """Get all sessions an agent has participated in.

    Args:
        conn: SQLite connection
        agent_id: Agent identifier
        status: Optional status filter (active, completed, terminated)

    Returns:
        List of session dicts with participation info
    """
    query = """
        SELECT s.session_id, s.title, s.status, s.orchestrator,
               s.created_at, s.updated_at,
               a.role as agent_role, a.joined_at, a.last_seen
        FROM agents a
        JOIN sessions s ON a.session_id = s.session_id
        WHERE a.agent_id = ?
    """
    params: list = [agent_id]

    if status:
        query += " AND s.status = ?"
        params.append(status)

    query += " ORDER BY s.updated_at DESC"

    cursor = conn.execute(query, params)
    rows = cursor.fetchall()
    return [dict(row) for row in rows]


def get_active_sessions_summary(
    conn: sqlite3.Connection,
    agent_id: Optional[str] = None,
) -> Dict:
    """Get a summary of all active sessions.

    Returns:
        Dict with active session count, total agents, total messages
    """
    session_filter = ""
    params: list = []
    if agent_id:
        session_filter = (
            " AND s.session_id IN (SELECT session_id FROM agents WHERE agent_id = ?)"
        )
        params.append(agent_id)

    active_sessions = conn.execute(
        f"SELECT COUNT(*) as count FROM sessions s WHERE s.status = 'active'{session_filter}",
        params,
    ).fetchone()["count"]

    total_agents = conn.execute(
        "SELECT COUNT(DISTINCT a.agent_id) FROM agents a "
        "JOIN sessions s ON a.session_id = s.session_id "
        f"WHERE s.status = 'active' AND a.status = 'active'{session_filter}",
        params,
    ).fetchone()[0]

    total_messages = conn.execute(
        "SELECT COUNT(*) FROM messages m "
        "JOIN sessions s ON m.session_id = s.session_id "
        f"WHERE s.status = 'active'{session_filter}",
        params,
    ).fetchone()[0]

    return {
        "active_sessions": active_sessions,
        "total_active_agents": total_agents,
        "total_active_messages": total_messages,
    }


def search_sessions_by_content(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 20,
    status: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> List[Dict]:
    """Search across all sessions by message content using FTS5.

    Args:
        conn: SQLite connection
        query: Search query (FTS5 syntax supported)
        limit: Max results
        status: Optional status filter

    Returns:
        List of sessions with matching messages
    """
    sql = """
        SELECT DISTINCT s.session_id, s.title, s.status, s.created_at,
               COUNT(m.msg_id) as match_count
        FROM messages_fts fts
        JOIN messages m ON m.rowid = fts.rowid
        JOIN sessions s ON m.session_id = s.session_id
        WHERE messages_fts MATCH ?
    """
    params: list = [query]

    if status:
        sql += " AND s.status = ?"
        params.append(status)
    if agent_id:
        sql += " AND s.session_id IN (SELECT session_id FROM agents WHERE agent_id = ?)"
        params.append(agent_id)

    sql += " GROUP BY s.session_id ORDER BY match_count DESC LIMIT ?"
    params.append(limit)

    cursor = conn.execute(sql, params)
    return [dict(row) for row in cursor.fetchall()]


def get_session_relationships(
    conn: sqlite3.Connection,
    session_id: str,
    agent_id: Optional[str] = None,
) -> Dict:
    """Get related sessions based on shared agents or similar content.

    Args:
        conn: SQLite connection
        session_id: Base session to find relationships for

    Returns:
        Dict with related sessions grouped by relationship type
    """
    agents_in_session = conn.execute(
        "SELECT DISTINCT agent_id FROM agents WHERE session_id = ?",
        (session_id,)
    ).fetchall()
    agent_ids = [row["agent_id"] for row in agents_in_session]

    if not agent_ids:
        return {"by_shared_agents": [], "by_orchestrator": []}

    placeholders = ",".join("?" for _ in agent_ids)

    related_by_agents = conn.execute(
        f"""
        SELECT DISTINCT s.session_id, s.title, s.status,
               COUNT(DISTINCT a.agent_id) as shared_agent_count
        FROM agents a
        JOIN sessions s ON a.session_id = s.session_id
        WHERE a.agent_id IN ({placeholders})
          AND a.session_id != ?
        GROUP BY s.session_id
        ORDER BY shared_agent_count DESC
        LIMIT 10
        """,
        [*agent_ids, session_id]
    ).fetchall()

    creator = conn.execute(
        "SELECT created_by FROM sessions WHERE session_id = ?",
        (session_id,)
    ).fetchone()

    related_by_orchestrator = []
    if creator:
        rows = conn.execute(
            """
            SELECT session_id, title, status, created_at
            FROM sessions
            WHERE created_by = ? AND session_id != ?
            ORDER BY updated_at DESC
            LIMIT 10
            """,
            (creator["created_by"], session_id)
        ).fetchall()
        related_by_orchestrator = [dict(row) for row in rows]

    by_shared_agents = [dict(row) for row in related_by_agents]
    by_orchestrator = related_by_orchestrator

    if agent_id:
        allowed_rows = conn.execute(
            "SELECT session_id FROM agents WHERE agent_id = ?",
            (agent_id,),
        ).fetchall()
        allowed_session_ids = {row["session_id"] for row in allowed_rows}
        by_shared_agents = [
            row for row in by_shared_agents if row["session_id"] in allowed_session_ids
        ]
        by_orchestrator = [
            row for row in by_orchestrator if row["session_id"] in allowed_session_ids
        ]

    return {
        "by_shared_agents": by_shared_agents,
        "by_orchestrator": by_orchestrator,
    }


def get_cross_session_agent_activity(conn: sqlite3.Connection, agent_id: str, limit: int = 50) -> List[Dict]:
    """Get an agent's activity across all sessions.

    Args:
        conn: SQLite connection
        agent_id: Agent identifier
        limit: Max messages to return

    Returns:
        List of messages with session context
    """
    cursor = conn.execute(
        """
        SELECT m.msg_id, m.session_id, s.title as session_title,
               m.seq, m.msg_type, m.to_agent, m.content,
               m.created_at
        FROM messages m
        JOIN sessions s ON m.session_id = s.session_id
        WHERE m.from_agent = ?
        ORDER BY m.created_at DESC
        LIMIT ?
        """,
        (agent_id, limit)
    )
    return [dict(row) for row in cursor.fetchall()]


def get_session_statistics(conn: sqlite3.Connection, session_id: str) -> Dict:
    """Get detailed statistics for a session.

    Args:
        conn: SQLite connection
        session_id: Session identifier

    Returns:
        Dict with session statistics
    """
    msg_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM messages WHERE session_id = ?",
        (session_id,)
    ).fetchone()["cnt"]

    msg_by_type = conn.execute(
        "SELECT msg_type, COUNT(*) as cnt FROM messages WHERE session_id = ? GROUP BY msg_type",
        (session_id,)
    ).fetchall()

    msg_by_agent = conn.execute(
        "SELECT from_agent, COUNT(*) as cnt FROM messages WHERE session_id = ? GROUP BY from_agent ORDER BY cnt DESC",
        (session_id,)
    ).fetchall()

    artifact_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM artifacts WHERE session_id = ?",
        (session_id,)
    ).fetchone()["cnt"]

    first_msg = conn.execute(
        "SELECT created_at FROM messages WHERE session_id = ? ORDER BY seq ASC LIMIT 1",
        (session_id,)
    ).fetchone()

    last_msg = conn.execute(
        "SELECT created_at FROM messages WHERE session_id = ? ORDER BY seq DESC LIMIT 1",
        (session_id,)
    ).fetchone()

    return {
        "session_id": session_id,
        "total_messages": msg_count,
        "total_artifacts": artifact_count,
        "messages_by_type": {row["msg_type"]: row["cnt"] for row in msg_by_type},
        "messages_by_agent": {row["from_agent"]: row["cnt"] for row in msg_by_agent},
        "first_message_at": first_msg["created_at"] if first_msg else None,
        "last_message_at": last_msg["created_at"] if last_msg else None,
    }
