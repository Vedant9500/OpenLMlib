"""
Memory injection system for OpenLMlib.

Provides lifecycle-based memory management with progressive disclosure:
- Session tracking and lifecycle hooks
- Observation capture and compression (extractive + caveman linguistic)
- 3-layer progressive retrieval (index → timeline → details)
- Privacy filtering and context building

Inspired by claude-mem architecture, adapted for MCP-native workflow.
Caveman compression adds 60% additional token reduction.
"""

from .hooks import HookType, HookRegistry, Hook
from .session_manager import SessionManager
from .observation_queue import ObservationQueue
from .memory_retriever import ProgressiveRetriever
from .storage import MemoryStorage
from .context_builder import ContextBuilder
from .caveman_compress import caveman_compress, compress_context_block, compress_observation_summary

__all__ = [
    "HookType",
    "HookRegistry",
    "Hook",
    "SessionManager",
    "ObservationQueue",
    "ProgressiveRetriever",
    "MemoryStorage",
    "ContextBuilder",
    "caveman_compress",
    "compress_context_block",
    "compress_observation_summary",
]
