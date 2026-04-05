"""SQLite database layer for CollabSessions.

Follows the same patterns as openlmlib/db.py: WAL mode, foreign keys,
row_factory, and FTS5 virtual tables.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional


COLLAB_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'paused', 'completed', 'terminated')),
    orchestrator TEXT NOT NULL,
    rules_json TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    msg_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    seq INTEGER NOT NULL,
    from_agent TEXT NOT NULL,
    from_model TEXT,
    msg_type TEXT NOT NULL CHECK (msg_type IN (
        'task', 'result', 'question', 'answer', 'ack',
        'update', 'artifact', 'system', 'complete', 'summary'
    )),
    to_agent TEXT,
    content TEXT NOT NULL,
    metadata_json TEXT,
    created_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content, metadata_json,
    content='messages', content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS messages_fts_insert AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content, metadata_json)
    VALUES (new.rowid, new.content, new.metadata_json);
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_delete AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content, metadata_json)
    VALUES ('delete', old.rowid, old.content, old.metadata_json);
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_update AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content, metadata_json)
    VALUES ('delete', old.rowid, old.content, old.metadata_json);
    INSERT INTO messages_fts(rowid, content, metadata_json)
    VALUES (new.rowid, new.content, new.metadata_json);
END;

CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    model TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('orchestrator', 'worker', 'observer')),
    capabilities_json TEXT,
    joined_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'inactive', 'left')),
    last_seen TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    step_num INTEGER NOT NULL,
    description TEXT NOT NULL,
    assigned_to TEXT,
    status TEXT NOT NULL CHECK (status IN ('pending', 'in_progress', 'completed', 'cancelled')),
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    created_by TEXT NOT NULL,
    title TEXT NOT NULL,
    artifact_type TEXT,
    file_path TEXT NOT NULL,
    tags_json TEXT,
    word_count INTEGER,
    created_at TEXT NOT NULL,
    referenced_in_messages_json TEXT
);

CREATE TABLE IF NOT EXISTS session_state (
    session_id TEXT PRIMARY KEY REFERENCES sessions(session_id),
    state_json TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL,
    updated_by TEXT
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, seq);
CREATE INDEX IF NOT EXISTS idx_messages_type ON messages(msg_type);
CREATE INDEX IF NOT EXISTS idx_messages_from ON messages(from_agent);
CREATE INDEX IF NOT EXISTS idx_messages_session_type ON messages(session_id, msg_type);
CREATE INDEX IF NOT EXISTS idx_agents_session ON agents(session_id);
CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);
CREATE INDEX IF NOT EXISTS idx_tasks_session ON tasks(session_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_artifacts_session ON artifacts(session_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_created_by ON artifacts(created_by);
"""


