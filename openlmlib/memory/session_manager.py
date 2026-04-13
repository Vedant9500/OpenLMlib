"""
Session manager for memory injection system.

Tracks session lifecycle and triggers appropriate hooks:
- Session start: Load context from previous sessions
- Tool use: Capture observations
- Session end: Summarize and persist

Integrates with HookRegistry and MemoryStorage.
"""

from __future__ import annotations

import atexit
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from .hooks import (
    Hook,
    HookRegistry,
    HookType,
    default_post_tool_use_handler,
    default_session_end_handler,
    default_session_start_handler,
    default_stop_handler,
)
from .privacy import sanitize_for_storage
from .storage import MemoryStorage

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages session lifecycle and memory hooks."""

    def __init__(
        self,
        storage: MemoryStorage,
        observation_callback: Optional[Callable] = None
    ):
        """
        Initialize session manager.

        Args:
            storage: MemoryStorage instance
            observation_callback: Optional callback for async observation processing
        """
        self.storage = storage
        self.observation_callback = observation_callback
        self.hooks = HookRegistry()
        self.active_sessions: Dict[str, Dict[str, Any]] = {}

        # Register default hooks
        self._register_default_hooks()

        # Register atexit handler to clean up active sessions
        atexit.register(self._cleanup_on_exit)

    def _register_default_hooks(self):
        """Register default lifecycle hooks."""
        self.hooks.register(Hook(
            HookType.SESSION_START,
            default_session_start_handler,
            priority=0,
            name="default_session_start"
        ))

        self.hooks.register(Hook(
            HookType.POST_TOOL_USE,
            default_post_tool_use_handler,
            priority=0,
            name="default_post_tool_use"
        ))

        self.hooks.register(Hook(
            HookType.STOP,
            default_stop_handler,
            priority=0,
            name="default_stop"
        ))

        self.hooks.register(Hook(
            HookType.SESSION_END,
            default_session_end_handler,
            priority=0,
            name="default_session_end"
        ))

    def register_hook(
        self,
        hook_type: HookType,
        handler: Callable,
        priority: int = 0,
        name: Optional[str] = None
    ) -> None:
        """
        Register a custom lifecycle hook.

        Args:
            hook_type: Type of lifecycle event
            handler: Callable that receives context dict
            priority: Higher priority hooks run first
            name: Optional hook name
        """
        hook = Hook(hook_type, handler, priority, name)
        self.hooks.register(hook)

    def on_session_start(
        self,
        session_id: str,
        user_id: Optional[str] = None,
        query: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Called when a new session starts (MCP client connects).

        Args:
            session_id: Unique session identifier
            user_id: Optional user/agent identifier
            query: Optional initial query

        Returns:
            Context dict with hook results and session metadata
        """
        # Check if session already exists
        existing = self.active_sessions.get(session_id)
        if existing:
            logger.warning(f"Session {session_id} already active, updating")
            existing["last_activity"] = time.time()
            return existing.get("context", {})

        # Create session in storage
        session_info = self.storage.create_session(session_id, user_id)

        # Track session
        self.active_sessions[session_id] = {
            "session_id": session_id,
            "user_id": user_id,
            "start_time": time.time(),
            "last_activity": time.time(),
            "observation_count": 0,
            "context": session_info,
        }

        # Trigger SessionStart hooks
        context = {
            "session_id": session_id,
            "user_id": user_id,
            "query": query,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        hook_results = self.hooks.trigger(HookType.SESSION_START, context)

        # Collect context injections from hooks
        injected_context = []
        for result in hook_results:
            if isinstance(result, dict) and "context_block" in result:
                injected_context.append(result["context_block"])

        response = {
            "session_id": session_id,
            "status": "started",
            "context_injected": len(injected_context) > 0,
            "injected_context": injected_context,
            "hook_results": hook_results,
        }

        logger.info(
            f"Session {session_id} started "
            f"(context injected: {len(injected_context)} blocks)"
        )

        return response

    def on_tool_use(
        self,
        session_id: str,
        tool_name: str,
        tool_input: str,
        tool_output: str
    ) -> Optional[str]:
        """
        Called after MCP tool execution (PostToolUse hook).

        Args:
            session_id: Active session identifier
            tool_name: Tool that was executed
            tool_input: Tool input
            tool_output: Tool output

        Returns:
            Observation ID, or None if filtered by privacy
        """
        # Check if session is active
        if session_id not in self.active_sessions:
            logger.warning(
                f"Session {session_id} not active, skipping observation"
            )
            return None

        # Privacy filtering on both input and output
        tool_input = sanitize_for_storage(tool_input)
        tool_output = sanitize_for_storage(tool_output)

        # Create observation
        obs_id = f"obs_{uuid4().hex[:12]}"
        observation = {
            "id": obs_id,
            "session_id": session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tool_name": tool_name,
            "tool_input": tool_input,
            "tool_output": tool_output,
        }

        # Store observation
        try:
            stored_id = self.storage.add_observation(observation)

            # Update session tracking
            if session_id in self.active_sessions:
                self.active_sessions[session_id]["observation_count"] += 1
                self.active_sessions[session_id]["last_activity"] = time.time()

            # Trigger PostToolUse hooks
            context = {
                "session_id": session_id,
                "observation_id": stored_id,
                "tool_name": tool_name,
                "tool_input": tool_input,
                "tool_output": tool_output,
            }

            hook_results = self.hooks.trigger(
                HookType.POST_TOOL_USE, context
            )

            # Async processing if callback registered
            if self.observation_callback:
                try:
                    self.observation_callback(observation)
                except Exception as e:
                    logger.error(
                        f"Observation callback failed: {e}",
                        exc_info=True
                    )

            logger.debug(
                f"Logged observation {stored_id} for session {session_id}"
            )
            return stored_id

        except Exception as e:
            logger.error(
                f"Failed to store observation: {e}",
                exc_info=True
            )
            return None

    def on_stop(
        self,
        session_id: str,
        summary_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Called when session pauses (Stop hook).

        Triggers summarization of session activity.

        Args:
            session_id: Active session identifier
            summary_data: Optional pre-computed summary

        Returns:
            Summary result dict
        """
        if session_id not in self.active_sessions:
            logger.warning(f"Session {session_id} not active")
            return {"error": "Session not active"}

        # Trigger Stop hooks
        context = {
            "session_id": session_id,
            "observation_count": self.active_sessions[session_id][
                "observation_count"
            ],
            "summary_data": summary_data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        hook_results = self.hooks.trigger(HookType.STOP, context)

        # Save summary if provided
        if summary_data:
            try:
                self.storage.save_summary(session_id, summary_data)
                logger.info(f"Saved summary for session {session_id}")
            except Exception as e:
                logger.error(
                    f"Failed to save summary: {e}",
                    exc_info=True
                )

        return {
            "session_id": session_id,
            "status": "stopped",
            "summary_saved": summary_data is not None,
            "hook_results": hook_results,
        }

    def on_session_end(
        self,
        session_id: str,
        generate_summary: bool = True
    ) -> Dict[str, Any]:
        """
        Called when session ends (SessionEnd hook).

        Finalizes persistence and optionally generates summary.

        Args:
            session_id: Active session identifier
            generate_summary: Whether to generate session summary

        Returns:
            Session end result dict
        """
        if session_id not in self.active_sessions:
            logger.warning(f"Session {session_id} not active")
            return {"error": "Session not active"}

        session_data = self.active_sessions[session_id]

        # Optionally summarize before ending
        summary_result = None
        if generate_summary:
            observations = self.storage.get_session_observations(
                session_id, limit=100
            )
            if observations:
                summary = self._generate_session_summary(observations)
                try:
                    self.storage.save_summary(session_id, summary)
                    summary_result = summary
                    logger.info(
                        f"Generated summary for session {session_id} "
                        f"({len(observations)} observations)"
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to save summary: {e}",
                        exc_info=True
                    )

        # End session in storage
        ended = self.storage.end_session(session_id)

        # Trigger SessionEnd hooks
        context = {
            "session_id": session_id,
            "user_id": session_data.get("user_id"),
            "observation_count": session_data["observation_count"],
            "duration": time.time() - session_data["start_time"],
            "summary": summary_result,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        hook_results = self.hooks.trigger(HookType.SESSION_END, context)

        # Remove from active sessions
        del self.active_sessions[session_id]

        result = {
            "session_id": session_id,
            "status": "ended",
            "ended": ended,
            "summary_generated": summary_result is not None,
            "observation_count": context["observation_count"],
            "duration_seconds": context["duration"],
            "hook_results": hook_results,
        }

        logger.info(
            f"Session {session_id} ended "
            f"({context['observation_count']} observations, "
            f"{context['duration']:.1f}s)"
        )

        return result

    def _cleanup_on_exit(self):
        """Clean up all active sessions on process exit."""
        if not self.active_sessions:
            return

        logger.info(f"Cleaning up {len(self.active_sessions)} active sessions on exit")
        session_ids = list(self.active_sessions.keys())
        for session_id in session_ids:
            try:
                self.storage.end_session(session_id)
                logger.debug(f"Ended session {session_id} on exit")
            except Exception as e:
                logger.error(f"Failed to end session {session_id} on exit: {e}")

        self.active_sessions.clear()

    def get_active_sessions(self) -> List[Dict[str, Any]]:
        """
        Get all active sessions.

        Returns:
            List of active session metadata
        """
        return [
            {
                "session_id": sid,
                "user_id": data.get("user_id"),
                "observation_count": data["observation_count"],
                "duration": time.time() - data["start_time"],
                "last_activity": time.time() - data["last_activity"],
            }
            for sid, data in self.active_sessions.items()
        ]

    def get_session_info(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Get info about an active session.

        Args:
            session_id: Session identifier

        Returns:
            Session metadata or None if not active
        """
        if session_id not in self.active_sessions:
            return None

        data = self.active_sessions[session_id]
        return {
            "session_id": session_id,
            "user_id": data.get("user_id"),
            "observation_count": data["observation_count"],
            "duration": time.time() - data["start_time"],
            "is_active": True,
        }

    def _generate_session_summary(
        self,
        observations: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Generate a simple summary from session observations.

        Args:
            observations: List of observation dicts

        Returns:
            Summary dict with overview, key_facts, concepts
        """
        if not observations:
            return {
                "summary": "No observations in session",
                "key_facts": [],
                "concepts": [],
            }

        # Extract key facts from observations
        key_facts = []
        concepts = set()

        for obs in observations:
            # Add tool usage summary
            tool_name = obs.get("tool_name", "unknown")
            concepts.add(tool_name)

            # Extract facts from compressed summaries
            if obs.get("compressed_summary"):
                key_facts.append(obs["compressed_summary"][:200])

            # Collect concepts
            if obs.get("concepts"):
                concepts.update(obs["concepts"])

        # Build summary
        summary_lines = [
            f"Session with {len(observations)} tool executions",
            f"Tools used: {', '.join(sorted(set(o.get('tool_name', '') for o in observations)))}",
        ]

        if key_facts:
            summary_lines.append(f"Key findings: {len(key_facts)}")

        return {
            "summary": "\n".join(summary_lines),
            "key_facts": key_facts[:10],  # Limit to 10 facts
            "concepts": list(concepts)[:20],  # Limit to 20 concepts
        }
