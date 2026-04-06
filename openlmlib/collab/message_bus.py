"""Message bus for CollabSessions.

Handles message creation with automatic sequence numbering,
JSONL shadow log writing for human-readable debugging, and
offset-based reading for efficient polling.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Dict, List, Optional

import sqlite3

from . import db
from .errors import VALID_MESSAGE_TYPES, InvalidMessageTypeError

logger = logging.getLogger(__name__)


class MessageBus:
    """Append-only message bus backed by SQLite + JSONL shadow log."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        sessions_dir: Path,
    ):
        self.conn = conn
        self.sessions_dir = sessions_dir

    def _session_dir(self, session_id: str) -> Path:
        return self.sessions_dir / session_id

    def _jsonl_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "messages.jsonl"

    def send(
        self,
        session_id: str,
        from_agent: str,
        msg_type: str,
        content: str,
        created_at: str,
        to_agent: Optional[str] = None,
        metadata: Optional[Dict] = None,
        from_model: Optional[str] = None,
        msg_id: Optional[str] = None,
    ) -> Dict:
        """Send a message to a session.

        Atomically inserts into SQLite and appends to JSONL shadow log.
        Auto-assigns the next sequence number.
        """
        if msg_type not in VALID_MESSAGE_TYPES:
            raise InvalidMessageTypeError(
                f"Invalid message type: {msg_type}. Allowed: {sorted(VALID_MESSAGE_TYPES)}"
            )

        if content is None:
            content = ""
        elif not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)

        msg_id = msg_id or f"msg_{uuid.uuid4().hex[:12]}"
        seq = db.get_max_seq(self.conn, session_id) + 1

        db.insert_message(
            self.conn,
            msg_id=msg_id,
            session_id=session_id,
            seq=seq,
            from_agent=from_agent,
            from_model=from_model,
            msg_type=msg_type,
            to_agent=to_agent,
            content=content,
            metadata=metadata,
            created_at=created_at,
        )

        self._append_jsonl(session_id, {
            "msg_id": msg_id,
            "session_id": session_id,
            "seq": seq,
            "from": from_agent,
            "from_model": from_model,
            "type": msg_type,
            "to": to_agent,
            "timestamp": created_at,
            "content": content,
            "metadata": metadata or {},
        })

        logger.debug(
            "Message sent: session=%s seq=%d type=%s from=%s",
            session_id, seq, msg_type, from_agent,
        )

        return {
            "msg_id": msg_id,
            "seq": seq,
            "session_id": session_id,
            "from_agent": from_agent,
            "msg_type": msg_type,
            "to_agent": to_agent,
            "created_at": created_at,
        }

    def read_new(
        self,
        session_id: str,
        last_seq: int,
        limit: int = 50,
        msg_types: Optional[List[str]] = None,
        from_agent: Optional[str] = None,
    ) -> List[Dict]:
        """Read messages since last_seq with optional filters."""
        return db.get_messages_since(
            self.conn,
            session_id=session_id,
            last_seq=last_seq,
            limit=limit,
            msg_types=msg_types,
            from_agent=from_agent,
        )

    def tail(self, session_id: str, n: int = 20) -> List[Dict]:
        """Get the last N messages."""
        return db.get_messages_tail(self.conn, session_id, n)

    def grep(
        self,
        session_id: str,
        pattern: str,
        limit: int = 50,
        msg_types: Optional[List[str]] = None,
    ) -> List[Dict]:
        """Search messages by keyword using FTS5."""
        return db.grep_messages(
            self.conn, session_id, pattern, limit, msg_types
        )

    def read_range(
        self,
        session_id: str,
        start_seq: int,
        end_seq: int,
    ) -> List[Dict]:
        """Read messages in a sequence range."""
        return db.get_message_range(self.conn, session_id, start_seq, end_seq)

    def _append_jsonl(self, session_id: str, entry: Dict) -> None:
        """Append a single JSON line to the shadow log."""
        jsonl_path = self._jsonl_path(session_id)
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        with open(jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def get_offset_file(self, session_id: str, agent_id: str) -> Path:
        """Get the path to an agent's offset tracking file."""
        offset_dir = self._session_dir(session_id) / "offsets"
        offset_dir.mkdir(parents=True, exist_ok=True)
        return offset_dir / f"{agent_id}.json"

    def load_offset(self, session_id: str, agent_id: str) -> int:
        """Load an agent's last-read sequence number."""
        offset_path = self.get_offset_file(session_id, agent_id)
        if offset_path.exists():
            try:
                with open(offset_path, "r") as f:
                    data = json.load(f)
                return int(data.get("last_seq", 0))
            except (json.JSONDecodeError, ValueError):
                return 0
        return 0

    def save_offset(self, session_id: str, agent_id: str, seq: int) -> None:
        """Save an agent's last-read sequence number."""
        offset_path = self.get_offset_file(session_id, agent_id)
        offset_path.parent.mkdir(parents=True, exist_ok=True)
        with open(offset_path, "w") as f:
            json.dump({"last_seq": seq, "agent_id": agent_id}, f)
