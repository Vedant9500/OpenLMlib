"""
Context builder for memory injection.

Formats retrieved memories into LLM-readable context blocks.
Handles session start and prompt-specific context injection.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .memory_retriever import ProgressiveRetriever

logger = logging.getLogger(__name__)


class ContextBuilder:
    """Builds context blocks for LLM injection."""

    def __init__(self, retriever: ProgressiveRetriever):
        """
        Initialize context builder.

        Args:
            retriever: ProgressiveRetriever instance
        """
        self.retriever = retriever

    def build_session_start_context(
        self,
        session_id: str,
        query: Optional[str] = None,
        limit: int = 50
    ) -> str:
        """
        Build context block for session start.

        This gets injected into system prompt when session starts.

        Args:
            session_id: Current session ID
            query: Optional initial query to filter relevant memories
            limit: Max observations to include

        Returns:
            Formatted context string for LLM
        """
        # Get relevant memories
        injection = self.retriever.auto_inject_context(
            session_id, query, limit
        )

        context_block = injection.get("context_block", "")

        if not context_block:
            logger.info(f"No context injected for session {session_id}")
            return ""

        # Format as system instruction
        context_lines = []
        context_lines.append("# Previous Session Context")
        context_lines.append("")
        context_lines.append(
            f"The following knowledge has been retrieved from "
            f"previous sessions ({injection.get('observation_count', 0)} items):"
        )
        context_lines.append("")
        context_lines.append(context_block)
        context_lines.append("")
        context_lines.append(
            "Use this context to inform your current work. "
            "This knowledge persists across sessions."
        )

        context = "\n".join(context_lines)

        logger.info(
            f"Built session start context: "
            f"{injection.get('observation_count', 0)} observations, "
            f"{len(context)} chars"
        )

        return context

    def build_prompt_context(
        self,
        session_id: str,
        user_prompt: str,
        limit: int = 20
    ) -> str:
        """
        Build context for specific user prompt.

        More targeted than session start context.
        Uses only layer 1 (index) for efficiency.

        Args:
            session_id: Current session ID
            user_prompt: User's query
            limit: Max observations to include

        Returns:
            Formatted context string for LLM
        """
        # Progressive disclosure: Layer 1 only
        index = self.retriever.layer1_search_index(
            user_prompt, limit=limit
        )

        if not index:
            logger.debug(f"No context for prompt: {user_prompt[:50]}")
            return ""

        context_lines = []
        context_lines.append("# Relevant Previous Context")
        context_lines.append("")
        context_lines.append(
            f"Found {len(index)} relevant memories for your query:"
        )
        context_lines.append("")

        for item in index:
            context_lines.append(
                f"- [{item.type}] {item.title[:80]} "
                f"(ID: {item.id}, Confidence: {item.confidence:.2f})"
            )

        context_lines.append("")
        context_lines.append(
            "Use `memory_get_observations` tool to fetch full details "
            "if you need complete context for any of these items."
        )

        context = "\n".join(context_lines)

        logger.debug(
            f"Built prompt context: {len(index)} items, {len(context)} chars"
        )

        return context

    def build_progressive_context(
        self,
        session_id: str,
        user_prompt: str,
        layer: int = 1,
        ids: Optional[List[str]] = None,
        limit: int = 50
    ) -> Dict[str, Any]:
        """
        Build context using progressive disclosure.

        Args:
            session_id: Current session ID
            user_prompt: User's query
            layer: Which layer to use (1, 2, or 3)
            ids: Optional IDs from previous layer
            limit: Max results

        Returns:
            Context dict with results and metadata
        """
        result = {
            "session_id": session_id,
            "layer": layer,
            "context_block": "",
            "item_count": 0,
            "token_estimate": 0,
        }

        if layer == 1:
            # Layer 1: Search index
            index = self.retriever.layer1_search_index(
                user_prompt, limit=limit
            )
            result["item_count"] = len(index)
            result["token_estimate"] = len(index) * 75
            result["items"] = [item.__dict__ for item in index]

            # Format context
            if index:
                lines = [
                    f"# Search Results ({len(index)} items)",
                    "",
                ]
                for item in index:
                    lines.append(
                        f"- **{item.title[:80]}** "
                        f"({item.type}, {item.confidence:.2f})"
                    )
                    lines.append(f"  ID: `{item.id}`")
                lines.append("")
                lines.append(
                    "Call with `layer=2` or `layer=3` and these IDs "
                    "to get more details."
                )

                result["context_block"] = "\n".join(lines)

        elif layer == 2:
            # Layer 2: Timeline
            if not ids:
                result["error"] = "IDs required for layer 2"
                return result

            timeline = self.retriever.layer2_timeline(ids)
            result["item_count"] = len(timeline)
            result["token_estimate"] = len(timeline) * 200
            result["items"] = [item.__dict__ for item in timeline]

            # Format context
            if timeline:
                lines = [
                    f"# Timeline Context ({len(timeline)} items)",
                    "",
                ]
                for item in timeline:
                    lines.append(f"## {item.timestamp[:19]}")
                    lines.append(f"**Session**: {item.session_id}")
                    lines.append(f"**Narrative**: {item.narrative[:200]}")
                    if item.related:
                        lines.append(
                            f"**Related**: {', '.join(item.related[:5])}"
                        )
                    lines.append("")

                result["context_block"] = "\n".join(lines)

        elif layer == 3:
            # Layer 3: Full details
            if not ids:
                result["error"] = "IDs required for layer 3"
                return result

            details = self.retriever.layer3_full_details(ids)
            result["item_count"] = len(details)
            result["token_estimate"] = len(details) * 750
            result["items"] = [item.__dict__ for item in details]

            # Format context
            if details:
                lines = [
                    f"# Full Observation Details ({len(details)} items)",
                    "",
                ]
                for item in details:
                    lines.append(f"## {item.id}")
                    lines.append(f"**Tool**: {item.tool_name}")
                    lines.append(f"**Type**: {item.obs_type}")
                    lines.append("")

                    if item.compressed_summary:
                        lines.append(f"**Summary**: {item.compressed_summary}")
                        lines.append("")

                    if item.facts:
                        lines.append("**Facts**:")
                        for fact in item.facts[:5]:
                            lines.append(f"- {fact}")
                        lines.append("")

                    if item.concepts:
                        lines.append(
                            f"**Concepts**: {', '.join(item.concepts[:10])}"
                        )
                        lines.append("")

                result["context_block"] = "\n".join(lines)

        else:
            result["error"] = f"Invalid layer: {layer} (must be 1, 2, or 3)"

        return result
