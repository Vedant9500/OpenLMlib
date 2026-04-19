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

MODEL_PROFILES = {
    "claude": {
        "optimal_context_messages": 5,
        "handoff_instructions": "Be thorough. Include caveats and confidence levels.",
    },
    "gpt": {
        "optimal_context_messages": 5,
        "handoff_instructions": "Be concise. Use numbered steps for actionable items.",
    },
    "gemini": {
        "optimal_context_messages": 8,
        "handoff_instructions": "Synthesize broadly. Connect findings to related areas.",
    },
    "default": {
        "optimal_context_messages": 5,
        "handoff_instructions": "Provide clear, structured findings.",
    }
}

def _get_model_family(model_name: str) -> str:
    """Detect the model family to apply the correct MODEL_PROFILE."""
    name = model_name.lower()
    if "claude" in name: return "claude"
    if "gpt" in name or "o1" in name or "o3" in name: return "gpt"
    if "gemini" in name: return "gemini"
    return "default"


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
        max_messages: int = 5,
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

        agents = db.get_session_agents(self.conn, session_id)
        
        # Apply model-aware constraints
        my_agent = next((a for a in agents if a["agent_id"] == agent_id), None)
        model_name = my_agent["model"] if my_agent else "default"
        family = _get_model_family(model_name)
        profile = MODEL_PROFILES.get(family, MODEL_PROFILES["default"])
        
        # Override max_messages with optimal context depth if the default isn't explicitly changed
        if max_messages == 5:
            max_messages = profile["optimal_context_messages"]

        recent_messages = self.message_bus.tail(session_id, max_messages)
        formatted_messages = self._format_messages(recent_messages, agent_id, family)

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

        # Injects model-specific handoff hints
        model_instructions = f"MODEL-SPECIFIC HINTS: {profile['handoff_instructions']}"

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
            "role_instructions": self._role_instructions(
                session_id, agent_id, agents
            ),
            "model_instructions": model_instructions,
            "autonomous_instructions": self.autonomous_instructions(),
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

        if context.get("role_instructions"):
            lines.append(context["role_instructions"])
            lines.append("")

        if context.get("model_instructions"):
            lines.append(context["model_instructions"])
            lines.append("")

        if context.get("autonomous_instructions"):
            lines.append("=== AUTONOMOUS MODE ===")
            lines.append(context["autonomous_instructions"])
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

    def _role_instructions(
        self,
        session_id: str,
        agent_id: str,
        agents: List[Dict],
    ) -> str:
        """Return role-specific behavioral instructions for this agent.

        Unlike autonomous_instructions (which explains the poll→respond loop),
        this tells the agent WHAT to do based on its role — its responsibilities,
        priorities, and how it should interact with other agents.
        """
        role = next(
            (a["role"] for a in agents if a["agent_id"] == agent_id),
            "worker",
        )

        other_agents = [
            a for a in agents
            if a["agent_id"] != agent_id and a["status"] == "active"
        ]
        other_agents_str = ", ".join(
            f"{a['agent_id']} ({a['model']}, {a['role']})"
            for a in other_agents
        ) if other_agents else "(none yet)"

        if role == "orchestrator":
            return (
                "=== YOUR ROLE: ORCHESTRATOR ===\n"
                "You lead this session. Your goal: produce a high-quality synthesized result.\n\n"
                "WORKFLOW:\n"
                "1. PLAN — Assign ALL tasks upfront via the session plan or send_message.\n"
                "   Each task needs: clear goal, acceptance criteria, assigned worker agent_id.\n"
                "   Workers start immediately on join — send all tasks at once, not one by one.\n\n"
                "2. MONITOR — Use poll_messages(session_id, your_agent_id, timeout=30,\n"
                "   msg_types=['result', 'question']) to wait for outputs.\n\n"
                "3. SYNTHESIZE — When workers return results:\n"
                "   Read full details via get_artifact (workers save detailed work there).\n"
                "   Different workers may use different styles — normalize before comparing.\n"
                "   Save your consolidated findings as a shared artifact.\n\n"
                "4. TERMINATE — Call terminate_session(session_id, your_agent_id, summary='...').\n\n"
                "KEY RULES:\n"
                "- Keep messages concise. Request artifacts for significant findings.\n"
                "- Provide clear acceptance criteria with each task.\n"
                "- Address messages to specific agent_ids.\n\n"
                f"Active agents: {other_agents_str}\n"
                "If no workers have joined yet, save your plan via update_session_state."
            )

        elif role == "worker":
            # Find who the orchestrator is
            orchestrator = next(
                (a for a in agents if a["role"] == "orchestrator"),
                None,
            )
            orch_id = orchestrator["agent_id"] if orchestrator else "unknown"
            orch_model = orchestrator["model"] if orchestrator else "unknown"

            # Find my tasks
            my_task_list = [
                t for t in (self.conn.execute(
                    "SELECT step_num, description, status FROM tasks "
                    "WHERE session_id = ? AND (assigned_to = ? OR assigned_to IS NULL OR assigned_to = 'any') "
                    "ORDER BY step_num",
                    (session_id, agent_id),
                ).fetchall() or [])
            ]

            tasks_text = ""
            if my_task_list:
                tasks_lines = [
                    f"  Step {t[0]}: {t[1]} (status: {t[2]})"
                    for t in my_task_list
                ]
                tasks_text = (
                    "YOUR ASSIGNED TASKS — start these now:\n"
                    + "\n".join(tasks_lines)
                    + "\n"
                )
            else:
                tasks_text = (
                    "No tasks pre-assigned. Use poll_messages to wait for assignments.\n"
                )

            return (
                "=== YOUR ROLE: WORKER ===\n"
                "PRIORITY: If tasks are listed below, start working immediately.\n\n"
                "WORKFLOW:\n"
                "1. Execute your assigned task(s) thoroughly.\n"
                "2. Save all detailed work via save_artifact (use markdown format).\n"
                f"3. Send ONE result message when done: msg_type='result', to_agent='{orch_id}'.\n"
                "   Reference artifact IDs for detailed output.\n"
                f"4. If blocked, ask: msg_type='question', to_agent='{orch_id}'.\n\n"
                "RESULT FORMAT — structure every result as:\n"
                "  ## Summary\n"
                "  [1-2 sentence finding]\n"
                "  ## Key Facts\n"
                "  - [concrete, verifiable fact]\n"
                "  ## Confidence & Caveats\n"
                "  [high/medium/low] — [what might be incomplete]\n"
                "  ## Artifacts\n"
                "  [artifact_id]: [description]\n\n"
                "EFFICIENCY:\n"
                "- Put detailed work in artifacts, keep messages short.\n"
                "- Skip greetings, acknowledgments, and progress updates.\n"
                "- Combine task completion into your result message.\n\n"
                f"Orchestrator: {orch_id} ({orch_model})\n"
                f"Other agents: {other_agents_str}\n"
                f"{tasks_text}"
            )

        else:  # observer
            return (
                "=== YOUR ROLE: OBSERVER ===\n"
                "You monitor and analyze this session without interfering.\n\n"
                "WORKFLOW:\n"
                "1. Use poll_messages to track session activity.\n"
                "2. Note key decisions, findings, and collaboration issues.\n"
                "3. Save analysis outputs as artifacts via save_artifact.\n"
                "4. Respond only when directly asked (use msg_type='answer').\n"
                "5. Never assign tasks or modify session state.\n\n"
                f"Active agents: {other_agents_str}"
            )

    @staticmethod
    def autonomous_instructions() -> str:
        """Return condensed autonomous mode instructions.

        Tells the agent to run a continuous poll→process→respond loop.
        Intentionally compact (~85 tokens) to minimize context overhead.
        """
        return (
            "AUTONOMOUS MODE — run a continuous loop without user input.\n\n"
            "Loop: poll_messages(timeout=30) → process messages → respond → repeat.\n"
            "- On timeout with no messages, poll again.\n"
            "- For 'task' or 'question': do the work, then send your response.\n"
            "- For 'result', 'complete', 'update', 'artifact': note and continue.\n"
            "- When done: orchestrators call terminate_session; "
            "workers send final 'result' then call leave_session.\n"
            "- Keep looping until session status is 'completed' or 'terminated'."
        )

    def _translate_for_receiver(self, content: str, receiver_family: str) -> str:
        """Inject minor framing to map cross-model outputs to the receiver's style."""
        content_lower = content.lower()
        if receiver_family == "claude" and "step" in content_lower and "\n1." in content:
            return "[GPT-Style Step List]:\n" + content
        if receiver_family == "gpt" and "however" in content_lower and "confidence" in content_lower:
            return "[Claude-Style Analysis]:\n" + content
        if receiver_family == "gemini" and "## summary" in content_lower:
            return "[Structured Findings]:\n" + content
        return content

    def _format_messages(self, messages: List[Dict], current_agent_id: str, receiver_family: str = "default") -> List[str]:
        """Format messages with clear attribution for the current agent."""
        formatted = []
        for msg in messages:
            from_label = msg["from_agent"]
            to_label = msg.get("to_agent") or "all"
            msg_type = msg["msg_type"]
            timestamp = msg.get("created_at", "")
            # Extract time portion for compact display
            if "T" in timestamp:
                time_part = timestamp.split("T")[1][:8]  # HH:MM:SS
            else:
                time_part = timestamp

            if from_label == "system":
                prefix = f"[{time_part}] [system]"
            else:
                prefix = f"[{time_part}] [{from_label} → {to_label}]"

            content = msg["content"]
            if len(content) > 500:
                content = content[:497] + "..."

            content = self._translate_for_receiver(content, receiver_family)

            line = f"{prefix} [{msg_type}] {content}"

            metadata = msg.get("metadata", {})
            if metadata.get("artifact_refs"):
                for art_ref in metadata["artifact_refs"]:
                    line += f"\n  ↳ Artifact: {art_ref}"

            formatted.append(line)
        return formatted
