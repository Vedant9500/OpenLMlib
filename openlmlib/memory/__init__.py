"""
Memory injection system for OpenLMlib.

Provides lifecycle-based memory management with progressive disclosure:
- Session tracking and lifecycle hooks
- Observation capture and compression
- 3-layer progressive retrieval (index → timeline → details)
- Privacy filtering and context building

Inspired by claude-mem architecture, adapted for MCP-native workflow.
"""

from .hooks import HookType, HookRegistry, Hook
from .session_manager import SessionManager
from .observation_queue import ObservationQueue
from .memory_retriever import ProgressiveRetriever
from .storage import MemoryStorage

__all__ = [
    "HookType",
    "HookRegistry",
    "Hook",
    "SessionManager",
    "ObservationQueue",
    "ProgressiveRetriever",
    "MemoryStorage",
]
