"""
Progressive memory retriever with 3-layer disclosure.

Layer 1: Search index (~50-100 tokens/result) - compact metadata
Layer 2: Timeline (~200 tokens/result) - chronological narrative
Layer 3: Full details (~500-1000 tokens/result) - complete observations

Enables token-efficient memory retrieval by filtering before fetching details.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .storage import MemoryStorage

logger = logging.getLogger(__name__)


@dataclass
class MemoryIndex:
    """Layer 1: Compact search index entry."""
    id: str
    title: str
    type: str
    timestamp: str
    session_id: str
    confidence: float
    token_estimate: int = 75  # ~50-100 tokens


@dataclass
class MemoryTimeline:
    """Layer 2: Chronological context entry."""
    id: str
    timestamp: str
    session_id: str
    narrative: str
    related: List[str] = field(default_factory=list)
    token_estimate: int = 200  # ~200 tokens


@dataclass
class MemoryDetail:
    """Layer 3: Full observation details."""
    id: str
    session_id: str
    timestamp: str
    tool_name: str
    tool_input: str
    tool_output: str
    compressed_summary: str
    facts: List[str] = field(default_factory=list)
    concepts: List[str] = field(default_factory=list)
    obs_type: str = "general"
    tags: List[str] = field(default_factory=list)
    token_estimate: int = 750  # ~500-1000 tokens


class ProgressiveRetriever:
    """3-layer progressive memory retriever."""

    def __init__(
        self,
        storage: MemoryStorage,
        retrieval_engine=None
    ):
        """
        Initialize progressive retriever.

        Args:
            storage: MemoryStorage instance
            retrieval_engine: Optional existing retrieval engine for semantic search
        """
        self.storage = storage
        self.retrieval_engine = retrieval_engine

    def layer1_search_index(
        self,
        query: str,
        limit: int = 50,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[MemoryIndex]:
        """
        Layer 1: Lightweight search index (~50-100 tokens/result).

        Returns compact metadata for filtering.
        Use this first to identify relevant memories.

        Args:
            query: Search query
            limit: Max results to return
            filters: Optional filters (tool_name, obs_type, session_id)

        Returns:
            List of MemoryIndex entries
        """
        observations = self.storage.search_observations(
            query, limit=limit, filters=filters
        )

        indexes = []
        for obs in observations:
            # Calculate confidence based on recency and completeness
            confidence = self._calculate_confidence(obs)

            index = MemoryIndex(
                id=obs["id"],
                title=self._generate_title(obs),
                type=obs.get("obs_type", "general"),
                timestamp=obs["timestamp"],
                session_id=obs["session_id"],
                confidence=confidence,
                token_estimate=75,
            )
            indexes.append(index)

        logger.debug(
            f"Layer 1 search: {len(indexes)} results for '{query}'"
        )

        return indexes

    def layer2_timeline(
        self,
        ids: List[str],
        window: str = "5m"
    ) -> List[MemoryTimeline]:
        """
        Layer 2: Chronological context (~200 tokens/result).

        Returns narrative flow around observations.
        Use after layer1 to understand sequence of events.

        Args:
            ids: List of observation IDs from layer1
            window: Time window for context (not yet implemented)

        Returns:
            List of MemoryTimeline entries
        """
        if not ids:
            return []

        observations = self.storage.get_observations_by_ids(ids)

        timelines = []
        for obs in observations:
            compressed_summary = obs.get("compressed_summary") or ""
            timeline = MemoryTimeline(
                id=obs["id"],
                timestamp=obs["timestamp"],
                session_id=obs["session_id"],
                narrative=compressed_summary[:200],
                related=obs.get("concepts", [])[:5],
                token_estimate=200,
            )
            timelines.append(timeline)

        # Sort chronologically
        timelines.sort(key=lambda t: t.timestamp)

        logger.debug(f"Layer 2 timeline: {len(timelines)} entries")

        return timelines

    def layer3_full_details(
        self,
        ids: List[str]
    ) -> List[MemoryDetail]:
        """
        Layer 3: Complete observation details (~500-1000 tokens/result).

        Returns full data for explicitly selected relevant items.
        Use only for observations identified as relevant in layers 1-2.

        Args:
            ids: List of observation IDs from layers 1-2

        Returns:
            List of MemoryDetail entries
        """
        if not ids:
            return []

        observations = self.storage.get_observations_by_ids(ids)

        details = []
        for obs in observations:
            detail = MemoryDetail(
                id=obs["id"],
                session_id=obs["session_id"],
                timestamp=obs["timestamp"],
                tool_name=obs.get("tool_name", "unknown"),
                tool_input=obs.get("tool_input", ""),
                tool_output=obs.get("tool_output", ""),
                compressed_summary=obs.get("compressed_summary", ""),
                facts=obs.get("facts", []),
                concepts=obs.get("concepts", []),
                obs_type=obs.get("obs_type", "general"),
                tags=obs.get("tags", []),
                token_estimate=750,
            )
            details.append(detail)

        logger.debug(f"Layer 3 details: {len(details)} entries")

        return details

    def auto_inject_context(
        self,
        session_id: str,
        query: Optional[str] = None,
        limit: int = 50
    ) -> Dict[str, Any]:
        """
        Automatic context injection at session start.

        Retrieves relevant memories from previous sessions.
        Returns formatted context block for LLM.

        Args:
            session_id: Current session ID
            query: Optional query to filter relevant memories
            limit: Max observations to inject

        Returns:
            Context dict with formatted context block
        """
        # Get recent or query-relevant observations
        if query:
            observations = self.storage.search_observations(
                query, limit=limit
            )
        else:
            observations = self.storage.get_recent_observations(limit=limit)

        if not observations:
            return {
                "context_block": "",
                "observation_count": 0,
                "token_estimate": 0,
                "message": "No previous memories found"
            }

        # Format context block
        context_block = self._format_context(observations)

        # Estimate tokens
        token_estimate = len(observations) * 75  # ~75 tokens per observation

        return {
            "context_block": context_block,
            "observation_count": len(observations),
            "token_estimate": token_estimate,
        }

    def _format_context(self, observations: List[Dict[str, Any]]) -> str:
        """
        Format observations into LLM-readable context block.

        Args:
            observations: List of observation dicts

        Returns:
            Formatted context string
        """
        lines = []
        lines.append("<openlmlib-memory-context>")
        lines.append(
            f"# Retrieved Knowledge ({len(observations)} items)"
        )
        lines.append("")

        for idx, obs in enumerate(observations, 1):
            # Generate title
            title = self._generate_title(obs)
            lines.append(f"## {idx}. {title[:80]}")

            # Add metadata
            if obs.get("obs_type"):
                lines.append(f"**Type**: {obs['obs_type']}")

            if obs.get("timestamp"):
                lines.append(f"**Timestamp**: {obs['timestamp'][:19]}")

            # Add compressed summary if available
            if obs.get("compressed_summary"):
                lines.append(f"**Summary**: {obs['compressed_summary'][:200]}")
            elif obs.get("tool_output"):
                # Fallback to truncated tool output
                lines.append(f"**Output**: {obs['tool_output'][:150]}...")

            # Add tags/concepts
            concepts = obs.get("concepts", [])
            if concepts:
                lines.append(
                    f"**Concepts**: {', '.join(concepts[:5])}"
                )

            lines.append("")

        lines.append("</openlmlib-memory-context>")
        lines.append("")
        lines.append(
            "This context was retrieved from previous sessions. "
            "Use it to inform your current work."
        )

        return "\n".join(lines)

    def _generate_title(self, observation: Dict[str, Any]) -> str:
        """Generate a concise title for an observation."""
        tool_name = observation.get("tool_name", "unknown")

        # Use compressed summary if available
        if observation.get("compressed_summary"):
            summary = observation["compressed_summary"]
            # Get first sentence
            first_sentence = summary.split('.')[0]
            if len(first_sentence) > 10:
                return first_sentence.strip()[:100]

        # Fallback to tool name + truncated output
        tool_output = observation.get("tool_output", "")
        if tool_output:
            first_line = tool_output.split('\n')[0].strip()
            if len(first_line) > 10:
                return f"{tool_name}: {first_line[:80]}"

        return f"{tool_name} execution"

    def _calculate_confidence(self, observation: Dict[str, Any]) -> float:
        """
        Calculate confidence score for an observation.

        Based on recency and completeness.
        """
        confidence = 0.5  # Base confidence

        # Boost for compressed summaries
        if observation.get("compressed_summary"):
            confidence += 0.2

        # Boost for complete observations
        if observation.get("facts") and observation.get("concepts"):
            confidence += 0.2

        # Boost for certain types
        if observation.get("obs_type") in ["discovery", "decision"]:
            confidence += 0.1

        return min(confidence, 1.0)
