"""Session rules engine for CollabSessions.

Validates operations against session rules and enforces constraints
like max agents, assignment requirements, message length limits,
and idle timeouts.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple


DEFAULT_RULES = {
    "max_agents": 10,
    "require_assignment": False,
    "max_message_length": 8000,
    "require_artifact_for_results": False,
    "auto_archive_after_idle_minutes": 120,
    "auto_compact_after_messages": 50,
    "max_pending_tasks": 20,
    "allow_self_assignment": True,
}


class RulesEngine:
    """Validates operations against session rules."""

    def __init__(self, rules: Optional[Dict] = None):
        self.rules = {**DEFAULT_RULES, **(rules or {})}

    def validate_join(self, current_agent_count: int) -> Tuple[bool, Optional[str]]:
        """Validate if a new agent can join."""
        max_agents = self.rules.get("max_agents", 10)
        if current_agent_count >= max_agents:
            return False, f"Session is full ({current_agent_count}/{max_agents} agents)"
        return True, None

    def validate_message(
        self,
        content: str,
        msg_type: str,
        has_artifact_ref: bool = False,
    ) -> Tuple[bool, List[str]]:
        """Validate a message against session rules.

        Returns (is_valid, list_of_warnings).
        """
        warnings = []
        max_len = self.rules.get("max_message_length", 8000)

        if len(content) > max_len:
            return False, [f"Message exceeds max length ({len(content)}/{max_len})"]

        require_artifact = self.rules.get("require_artifact_for_results", False)
        if require_artifact and msg_type == "result" and not has_artifact_ref:
            warnings.append(
                "Session rules require artifacts for result messages. "
                "Use save_artifact to save your work."
            )

        return True, warnings

    def validate_task_assignment(
        self,
        assigned_to: Optional[str],
        current_pending_count: int,
    ) -> Tuple[bool, Optional[str]]:
        """Validate task assignment."""
        max_pending = self.rules.get("max_pending_tasks", 20)
        if current_pending_count >= max_pending:
            return False, f"Too many pending tasks ({current_pending_count}/{max_pending})"
        return True, None

    def should_compact(self, message_count: int, last_compact_seq: int) -> bool:
        """Check if session should be compacted."""
        threshold = self.rules.get("auto_compact_after_messages", 50)
        return (message_count - last_compact_seq) >= threshold

    def is_idle(self, last_activity_iso: str, current_iso: str) -> Tuple[bool, float]:
        """Check if session is idle beyond the timeout.

        Returns (is_idle, minutes_since_activity).
        """
        try:
            from datetime import datetime, timezone

            last = datetime.fromisoformat(last_activity_iso)
            current = datetime.fromisoformat(current_iso)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if current.tzinfo is None:
                current = current.replace(tzinfo=timezone.utc)

            minutes = (current - last).total_seconds() / 60
            timeout = self.rules.get("auto_archive_after_idle_minutes", 120)
            return minutes >= timeout, minutes
        except (ValueError, TypeError):
            return False, 0

    def get_rules_summary(self) -> str:
        """Get a human-readable summary of active rules."""
        lines = ["Session Rules:"]
        defaults = DEFAULT_RULES
        for key, value in sorted(self.rules.items()):
            default = defaults.get(key)
            marker = " (custom)" if value != default else ""
            lines.append(f"  - {key}: {value}{marker}")
        return "\n".join(lines)
