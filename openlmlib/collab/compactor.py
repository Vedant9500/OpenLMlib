"""Session compaction and summarization for CollabSessions.

Generates compact summaries of session activity to manage context
window size for agents joining mid-session or catching up after
a long absence.

Inspired by Google ADK's context compaction pattern.
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional

import sqlite3

from ..schema import utc_now_iso
from . import db
from .message_bus import MessageBus
from .artifact_store import ArtifactStore
from .state_manager import StateManager


class SessionCompactor:
    """Generates and manages session summaries."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        sessions_dir,
        message_bus: MessageBus,
        artifact_store: ArtifactStore,
        state_manager: StateManager,
    ):
        self.conn = conn
        self.sessions_dir = sessions_dir
        self.message_bus = message_bus
        self.artifact_store = artifact_store
        self.state_manager = state_manager

    def generate_summary(
        self,
        session_id: str,
        from_seq: int = 0,
    ) -> Optional[str]:
        """Generate a human-readable summary of session activity since from_seq.

        This creates a factual, structured summary that agents can use
        to quickly understand what happened without reading every message.
        """
        messages = self.message_bus.read_new(session_id, from_seq, limit=500)
        if not messages:
            return None

        artifacts = self.artifact_store.list_artifacts(session_id)
        tasks = db.get_session_tasks(self.conn, session_id)
        agents = db.get_session_agents(self.conn, session_id)

        lines = []

        if from_seq == 0:
            lines.append("## Session Overview")
        else:
            lines.append(f"## Session Update (since message {from_seq})")

        lines.append("")

        task_lines = []
        completed = [t for t in tasks if t["status"] == "completed"]
        in_progress = [t for t in tasks if t["status"] == "in_progress"]
        pending = [t for t in tasks if t["status"] == "pending"]

        if completed:
            task_lines.append(f"Completed ({len(completed)}):")
            for t in completed:
                task_lines.append(f"  - Step {t['step_num']}: {t['description']}")

        if in_progress:
            task_lines.append(f"In Progress ({len(in_progress)}):")
            for t in in_progress:
                task_lines.append(f"  - Step {t['step_num']}: {t['description']}")

        if pending:
            task_lines.append(f"Pending ({len(pending)}):")
            for t in pending:
                assignee = t.get("assigned_to") or "unassigned"
                task_lines.append(f"  - Step {t['step_num']}: {t['description']} ({assignee})")

        if task_lines:
            lines.append("### Tasks")
            lines.extend(task_lines)
            lines.append("")

        agent_lines = []
        active = [a for a in agents if a["status"] == "active"]
        left = [a for a in agents if a["status"] == "left"]
        if active:
            agent_lines.append(f"Active ({len(active)}):")
            for a in active:
                agent_lines.append(f"  - {a['agent_id']} ({a['model']}) [{a['role']}]")
        if left:
            agent_lines.append(f"Left ({len(left)}):")
            for a in left:
                agent_lines.append(f"  - {a['agent_id']} ({a['model']})")

        if agent_lines:
            lines.append("### Agents")
            lines.extend(agent_lines)
            lines.append("")

        artifact_lines = []
        if artifacts:
            artifact_lines.append(f"Artifacts ({len(artifacts)}):")
            for a in artifacts:
                tag_str = f" [{', '.join(a.get('tags', []))}]" if a.get("tags") else ""
                artifact_lines.append(
                    f"  - {a['artifact_id']}: {a['title']} "
                    f"(by {a['created_by']}, {a.get('word_count', '?')} words){tag_str}"
                )

        if artifact_lines:
            lines.append("### Artifacts")
            lines.extend(artifact_lines)
            lines.append("")

        msg_summary = self._summarize_messages(messages)
        if msg_summary:
            lines.append("### Key Messages")
            lines.append(msg_summary)
            lines.append("")

        lines.append(f"Total messages in session: {len(messages) + from_seq}")
        lines.append(f"Summary covers messages {from_seq + 1} to {from_seq + len(messages)}")

        return "\n".join(lines)

    def compact_session(
        self,
        session_id: str,
        from_seq: int = 0,
        compacted_at: Optional[str] = None,
    ) -> Optional[Dict]:
        """Generate a summary, save it, and record the compaction point.

        Returns compaction metadata or None if no messages to summarize.
        """
        summary = self.generate_summary(session_id, from_seq)
        if summary is None:
            return None

        compacted_at = compacted_at or utc_now_iso()
        pre_summary_max_seq = db.get_max_seq(self.conn, session_id)

        file_path = self.artifact_store.save_summary(
            session_id, summary, compacted_at
        )

        # Use existing message_bus rather than creating a new one
        self.message_bus.send(
            session_id=session_id,
            from_agent="system",
            msg_type="summary",
            content=f"Session summary generated (messages {from_seq + 1}+). "
                    f"Saved to {file_path}",
            created_at=compacted_at,
            metadata={
                "from_seq": from_seq,
                "file_path": file_path,
            },
        )

        # Get actual current max seq from DB instead of undefined 'messages'
        current_max_seq = db.get_max_seq(self.conn, session_id)

        state_row = self.state_manager.get_state(session_id)
        if state_row:
            state = state_row["state"]
            state["last_compact_seq"] = current_max_seq
            state["last_compacted_at"] = compacted_at
            self.state_manager.update_state(
                session_id, state, "system", compacted_at, state_row.get("version")
            )

        return {
            "session_id": session_id,
            "from_seq": from_seq,
            "to_seq": pre_summary_max_seq,
            "file_path": file_path,
            "compacted_at": compacted_at,
            "summary_length": len(summary),
        }

    def check_and_compact(
        self,
        session_id: str,
        auto_compact_threshold: int = 50,
    ) -> Optional[Dict]:
        """Auto-compact if the session has exceeded the message threshold."""
        state_row = self.state_manager.get_state(session_id)
        if not state_row:
            return None

        state = state_row["state"]
        last_compact_seq = state.get("last_compact_seq", 0)

        # Use actual max_seq from DB instead of message_count counter
        current_max_seq = db.get_max_seq(self.conn, session_id)
        messages_since_compact = current_max_seq - last_compact_seq

        if messages_since_compact >= auto_compact_threshold:
            return self.compact_session(session_id, last_compact_seq)

        return None

    def _summarize_messages(self, messages: List[Dict]) -> str:
        """Generate a concise summary of message activity."""
        by_type = {}
        by_agent = {}
        key_events = []

        for msg in messages:
            msg_type = msg["msg_type"]
            from_agent = msg["from_agent"]

            by_type[msg_type] = by_type.get(msg_type, 0) + 1
            by_agent[from_agent] = by_agent.get(from_agent, 0) + 1

            if msg_type in ("task", "complete", "system"):
                content = msg["content"]
                if len(content) > 120:
                    content = content[:117] + "..."
                key_events.append(f"[{msg_type}] {from_agent}: {content}")

        lines = []

        if by_type:
            type_parts = [f"{k}: {v}" for k, v in sorted(by_type.items())]
            lines.append(f"Message types: {', '.join(type_parts)}")

        if by_agent:
            agent_parts = [f"{k}: {v}" for k, v in sorted(by_agent.items())]
            lines.append(f"Activity by agent: {', '.join(agent_parts)}")

        if key_events:
            lines.append("Key events:")
            for event in key_events[:10]:
                lines.append(f"  {event}")
            if len(key_events) > 10:
                lines.append(f"  ... and {len(key_events) - 10} more")

        return "\n".join(lines)