def connect_collab_db(db_path: Path) -> sqlite3.Connection:
    """Connect to the collab sessions database with optimized pragmas."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.execute("PRAGMA temp_store = MEMORY;")
    conn.execute("PRAGMA cache_size = -20000;")
    conn.execute("PRAGMA wal_autocheckpoint = 4000;")
    return conn


def init_collab_db(conn: sqlite3.Connection) -> None:
    """Initialize the collab sessions schema."""
    conn.executescript(COLLAB_SCHEMA)
    conn.commit()


def _json_dump(value) -> str:
    return json.dumps(value, separators=(",", ":"))


def _json_load(value: Optional[str], default=None):
    if value is None:
        return default
    return json.loads(value)


# ── Session CRUD ──────────────────────────────────────────────────────

def create_session(
    conn: sqlite3.Connection,
    session_id: str,
    title: str,
    created_by: str,
    created_at: str,
    description: Optional[str] = None,
    orchestrator: Optional[str] = None,
    rules: Optional[Dict] = None,
) -> Dict:
    """Create a new collaboration session."""
    orch = orchestrator or created_by
    with conn:
        conn.execute(
            """
            INSERT INTO sessions (session_id, title, description, created_by, created_at,
                                  status, orchestrator, rules_json, updated_at)
            VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?)
            """,
            (session_id, title, description, created_by, created_at,
             orch, _json_dump(rules or {}), created_at),
        )
        conn.execute(
            """
            INSERT INTO session_state (session_id, state_json, version, updated_at, updated_by)
            VALUES (?, ?, 1, ?, ?)
            """,
            (session_id, _json_dump({
                "session_id": session_id,
                "status": "active",
                "current_phase": "initialized",
                "active_tasks": [],
                "completed_tasks": [],
                "pending_tasks": [],
                "message_count": 0,
                "artifact_count": 0,
                "last_activity": created_at,
            }), created_at, created_by),
        )
    return {
        "session_id": session_id,
        "title": title,
        "status": "active",
        "orchestrator": orch,
        "created_at": created_at,
    }


def get_session(conn: sqlite3.Connection, session_id: str) -> Optional[Dict]:
    """Get session metadata."""
    row = conn.execute(
        "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["rules"] = _json_load(result.pop("rules_json"), {})
    return result


def list_sessions(
    conn: sqlite3.Connection,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict]:
    """List sessions with optional status filter."""
    if status:
        rows = conn.execute(
            """
            SELECT session_id, title, description, created_by, created_at,
                   status, orchestrator, updated_at
            FROM sessions
            WHERE status = ?
            ORDER BY updated_at DESC
            LIMIT ? OFFSET ?
            """,
            (status, limit, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT session_id, title, description, created_by, created_at,
                   status, orchestrator, updated_at
            FROM sessions
            ORDER BY updated_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
    return [dict(r) for r in rows]


def update_session_status(
    conn: sqlite3.Connection,
    session_id: str,
    status: str,
    updated_at: str,
) -> bool:
    """Update session status. Returns True if row was updated."""
    with conn:
        cursor = conn.execute(
            """
            UPDATE sessions SET status = ?, updated_at = ?
            WHERE session_id = ? AND status IN ('active', 'paused')
            """,
            (status, updated_at, session_id),
        )
    return cursor.rowcount > 0


# ── Agent CRUD ────────────────────────────────────────────────────────

def insert_agent(
    conn: sqlite3.Connection,
    agent_id: str,
    session_id: str,
    model: str,
    role: str,
    joined_at: str,
    capabilities: Optional[List[str]] = None,
) -> None:
    """Register an agent in a session."""
    with conn:
        conn.execute(
            """
            INSERT INTO agents (agent_id, session_id, model, role, capabilities_json,
                                joined_at, status, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, 'active', ?)
            """,
            (agent_id, session_id, model, role,
             _json_dump(capabilities or []), joined_at, joined_at),
        )


def get_session_agents(conn: sqlite3.Connection, session_id: str) -> List[Dict]:
    """Get all agents registered in a session."""
    rows = conn.execute(
        """
        SELECT agent_id, session_id, model, role, capabilities_json,
               joined_at, status, last_seen
        FROM agents
        WHERE session_id = ?
        ORDER BY joined_at ASC
        """,
        (session_id,),
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["capabilities"] = _json_load(d.pop("capabilities_json"), [])
        result.append(d)
    return result


def update_agent_status(
    conn: sqlite3.Connection,
    agent_id: str,
    status: str,
    last_seen: Optional[str] = None,
) -> None:
    """Update an agent's status."""
    with conn:
        if last_seen:
            conn.execute(
                "UPDATE agents SET status = ?, last_seen = ? WHERE agent_id = ?",
                (status, last_seen, agent_id),
            )
        else:
            conn.execute(
                "UPDATE agents SET status = ? WHERE agent_id = ?",
                (status, agent_id),
            )


# ── Message CRUD ──────────────────────────────────────────────────────

