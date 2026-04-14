"""
Knowledge extractor for synthesizing structured knowledge from observations.

Transforms raw tool observations into actionable session knowledge:
- Decisions made and rationale
- Files/modules touched and why
- Conventions and patterns discovered
- Phases completed vs remaining
- Open questions and next steps

This is the "knowledge layer" — not compressed tool outputs, but synthesized
understanding that an LLM can use to resume work across sessions.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class SessionKnowledge:
    """Structured knowledge synthesized from a session's observations."""
    session_id: str
    summary: str = ""

    # What was done
    files_touched: List[Dict[str, str]] = field(default_factory=list)
    # [{path: "memory/storage.py", action: "modified", reason: "Fixed FK cascade"}]

    decisions_made: List[str] = field(default_factory=list)
    # ["Chose SQLite with CASCADE for FK management"]

    phases_completed: List[str] = field(default_factory=list)
    phases_remaining: List[str] = field(default_factory=list)

    # What was discovered
    conventions_found: List[str] = field(default_factory=list)
    # ["Uses dataclasses for structured data", "Lazy-loading for heavy modules"]

    architecture_notes: List[str] = field(default_factory=list)
    # ["MCP server uses FastMCP with lazy tool registration"]

    # What's next
    open_questions: List[str] = field(default_factory=list)
    next_steps: List[str] = field(default_factory=list)

    # Metadata
    tool_execution_count: int = 0
    tool_breakdown: Dict[str, int] = field(default_factory=dict)
    errors_encountered: List[str] = field(default_factory=list)

    def format_quick_recap(self) -> str:
        """Format as a quick recap for the model (~150-250 tokens)."""
        lines = []
        session_preview = self.session_id[:16] if self.session_id else "unknown"
        lines.append(f"# Session Recap (session: {session_preview})")
        lines.append("")

        # Summary
        if self.summary:
            lines.append(self.summary)
            lines.append("")

        # Activity overview
        lines.append(f"**Activity**: {self.tool_execution_count} tool executions")
        if self.tool_breakdown:
            tools = ", ".join(
                f"{t}: {c}" for t, c in
                sorted(self.tool_breakdown.items(), key=lambda x: -x[1])[:5]
            )
            lines.append(f"**Tools**: {tools}")
        lines.append("")

        # Files touched (compact)
        if self.files_touched:
            files = ", ".join(
                f"{f['path']} ({f['action']})"
                for f in self.files_touched[:8]
            )
            lines.append(f"**Files**: {files}")
            if len(self.files_touched) > 8:
                lines.append(f"  (+{len(self.files_touched) - 8} more)")
            lines.append("")

        # Key decisions
        if self.decisions_made:
            lines.append("**Decisions**:")
            for d in self.decisions_made[:5]:
                lines.append(f"- {d}")
            lines.append("")

        # Next steps (most important for resuming)
        if self.next_steps:
            lines.append("**Next Steps**:")
            for n in self.next_steps[:3]:
                lines.append(f"- {n}")
            lines.append("")

        # Open questions
        if self.open_questions:
            lines.append(f"**Open Questions**: {len(self.open_questions)}")
            lines.append("")

        result = "\n".join(lines)
        token_estimate = int(len(result.split()) * 1.3)
        return result

    def format_detailed_context(self, topic: Optional[str] = None) -> str:
        """Format as detailed context for a specific topic (~500-800 tokens)."""
        lines = []
        lines.append(f"# Detailed Session Context")
        lines.append(f"Session: {self.session_id}")
        lines.append("")

        if topic:
            # Filter to topic-specific content
            lines.append(f"## Topic: {topic}")
            lines.append("")

            # Show files related to topic
            topic_files = [
                f for f in self.files_touched
                if topic.lower() in f["path"].lower() or topic.lower() in f.get("reason", "").lower()
            ]
            if topic_files:
                lines.append("### Related Files")
                for f in topic_files:
                    lines.append(f"- `{f['path']}` — {f['action']}: {f['reason']}")
                lines.append("")

            # Show decisions related to topic
            topic_decisions = [
                d for d in self.decisions_made
                if topic.lower() in d.lower()
            ]
            if topic_decisions:
                lines.append("### Related Decisions")
                for d in topic_decisions:
                    lines.append(f"- {d}")
                lines.append("")

            # Show architecture notes related to topic
            topic_arch = [
                a for a in self.architecture_notes
                if topic.lower() in a.lower()
            ]
            if topic_arch:
                lines.append("### Architecture Notes")
                for a in topic_arch:
                    lines.append(f"- {a}")
                lines.append("")

        else:
            # Full detailed context

            ## Files touched
            if self.files_touched:
                lines.append("## Files Touched")
                for f in self.files_touched:
                    lines.append(f"- `{f['path']}` — {f['action']}")
                    if f.get("reason"):
                        lines.append(f"  Reason: {f['reason']}")
                lines.append("")

            ## Decisions
            if self.decisions_made:
                lines.append("## Decisions Made")
                for d in self.decisions_made:
                    lines.append(f"- {d}")
                lines.append("")

            ## Conventions
            if self.conventions_found:
                lines.append("## Conventions & Patterns")
                for c in self.conventions_found:
                    lines.append(f"- {c}")
                lines.append("")

            ## Architecture
            if self.architecture_notes:
                lines.append("## Architecture Notes")
                for a in self.architecture_notes:
                    lines.append(f"- {a}")
                lines.append("")

            ## Phases
            if self.phases_completed or self.phases_remaining:
                lines.append("## Phase Status")
                if self.phases_completed:
                    lines.append(f"**Done**: {', '.join(self.phases_completed)}")
                if self.phases_remaining:
                    lines.append(f"**Remaining**: {', '.join(self.phases_remaining)}")
                lines.append("")

            ## Errors
            if self.errors_encountered:
                lines.append("## Errors Encountered")
                for e in self.errors_encountered:
                    lines.append(f"- {e}")
                lines.append("")

            ## Next steps
            if self.next_steps:
                lines.append("## Next Steps")
                for n in self.next_steps:
                    lines.append(f"- {n}")
                lines.append("")

            ## Open questions
            if self.open_questions:
                lines.append("## Open Questions")
                for q in self.open_questions:
                    lines.append(f"- {q}")
                lines.append("")

        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for storage."""
        return {
            "session_id": self.session_id,
            "summary": self.summary,
            "files_touched": self.files_touched,
            "decisions_made": self.decisions_made,
            "phases_completed": self.phases_completed,
            "phases_remaining": self.phases_remaining,
            "conventions_found": self.conventions_found,
            "architecture_notes": self.architecture_notes,
            "open_questions": self.open_questions,
            "next_steps": self.next_steps,
            "tool_execution_count": self.tool_execution_count,
            "tool_breakdown": self.tool_breakdown,
            "errors_encountered": self.errors_encountered,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionKnowledge":
        """Deserialize from dict."""
        knowledge = cls(session_id=data.get("session_id", ""))
        knowledge.summary = data.get("summary", "")
        knowledge.files_touched = data.get("files_touched", [])
        knowledge.decisions_made = data.get("decisions_made", [])
        knowledge.phases_completed = data.get("phases_completed", [])
        knowledge.phases_remaining = data.get("phases_remaining", [])
        knowledge.conventions_found = data.get("conventions_found", [])
        knowledge.architecture_notes = data.get("architecture_notes", [])
        knowledge.open_questions = data.get("open_questions", [])
        knowledge.next_steps = data.get("next_steps", [])
        knowledge.tool_execution_count = data.get("tool_execution_count", 0)
        knowledge.tool_breakdown = data.get("tool_breakdown", {})
        knowledge.errors_encountered = data.get("errors_encountered", [])
        return knowledge


# Patterns for extracting knowledge from observations

FILE_ACTION_PATTERNS = {
    # Tool name -> action type
    "read": "read",
    "read_file": "read",
    "cat": "read",
    "edit": "modified",
    "write": "created",
    "write_file": "created",
    "save": "created",
    "run_shell_command": "executed",
    "bash": "executed",
    "shell": "executed",
    "grep": "searched",
    "search": "searched",
    "glob": "searched",
    "delete": "deleted",
    "remove": "deleted",
}

# Keywords that signal decisions in output text
DECISION_KEYWORDS = [
    "decided", "chose", "selected", "opted for", "went with",
    "determined", "concluded", "settled on", "preference",
    "best approach", "better to", "should use", "will use",
    "architecture", "design choice", "pattern", "convention",
]

# Keywords that signal conventions/patterns
CONVENTION_KEYWORDS = [
    "pattern", "convention", "style", "format", "structure",
    "follows", "uses", "imports", "decorator", "class",
    "function", "method", "module", "package",
]

# Keywords that signal phases/milestones
PHASE_KEYWORDS = [
    "phase", "step", "stage", "milestone", "completed",
    "done", "finished", "implemented", "ready",
]

# Keywords that signal next steps
NEXT_STEP_KEYWORDS = [
    "next", "todo", "remaining", "still need", "should",
    "will need to", "future", "upcoming", "plan",
    "TODO", "FIXME", "hack",
]


class KnowledgeExtractor:
    """Extracts structured knowledge from session observations."""

    def extract(
        self,
        session_id: str,
        observations: List[Dict[str, Any]]
    ) -> SessionKnowledge:
        """
        Extract knowledge from a list of observations.

        Args:
            session_id: Session identifier
            observations: List of observation dicts from storage

        Returns:
            SessionKnowledge with synthesized knowledge
        """
        knowledge = SessionKnowledge(session_id=session_id)

        if not observations:
            return knowledge

        knowledge.tool_execution_count = len(observations)

        # Track seen files to avoid duplicates
        seen_files: Set[str] = set()

        for obs in observations:
            tool_name = obs.get("tool_name", "").lower()
            tool_input = obs.get("tool_input", "")
            tool_output = obs.get("tool_output", "")
            compressed = obs.get("compressed_summary", "")

            # Count tool breakdown
            knowledge.tool_breakdown[tool_name or "unknown"] = (
                knowledge.tool_breakdown.get(tool_name or "unknown", 0) + 1
            )

            # Extract files
            self._extract_files(obs, tool_name, tool_input, tool_output,
                              knowledge, seen_files)

            # Extract decisions
            self._extract_decisions(tool_input, tool_output, compressed,
                                   knowledge)

            # Extract conventions
            self._extract_conventions(tool_output, compressed, knowledge)

            # Extract errors
            self._extract_errors(tool_output, compressed, knowledge)

        # Extract phases from overall context
        self._extract_phases(observations, knowledge)

        # Generate next steps and open questions
        self._generate_next_steps(knowledge)

        # Generate summary
        knowledge.summary = self._generate_summary(knowledge)

        return knowledge

    def _extract_files(
        self,
        obs: Dict[str, Any],
        tool_name: str,
        tool_input: str,
        tool_output: str,
        knowledge: SessionKnowledge,
        seen_files: Set[str]
    ):
        """Extract files touched from observation."""
        file_path = None
        path_match = re.search(
            r'([a-zA-Z0-9_./\\-]+(?:\.py|\.json|\.md|\.txt|\.yaml|\.yml|\.toml|\.cfg|\.ini|\.sh|\.ps1|\.js|\.ts|\.tsx|\.css|\.html))',
            tool_input
        )
        if path_match:
            file_path = path_match.group(1)

        # Also check tool_output for file paths (e.g., from ls, glob)
        if not file_path:
            path_match = re.search(
                r'([a-zA-Z0-9_./\\-]+(?:\.py|\.json|\.md|\.txt|\.yaml|\.yml|\.toml))',
                tool_output[:500]  # Only scan first 500 chars
            )
            if path_match:
                file_path = path_match.group(1)

        if file_path and file_path not in seen_files:
            seen_files.add(file_path)
            action = FILE_ACTION_PATTERNS.get(tool_name, "interacted")
            reason = self._infer_file_reason(tool_name, tool_output)

            knowledge.files_touched.append({
                "path": file_path,
                "action": action,
                "reason": reason,
            })

    def _infer_file_reason(self, tool_name: str, tool_output: str) -> str:
        """Infer why a file was touched based on tool output."""
        output_lower = tool_output.lower()[:200]

        if "error" in output_lower or "failed" in output_lower:
            return "error encountered"
        if "created" in output_lower or "new" in output_lower:
            return "new file"
        if "updated" in output_lower or "modified" in output_lower:
            return "modification"
        if "read" in output_lower or "content" in output_lower:
            return "reading content"

        action = FILE_ACTION_PATTERNS.get(tool_name, "")
        if action == "read":
            return "analysis"
        elif action == "modified":
            return "code change"
        elif action == "created":
            return "new file"
        elif action == "executed":
            return "command execution"

        return "interaction"

    def _extract_decisions(
        self,
        tool_input: str,
        tool_output: str,
        compressed: str,
        knowledge: SessionKnowledge
    ):
        """Extract decisions from observation text."""
        text = f"{tool_input} {tool_output} {compressed}".lower()

        for keyword in DECISION_KEYWORDS:
            if keyword in text:
                sentences = re.split(r'[.!?]+', f"{tool_input} {tool_output}")
                for sentence in sentences:
                    if keyword in sentence.lower() and len(sentence.strip()) > 20:
                        decision = sentence.strip()[:200]
                        if decision not in knowledge.decisions_made:
                            knowledge.decisions_made.append(decision)
                        break
                break  # Only match once per observation

    def _extract_conventions(
        self,
        tool_output: str,
        compressed: str,
        knowledge: SessionKnowledge
    ):
        """Extract conventions and patterns from observation text."""
        text = f"{tool_output} {compressed}".lower()

        uses_pattern = re.findall(
            r'(?:uses|follows|employs|applies)\s+([a-z][a-z\s_-]{3,30})\s+(?:pattern|convention|style|approach)',
            text
        )
        for pattern in uses_pattern:
            convention = f"Uses {pattern.strip()} pattern"
            if convention not in knowledge.conventions_found:
                knowledge.conventions_found.append(convention)

    def _extract_errors(
        self,
        tool_output: str,
        compressed: str,
        knowledge: SessionKnowledge
    ):
        """Extract errors encountered."""
        text = tool_output or ""
        text_lower = text.lower()

        if any(err in text_lower for err in [
            "traceback", "exception", "error:", "failed:",
            "syntaxerror", "importerror", "typeerror",
            "attributeerror", "keyerror", "valueerror",
        ]):
            # Extract error line
            for line in text.split("\n")[:20]:  # Scan first 20 lines
                if "error" in line.lower() or "traceback" in line.lower():
                    error = line.strip()[:200]
                    if error and error not in knowledge.errors_encountered:
                        knowledge.errors_encountered.append(error)
                        break  # One error per observation

    def _extract_phases(
        self,
        observations: List[Dict[str, Any]],
        knowledge: SessionKnowledge
    ):
        """Extract phase information from observations."""
        all_text = " ".join(
            f"{o.get('tool_output', '')} {o.get('compressed_summary', '')}"
            for o in observations
        ).lower()

        phase_matches = re.findall(
            r'phase\s+(\d+|[ivxlcdm]+)\s*(completed|done|finished|remaining|pending|next)?',
            all_text
        )
        for phase_num, status in phase_matches:
            phase_str = f"Phase {phase_num}"
            if status in ("completed", "done", "finished"):
                if phase_str not in knowledge.phases_completed:
                    knowledge.phases_completed.append(phase_str)
            elif status in ("remaining", "pending", "next"):
                if phase_str not in knowledge.phases_remaining:
                    knowledge.phases_remaining.append(phase_str)

    def _generate_next_steps(self, knowledge: SessionKnowledge):
        """Generate next steps based on extracted knowledge."""
        # If there are remaining phases, they become next steps
        for phase in knowledge.phases_remaining:
            step = f"Complete {phase}"
            if step not in knowledge.next_steps:
                knowledge.next_steps.append(step)

        # If errors were encountered, fixing them is a next step
        if knowledge.errors_encountered:
            error_types = set()
            for e in knowledge.errors_encountered:
                if "import" in e.lower():
                    error_types.add("Fix import errors")
                elif "type" in e.lower():
                    error_types.add("Fix type errors")
                elif "syntax" in e.lower():
                    error_types.add("Fix syntax errors")
                else:
                    error_types.add("Fix runtime errors")
            for et in error_types:
                if et not in knowledge.next_steps:
                    knowledge.next_steps.append(et)

        # If files were modified, testing is often a next step
        if len(knowledge.files_touched) > 3:
            test_step = "Run tests to verify changes"
            if test_step not in knowledge.next_steps:
                knowledge.next_steps.append(test_step)

    def _generate_summary(self, knowledge: SessionKnowledge) -> str:
        """Generate a one-line summary of the session."""
        parts = []

        if knowledge.files_touched:
            file_count = len(knowledge.files_touched)
            parts.append(f"Worked on {file_count} file{'s' if file_count > 1 else ''}")

        if knowledge.phases_completed:
            parts.append(f"completed {', '.join(knowledge.phases_completed[:3])}")

        if knowledge.tool_execution_count:
            parts.append(f"({knowledge.tool_execution_count} tool calls)")

        if knowledge.errors_encountered:
            parts.append(f"encountered {len(knowledge.errors_encountered)} error{'s' if len(knowledge.errors_encountered) > 1 else ''}")

        return " — ".join(parts) if parts else "Session activity recorded"


def extract_knowledge(
    session_id: str,
    observations: List[Dict[str, Any]]
) -> SessionKnowledge:
    """
    Convenience function to extract knowledge from observations.

    Args:
        session_id: Session identifier
        observations: List of observation dicts

    Returns:
        SessionKnowledge with synthesized knowledge
    """
    extractor = KnowledgeExtractor()
    return extractor.extract(session_id, observations)
