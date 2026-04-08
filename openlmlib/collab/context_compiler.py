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
            "role_instructions": self._role_instructions(
                session_id, agent_id, agents
            ),
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
                "You are the session ORCHESTRATOR. You are in charge. Your job is to:\n\n"
                "1. **PLAN**: Analy the session goal and break it into specific, numbered tasks.\n"
                "   - Each task should have a clear description, step number, and expected output.\n"
                "   - Assign tasks to specific workers based on their model capabilities.\n"
                "   - Use collab_update_session_state to save your plan.\n\n"
                "2. **DELEGATE**: Send tasks to workers via collab_send_message.\n"
                "   - Use msg_type='task' for work assignments.\n"
                "   - Include the step number, detailed instructions, and acceptance criteria.\n"
                "   - Address messages to the specific worker's agent_id.\n\n"
                "3. **MONITOR**: After delegating, use collab_poll_messages to watch for results.\n"
                "   - Workers will send msg_type='result' when they complete tasks.\n"
                "   - Workers may send msg_type='question' if they need clarification.\n"
                "   - If a worker is silent, send a follow-up message.\n\n"
                "4. **SYNTHESIZE**: When workers return results, integrate them.\n"
                "   - Compare findings from different workers.\n"
                "   - Identify gaps and assign follow-up tasks as needed.\n"
                "   - Save consolidated conclusions as artifacts.\n\n"
                "5. **TERMINATE**: When the session goal is achieved, call\n"
                "   collab_terminate_session(session_id, your_agent_id, summary='...').\n\n"
                f"Active agents in this session: {other_agents_str}\n"
                "If no workers have joined yet, you can still create your plan and save it via\n"
                "collab_update_session_state. Workers will see it when they join."
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
                    "\nYour current assigned tasks:\n"
                    + "\n".join(tasks_lines)
                    + "\n"
                )
            else:
                tasks_text = (
                    "No tasks are assigned to you yet. Wait for the orchestrator to send work.\n"
                )

            return (
                "=== YOUR ROLE: WORKER ===\n"
                "You are a WORKER agent. Your job is to complete tasks assigned by the orchestrator.\n\n"
                "1. **CHECK FOR TASKS**: Look at 'Your Current Tasks' in the session context above.\n"
                "   - If you have a pending or in-progress task, work on it now.\n"
                "   - If you have no tasks, wait for the orchestrator to assign you work.\n\n"
                "2. **EXECUTE**: Complete your assigned task thoroughly.\n"
                "   - Do the research, analysis, or writing as required.\n"
                "   - Save significant outputs as artifacts via collab_add_artifact.\n\n"
                "3. **REPORT**: Send your results back to the orchestrator.\n"
                "   - Use collab_send_message with msg_type='result'.\n"
                "   - Address the message to the orchestrator: to_agent='{orch_id}' ({orch_model}).\n"
                "   - Include a clear summary, not just raw data.\n"
                "   - Reference artifact IDs if you saved outputs.\n\n"
                "4. **PROGRESS UPDATES**: For long tasks, send interim updates.\n"
                "   - Use msg_type='update' to show partial progress.\n"
                "   - This keeps the orchestrator informed and prevents timeout.\n\n"
                "5. **ASK QUESTIONS**: If a task is unclear, ask the orchestrator.\n"
                "   - Use msg_type='question' with to_agent='{orch_id}'.\n\n"
                "6. **WHEN DONE**: After completing all your tasks:\n"
                "   - Send a msg_type='complete' message to the orchestrator.\n"
                "   - Call collab_leave_session(session_id, your_agent_id).\n\n"
                f"Orchestrator: {orch_id} ({orch_model})\n"
                f"Other workers: {other_agents_str}\n\n"
                f"{tasks_text}"
                "IMPORTANT: Always use collab_poll_messages(session_id, your_agent_id, timeout=30)\n"
                "in a loop to check for new tasks or messages from the orchestrator."
            )

        else:  # observer
            return (
                "=== YOUR ROLE: OBSERVER ===\n"
                "You are an OBSERVER agent. Your job is to monitor and analyze the session.\n\n"
                "1. **MONITOR**: Use collab_poll_messages to watch session activity.\n"
                "   - Track how the orchestrator and workers are collaborating.\n"
                "   - Note key decisions, progress, and any issues.\n\n"
                "2. **ANALYZE**: Provide insights on session progress.\n"
                "   - Identify bottlenecks or communication gaps.\n"
                "   - Suggest improvements if asked.\n\n"
                "3. **DO NOT INTERFERE**: You are read-only.\n"
                "   - Do NOT assign tasks or modify session state.\n"
                "   - Only send messages with msg_type='answer' when directly asked.\n\n"
                "4. **SAVE ANALYSIS**: Use collab_add_artifact for analysis outputs.\n\n"
                f"Active agents: {other_agents_str}"
            )

    @staticmethod
    def autonomous_instructions() -> str:
        """Return instructions for agents running in autonomous mode.

        This tells the agent to run a continuous poll→process→respond loop
        without requiring human intervention between turns.
        """
        return (
            "You are in AUTONOMOUS MODE. You must run a continuous collaboration loop "
            "without waiting for user input:\n\n"
            "1. Call collab_poll_messages(session_id, your_agent_id, timeout=30)\n"
            "   - This blocks until another agent sends a message or 30s passes\n"
            "   - If timed_out is True, call it again to keep waiting\n"
            "   - If messages arrive, process ALL of them before the next poll\n\n"
            "2. For each message:\n"
            "   - If msg_type is 'task' or 'question': process it, then send your result\n"
            "   - If msg_type is 'result' or 'answer': acknowledge and update your state\n"
            "   - If msg_type is 'complete': acknowledge and consider the task done\n"
            "   - If msg_type is 'ack', 'update', or 'artifact': note it and continue the loop\n\n"
            "3. Send responses via collab_send_message(session_id, msg_type, content, "
            "from_agent=your_agent_id, to_agent=target_agent_if_known)\n\n"
            "4. After sending, loop back to step 1 immediately\n\n"
            "5. When all your work is done:\n"
            "   - If you are the orchestrator: call collab_terminate_session(session_id, "
            "your_agent_id, summary='...') to mark the session completed\n"
            "   - If you are a worker: send a 'complete' message to the orchestrator, "
            "then call collab_leave_session(session_id, your_agent_id)\n\n"
            "IMPORTANT: Do NOT stop after a single turn. Keep the poll→process→respond loop "
            "running until the session status changes to 'completed' or 'terminated'.\n"
            "Only return control to the user when the session is fully finished."
        )

    def _format_messages(self, messages: List[Dict], current_agent_id: str) -> List[str]:
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

            line = f"{prefix} [{msg_type}] {content}"

            metadata = msg.get("metadata", {})
            if metadata.get("artifact_refs"):
                for art_ref in metadata["artifact_refs"]:
                    line += f"\n  ↳ Artifact: {art_ref}"

            formatted.append(line)
        return formatted
