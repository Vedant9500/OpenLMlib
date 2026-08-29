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

from .caveman_compress import (
    caveman_compress,
    compress_context_block,
    compress_observation_summary,
)
from .context_builder import ContextBuilder
from .hooks import Hook, HookRegistry, HookType
from .knowledge_extractor import (
    KnowledgeExtractor,
    SessionKnowledge,
    extract_knowledge,
)
from .memory_retriever import ProgressiveRetriever
from .observation_queue import ObservationQueue
from .retrogit_ingest import retroactive_ingest
from .session_manager import SessionManager
from .storage import MemoryStorage

__all__ = [
    "ContextBuilder",
    "Hook",
    "HookRegistry",
    "HookType",
    "KnowledgeExtractor",
    "MemoryStorage",
    "ObservationQueue",
    "ProgressiveRetriever",
    "SessionKnowledge",
    "SessionManager",
    "caveman_compress",
    "compress_context_block",
    "compress_observation_summary",
    "extract_knowledge",
    "retroactive_ingest",
]