def insert_message(
    conn: sqlite3.Connection,
    msg_id: str,
    session_id: str,
    seq: int,
    from_agent: str,
    msg_type: str,
    content: str,
    created_at: str,
    from_model: Optional[str] = None,
    to_agent: Optional[str] = None,
    metadata: Optional[Dict] = None,
) -> None:
    """Append a message to the session (append-only)."""
    metadata_json = _json_dump(metadata) if metadata else None
    with conn:
        conn.execute(
            """
            INSERT INTO messages (msg_id, session_id, seq, from_agent, from_model,
                                  msg_type, to_agent, content, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (msg_id, session_id, seq, from_agent, from_model,
             msg_type, to_agent, content, metadata_json, created_at),
        )


def get_messages(
    conn: sqlite3.Connection,
    session_id: str,
    limit: int = 50,
    offset: int = 0,
    msg_types: Optional[List[str]] = None,
    from_agent: Optional[str] = None,
    to_agent: Optional[str] = None,
) -> List[Dict]:
    """Get messages for a session with optional filters."""
    sql = """
        SELECT msg_id, session_id, seq, from_agent, from_model, msg_type,
               to_agent, content, metadata_json, created_at
        FROM messages
        WHERE session_id = ?
    """
    params: list = [session_id]

    if msg_types:
        placeholders = ",".join("?" for _ in msg_types)
        sql += f" AND msg_type IN ({placeholders})"
        params.extend(msg_types)
    if from_agent:
        sql += " AND from_agent = ?"
        params.append(from_agent)
    if to_agent:
        sql += " AND (to_agent = ? OR to_agent IS NULL)"
        params.append(to_agent)

    sql += " ORDER BY seq ASC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = conn.execute(sql, params).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["metadata"] = _json_load(d.pop("metadata_json"), {})
        result.append(d)
    return result


def get_messages_since(
    conn: sqlite3.Connection,
    session_id: str,
    last_seq: int,
    limit: int = 50,
    msg_types: Optional[List[str]] = None,
    from_agent: Optional[str] = None,
) -> List[Dict]:
    """Get messages with seq > last_seq (offset-based polling)."""
    sql = """
        SELECT msg_id, session_id, seq, from_agent, from_model, msg_type,
               to_agent, content, metadata_json, created_at
        FROM messages
        WHERE session_id = ? AND seq > ?
    """
    params: list = [session_id, last_seq]

    if msg_types:
        placeholders = ",".join("?" for _ in msg_types)
        sql += f" AND msg_type IN ({placeholders})"
        params.extend(msg_types)
    if from_agent:
        sql += " AND from_agent = ?"
        params.append(from_agent)

    sql += " ORDER BY seq ASC LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["metadata"] = _json_load(d.pop("metadata_json"), {})
        result.append(d)
    return result


def get_messages_tail(
    conn: sqlite3.Connection,
    session_id: str,
    n: int = 20,
) -> List[Dict]:
    """Get the last N messages for a session."""
    rows = conn.execute(
        """
        SELECT msg_id, session_id, seq, from_agent, from_model, msg_type,
               to_agent, content, metadata_json, created_at
        FROM messages
        WHERE session_id = ?
        ORDER BY seq DESC
        LIMIT ?
        """,
        (session_id, n),
    ).fetchall()
    rows = list(reversed(rows))
    result = []
    for r in rows:
        d = dict(r)
        d["metadata"] = _json_load(d.pop("metadata_json"), {})
        result.append(d)
    return result


def get_message_range(
    conn: sqlite3.Connection,
    session_id: str,
    start_seq: int,
    end_seq: int,
) -> List[Dict]:
    """Get messages in a sequence range [start_seq, end_seq)."""
    rows = conn.execute(
        """
        SELECT msg_id, session_id, seq, from_agent, from_model, msg_type,
               to_agent, content, metadata_json, created_at
        FROM messages
        WHERE session_id = ? AND seq >= ? AND seq < ?
        ORDER BY seq ASC
        """,
        (session_id, start_seq, end_seq),
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["metadata"] = _json_load(d.pop("metadata_json"), {})
        result.append(d)
    return result


def grep_messages(
    conn: sqlite3.Connection,
    session_id: str,
    pattern: str,
    limit: int = 50,
    msg_types: Optional[List[str]] = None,
) -> List[Dict]:
    """Search messages by keyword using FTS5."""
    sql = """
        SELECT m.msg_id, m.session_id, m.seq, m.from_agent, m.from_model,
               m.msg_type, m.to_agent, m.content, m.metadata_json, m.created_at
        FROM messages_fts AS fts
        JOIN messages AS m ON m.rowid = fts.rowid
        WHERE m.session_id = ? AND messages_fts MATCH ?
    """
    params: list = [session_id, pattern]

    if msg_types:
        placeholders = ",".join("?" for _ in msg_types)
        sql += f" AND m.msg_type IN ({placeholders})"
        params.extend(msg_types)

    sql += " ORDER BY m.seq ASC LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["metadata"] = _json_load(d.pop("metadata_json"), {})
        result.append(d)
    return result


def get_max_seq(conn: sqlite3.Connection, session_id: str) -> int:
    """Get the highest sequence number for a session."""
    row = conn.execute(
        "SELECT COALESCE(MAX(seq), 0) as max_seq FROM messages WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    return int(row["max_seq"])


# ── Task CRUD ─────────────────────────────────────────────────────────

def insert_task(
    conn: sqlite3.Connection,
    task_id: str,
    session_id: str,
    step_num: int,
    description: str,
    created_at: str,
    assigned_to: Optional[str] = None,
) -> None:
    """Create a task in a session."""
    with conn:
        conn.execute(
            """
            INSERT INTO tasks (task_id, session_id, step_num, description,
                               assigned_to, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'pending', ?)
            """,
            (task_id, session_id, step_num, description, assigned_to, created_at),
        )


def update_task_status(
    conn: sqlite3.Connection,
    task_id: str,
    status: str,
    started_at: Optional[str] = None,
    completed_at: Optional[str] = None,
) -> None:
    """Update task status."""
    with conn:
        if started_at and status == "in_progress":
            conn.execute(
                "UPDATE tasks SET status = ?, started_at = ? WHERE task_id = ?",
                (status, started_at, task_id),
            )
        elif completed_at and status == "completed":
            conn.execute(
                "UPDATE tasks SET status = ?, completed_at = ? WHERE task_id = ?",
                (status, completed_at, task_id),
            )
        else:
            conn.execute(
                "UPDATE tasks SET status = ? WHERE task_id = ?",
                (status, task_id),
            )


def get_session_tasks(
    conn: sqlite3.Connection,
    session_id: str,
    status: Optional[str] = None,
) -> List[Dict]:
    """Get tasks for a session."""
    if status:
        rows = conn.execute(
            """
            SELECT * FROM tasks
            WHERE session_id = ? AND status = ?
            ORDER BY step_num ASC
            """,
            (session_id, status),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM tasks
            WHERE session_id = ?
            ORDER BY step_num ASC
            """,
            (session_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Artifact CRUD ─────────────────────────────────────────────────────

def insert_artifact(
    conn: sqlite3.Connection,
    artifact_id: str,
    session_id: str,
    created_by: str,
    title: str,
    file_path: str,
    created_at: str,
    artifact_type: Optional[str] = None,
    tags: Optional[List[str]] = None,
    word_count: Optional[int] = None,
    referenced_in_messages: Optional[List[str]] = None,
) -> None:
    """Register an artifact in the index."""
    with conn:
        conn.execute(
            """
            INSERT INTO artifacts (artifact_id, session_id, created_by, title,
                                   artifact_type, file_path, tags_json, word_count,
                                   created_at, referenced_in_messages_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (artifact_id, session_id, created_by, title, artifact_type,
             file_path, _json_dump(tags or []), word_count, created_at,
             _json_dump(referenced_in_messages or [])),
        )


def get_session_artifacts(
    conn: sqlite3.Connection,
    session_id: str,
    created_by: Optional[str] = None,
    artifact_type: Optional[str] = None,
) -> List[Dict]:
    """Get artifacts for a session."""
    sql = "SELECT * FROM artifacts WHERE session_id = ?"
    params: list = [session_id]
    if created_by:
        sql += " AND created_by = ?"
        params.append(created_by)
    if artifact_type:
        sql += " AND artifact_type = ?"
        params.append(artifact_type)
    sql += " ORDER BY created_at ASC"

    rows = conn.execute(sql, params).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["tags"] = _json_load(d.pop("tags_json"), [])
        d["referenced_in_messages"] = _json_load(
            d.pop("referenced_in_messages_json"), []
        )
        result.append(d)
    return result


# ── Session State ─────────────────────────────────────────────────────

def get_session_state(
    conn: sqlite3.Connection,
    session_id: str,
) -> Optional[Dict]:
    """Get the current session state."""
    row = conn.execute(
        "SELECT * FROM session_state WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["state"] = _json_load(result.pop("state_json"), {})
    return result


def update_session_state(
    conn: sqlite3.Connection,
    session_id: str,
    state: Dict,
    updated_by: str,
    updated_at: str,
    expected_version: Optional[int] = None,
) -> bool:
    """Atomically update session state with version check.

    Returns True if the update succeeded, False if version mismatch.
    """
    with conn:
        if expected_version is not None:
            cursor = conn.execute(
                """
                UPDATE session_state
                SET state_json = ?, version = version + 1, updated_at = ?, updated_by = ?
                WHERE session_id = ? AND version = ?
                """,
                (_json_dump(state), updated_at, updated_by,
                 session_id, expected_version),
            )
            return cursor.rowcount > 0
        else:
            conn.execute(
                """
                UPDATE session_state
                SET state_json = ?, version = version + 1, updated_at = ?, updated_by = ?
                WHERE session_id = ?
                """,
                (_json_dump(state), updated_at, updated_by, session_id),
            )
            return True
