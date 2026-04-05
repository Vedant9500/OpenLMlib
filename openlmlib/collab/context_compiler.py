"""Context compiler for CollabSessions.

Compiles a 'working context' view from the full session state,
implementing progressive disclosure so agents get only what they
need without blowing their context windows.

Inspired by Google ADK's "context as a compiled view" pattern.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import sqlite3

from . import db
from .message_bus import MessageBus
from .artifact_store import ArtifactStore


class ContextCompiler:
    """Compiles session state into agent-specific context views."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        message_bus: MessageBus,
        artifact_store: ArtifactStore,
    ):
        self.conn = conn
        self.message_bus = message_bus
        self.artifact_store = artifact_store

    def compile_context(
        self,
        session_id: str,
        agent_id: str,
        max_messages: int = 20,
    ) -> Dict:
        """Compile a complete context view for an agent.

        Returns a structured dict containing:
        - session_info: basic session metadata
        - summary: latest session summary (if exists)
        - recent_messages: last N messages with attribution
        - current_state: session state
        - my_tasks: tasks assigned to this agent
        - artifacts: list of available artifacts (references only, not content)
        """
        session = db.get_session(self.conn, session_id)
        if session is None:
            return {"error": f"Session {session_id} not found"}

        state_row = db.get_session_state(self.conn, session_id)
        state = state_row["state"] if state_row else {}

        summary = self.artifact_store.get_latest_summary(session_id)

        recent_messages = self.message_bus.tail(session_id, max_messages)
        formatted_messages = self._format_messages(recent_messages, agent_id)

        tasks = db.get_session_tasks(self.conn, session_id)
        my_tasks = [t for t in tasks if t.get("assigned_to") == agent_id]
        pending_tasks = [t for t in tasks if t.get("status") == "pending" and t.get("assigned_to") in (None, "any")]

        artifacts = self.artifact_store.list_artifacts(session_id)
        artifact_refs = [
            {
                "artifact_id": a["artifact_id"],
                "title": a["title"],
                "created_by": a["created_by"],
                "artifact_type": a.get("artifact_type"),
                "word_count": a.get("word_count"),
                "tags": a.get("tags", []),
            }
            for a in artifacts
        ]

        agents = db.get_session_agents(self.conn, session_id)
        active_agents = [
            {"agent_id": a["agent_id"], "model": a["model"], "role": a["role"]}
            for a in agents
            if a["status"] == "active"
        ]

        return {
            "session_info": {
                "session_id": session_id,
                "title": session["title"],
                "status": session["status"],
                "orchestrator": session["orchestrator"],
                "created_by": session["created_by"],
            },
            "your_identity": {
                "agent_id": agent_id,
                "role": next(
                    (a["role"] for a in agents if a["agent_id"] == agent_id),
                    "worker",
                ),
            },
            "summary": summary,
            "recent_messages": formatted_messages,
            "current_state": state,
            "my_tasks": my_tasks,
            "pending_tasks": pending_tasks,
            "artifacts": artifact_refs,
            "active_agents": active_agents,
        }

    def format_context_for_prompt(self, context: Dict) -> str:
        """Format a compiled context dict into a prompt-ready string."""
        if "error" in context:
            return f"ERROR: {context['error']}"

        lines = []
        info = context["session_info"]
        identity = context["your_identity"]

        lines.append(f"[Session: {info['title']}]")
        lines.append(f"[Status: {info['status']} | Orchestrator: {info['orchestrator']}]")
        lines.append(f"[Your role: {identity['role']} | Agent ID: {identity['agent_id']}]")
        lines.append("")

        if context.get("summary"):
            lines.append("=== SESSION SUMMARY ===")
            lines.append(context["summary"])
            lines.append("")

        if context.get("recent_messages"):
            lines.append(f"=== RECENT MESSAGES ({len(context['recent_messages'])}) ===")
            for msg in context["recent_messages"]:
                lines.append(msg)
            lines.append("")

        if context.get("my_tasks"):
            lines.append("=== YOUR CURRENT TASKS ===")
            for task in context["my_tasks"]:
                status_icon = {
                    "pending": "[ ]",
                    "in_progress": "[>]",
                    "completed": "[x]",
                }.get(task["status"], "[ ]")
                lines.append(
                    f"  {status_icon} Step {task['step_num']}: {task['description']} "
                    f"(status: {task['status']})"
                )
            lines.append("")

        if context.get("pending_tasks"):
            lines.append("=== UNASSIGNED TASKS ===")
            for task in context["pending_tasks"]:
                lines.append(f"  [ ] Step {task['step_num']}: {task['description']}")
            lines.append("")

        if context.get("artifacts"):
            lines.append(f"=== ARTIFACTS ({len(context['artifacts'])}) ===")
            for art in context["artifacts"]:
                tag_str = f" [{', '.join(art['tags'])}]" if art["tags"] else ""
                lines.append(
                    f"  - {art['artifact_id']}: {art['title']} "
                    f"(by {art['created_by']}, {art.get('word_count', '?')} words){tag_str}"
                )
            lines.append("")

        if context.get("active_agents"):
            lines.append(f"=== ACTIVE AGENTS ({len(context['active_agents'])}) ===")
            for agent in context["active_agents"]:
                lines.append(
                    f"  - {agent['agent_id']} ({agent['model']}) [{agent['role']}]"
                )
            lines.append("")

        return "\n".join(lines)

    def _format_messages(self, messages: List[Dict], current_agent_id: str) -> List[str]:
        """Format messages with clear attribution for the current agent."""
        formatted = []
        for msg in messages:
            from_label = msg["from_agent"]
            to_label = msg.get("to_agent") or "all"
            msg_type = msg["msg_type"]

            if from_label == "system":
                prefix = f"[system]"
            else:
                prefix = f"[{from_label} → {to_label}]"

            content = msg["content"]
            if len(content) > 500:
                content = content[:497] + "..."

            line = f"{prefix} [{msg_type}] {content}"

            metadata = msg.get("metadata", {})
            if metadata.get("artifact_refs"):
                for art_ref in metadata["artifact_refs"]:
                    line += f"\n  ↳ Artifact: {art_ref}"

            formatted.append(line)
        return formatted
