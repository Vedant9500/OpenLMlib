"""
Lifecycle hook system for memory injection.

Defines hook types and registry for lifecycle events.
Inspired by claude-mem's 5-hook architecture:
- SessionStart: Inject context from previous sessions
- UserPromptSubmit: React to user query
- PostToolUse: Capture tool outputs
- Stop: Summarize session
- SessionEnd: Finalize persistence
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class HookType(Enum):
    """Lifecycle hook types for memory injection system."""

    SESSION_START = "session_start"
    """Triggered when a new session starts. Injects context from past sessions."""

    USER_PROMPT_SUBMIT = "user_prompt_submit"
    """Triggered when user submits a prompt. Can inject reactive context."""

    POST_TOOL_USE = "post_tool_use"
    """Triggered after tool execution. Captures tool outputs as observations."""

    STOP = "stop"
    """Triggered when session pauses. Generates session summary."""

    SESSION_END = "session_end"
    """Triggered when session ends. Finalizes persistence."""


class Hook:
    """A lifecycle hook with priority-based ordering."""

    def __init__(
        self,
        hook_type: HookType,
        handler: Callable[[Dict[str, Any]], Any],
        priority: int = 0,
        name: Optional[str] = None,
    ):
        """
        Create a new hook.

        Args:
            hook_type: Type of lifecycle event
            handler: Callable that receives context dict and returns result
            priority: Higher priority hooks run first (default: 0)
            name: Optional hook name for logging
        """
        self.type = hook_type
        self.handler = handler
        self.priority = priority
        self.name = name or f"{hook_type.value}_hook_{id(handler)}"

    def __repr__(self) -> str:
        return f"Hook({self.name}, priority={self.priority})"


class HookRegistry:
    """Registry for lifecycle hooks with priority-based execution."""

    def __init__(self):
        """Initialize empty hook registry."""
        self.hooks: Dict[HookType, List[Hook]] = {
            ht: [] for ht in HookType
        }

    def register(self, hook: Hook) -> None:
        """
        Register a hook.

        Args:
            hook: Hook instance to register
        """
        self.hooks[hook.type].append(hook)
        # Sort by priority (highest first)
        self.hooks[hook.type].sort(
            key=lambda h: h.priority, reverse=True
        )
        logger.debug(f"Registered hook: {hook}")

    def unregister(self, hook_type: HookType, name: str) -> bool:
        """
        Unregister a hook by name.

        Args:
            hook_type: Type of hook
            name: Hook name to remove

        Returns:
            True if hook was found and removed
        """
        hooks = self.hooks[hook_type]
        for i, hook in enumerate(hooks):
            if hook.name == name:
                hooks.pop(i)
                logger.debug(f"Unregistered hook: {name}")
                return True
        return False

    def trigger(
        self,
        hook_type: HookType,
        context: Dict[str, Any]
    ) -> List[Any]:
        """
        Trigger all hooks of a given type.

        Args:
            hook_type: Type of lifecycle event
            context: Context dict passed to all hooks

        Returns:
            List of results from all hooks
        """
        results = []
        hooks = self.hooks[hook_type]

        if not hooks:
            return results

        logger.debug(
            f"Triggering {len(hooks)} hooks for {hook_type.value}"
        )

        for hook in hooks:
            try:
                result = hook.handler(context)
                results.append(result)
                logger.debug(f"Hook {hook.name} executed successfully")
            except Exception as e:
                logger.error(
                    f"Hook {hook.name} failed: {e}",
                    exc_info=True
                )
                results.append({"error": str(e), "hook": hook.name})

        return results

    def get_hooks(self, hook_type: HookType) -> List[Hook]:
        """
        Get all hooks of a given type.

        Args:
            hook_type: Type of hook

        Returns:
            List of hooks (sorted by priority)
        """
        return self.hooks[hook_type].copy()

    def clear(self, hook_type: Optional[HookType] = None) -> None:
        """
        Clear hooks.

        Args:
            hook_type: If provided, clear only this type. Otherwise clear all.
        """
        if hook_type:
            self.hooks[hook_type] = []
        else:
            for ht in HookType:
                self.hooks[ht] = []

    def stats(self) -> Dict[str, int]:
        """
        Get hook statistics.

        Returns:
            Dict with hook counts per type
        """
        return {
            ht.value: len(hooks)
            for ht, hooks in self.hooks.items()
        }


# Default hooks for common memory operations

def default_session_start_handler(context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Default handler for SessionStart hook.
    Returns context injection data.
    """
    return {
        "hook": "session_start",
        "session_id": context.get("session_id"),
        "message": "Session started (default handler)",
    }


def default_post_tool_use_handler(context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Default handler for PostToolUse hook.
    Logs observation data.
    """
    return {
        "hook": "post_tool_use",
        "session_id": context.get("session_id"),
        "tool_name": context.get("tool_name"),
        "message": "Observation logged (default handler)",
    }


def default_stop_handler(context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Default handler for Stop hook.
    Triggers session summarization.
    """
    return {
        "hook": "stop",
        "session_id": context.get("session_id"),
        "message": "Session summary triggered (default handler)",
    }


def default_session_end_handler(context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Default handler for SessionEnd hook.
    Finalizes persistence.
    """
    return {
        "hook": "session_end",
        "session_id": context.get("session_id"),
        "message": "Session ended (default handler)",
    }
