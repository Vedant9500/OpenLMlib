from __future__ import annotations

from dataclasses import dataclass
import copy
from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class DecomposedFinding:
    """A finding decomposed into its core components."""
    id: str
    claim: str
    evidence: List[str]
    reasoning: str
    caveats: List[str]
    relevance_score: float = 0.0
    filtered: bool = False
    filter_reason: str = ""


class DocumentDecomposer:
    """Decomposes retrieved findings into claim + evidence + caveats components.

    Inspired by CRAG's decompose-then-recompose approach: after retrieval,
    each finding is split into structured components, and low-relevance
    sections are filtered out before context packing.

    This saves context window space (~20% per the plan) by removing
    tangential evidence/caveats that don't match the query intent.
    """

    def __init__(
        self,
        min_relevance_threshold: float = 0.3,
        include_caveats: bool = True,
        max_evidence_items: int = 3,
    ) -> None:
        self.min_relevance_threshold = min_relevance_threshold
        self.include_caveats = include_caveats
        self.max_evidence_items = max_evidence_items

    def decompose(
        self,
        finding: Dict[str, Any],
        query: str,
    ) -> DecomposedFinding:
        """Decompose a single finding into structured components.

        Args:
            finding: A retrieval result item dict.
            query: The original search query.

        Returns:
            DecomposedFinding with relevance scores per component.
        """
        claim = finding.get("claim", "")
        evidence = finding.get("evidence") or []
        reasoning = finding.get("reasoning", "")
        caveats = finding.get("caveats") or []

        # Score each component against the query
        claim_score = _component_relevance(query, claim)
        evidence_scores = [_component_relevance(query, ev) for ev in evidence]
        reasoning_score = _component_relevance(query, reasoning)
        caveats_scores = [_component_relevance(query, c) for c in caveats]

        # Filter evidence items below threshold
        filtered_evidence = [
            ev for ev, score in zip(evidence, evidence_scores)
            if score >= self.min_relevance_threshold
        ]
        # Cap evidence items
        filtered_evidence = filtered_evidence[: self.max_evidence_items]

        # Filter caveats if enabled
        filtered_caveats = []
        if self.include_caveats:
            filtered_caveats = [
                c for c, score in zip(caveats, caveats_scores)
                if score >= self.min_relevance_threshold
            ]

        # Determine if the finding as a whole is relevant
        overall_score = max(claim_score, reasoning_score)
        filtered = overall_score < self.min_relevance_threshold

        return DecomposedFinding(
            id=finding.get("id", ""),
            claim=claim,
            evidence=filtered_evidence,
            reasoning=reasoning if reasoning_score >= self.min_relevance_threshold else "",
            caveats=filtered_caveats,
            relevance_score=overall_score,
            filtered=filtered,
            filter_reason="low_relevance" if filtered else "",
        )

    def decompose_many(
        self,
        findings: List[Dict[str, Any]],
        query: str,
    ) -> List[DecomposedFinding]:
        """Decompose multiple findings."""
        return [self.decompose(f, query) for f in findings]

    def recompose(
        self,
        decomposed: List[DecomposedFinding],
        originals_by_id: Optional[Dict[str, Dict[str, Any]]] = None,
        max_findings: int = 5,
    ) -> List[Dict[str, Any]]:
        """Recompose decomposed findings back into context-ready dicts.

        Filters out low-relevance findings and rebuilds compact representations.

        Args:
            decomposed: List of decomposed findings.
            max_findings: Maximum number of findings to include.

        Returns:
            Recomposed finding dicts ready for context packing.
        """
        # Filter out fully filtered findings
        active = [d for d in decomposed if not d.filtered]

        # Sort by relevance score
        active.sort(key=lambda d: d.relevance_score, reverse=True)
        active = active[:max_findings]

        recomposed: List[Dict[str, Any]] = []
        for d in active:
            item = copy.deepcopy((originals_by_id or {}).get(d.id, {}))
            item["id"] = d.id
            item["claim"] = d.claim
            item["evidence"] = d.evidence
            item["reasoning"] = d.reasoning
            item["caveats"] = d.caveats
            item["relevance_score"] = d.relevance_score
            recomposed.append(item)

        logger.info(
            "recompose: input=%d filtered=%d output=%d",
            len(decomposed),
            len(decomposed) - len(active),
            len(recomposed),
        )
        return recomposed

    def decompose_and_recompose(
        self,
        findings: List[Dict[str, Any]],
        query: str,
        max_findings: int = 5,
    ) -> List[Dict[str, Any]]:
        """Full decompose-then-recompose pipeline."""
        originals_by_id = {
            str(item.get("id")): item
            for item in findings
            if item.get("id")
        }
        decomposed = self.decompose_many(findings, query)
        return self.recompose(
            decomposed,
            originals_by_id=originals_by_id,
            max_findings=max_findings,
        )


def _component_relevance(query: str, text: str) -> float:
    """Estimate relevance of a text component to the query.

    Uses a simple keyword overlap + length heuristic. In a future iteration,
    this could use a lightweight cross-encoder for more accurate scoring.
    """
    if not text or not query:
        return 0.0

    query_tokens = set(_tokenize(query))
    text_tokens = set(_tokenize(text))

    if not query_tokens or not text_tokens:
        return 0.0

    overlap = query_tokens & text_tokens
    # Jaccard-like score, weighted by query coverage
    query_coverage = len(overlap) / len(query_tokens) if query_tokens else 0.0
    text_coverage = len(overlap) / len(text_tokens) if text_tokens else 0.0

    # Weight query coverage more heavily
    score = (0.7 * query_coverage) + (0.3 * text_coverage)
    return float(min(1.0, score))


def _tokenize(text: str) -> List[str]:
    """Simple tokenizer for relevance scoring."""
    import re
    stopwords = {
        "a", "an", "the", "is", "are", "was", "were", "be", "been",
        "have", "has", "had", "do", "does", "did", "will", "would",
        "could", "should", "may", "might", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "as", "and", "or", "but",
        "not", "no", "it", "its", "this", "that", "these", "those",
    }
    tokens = re.findall(r"[a-zA-Z0-9]+", text.lower())
    return [t for t in tokens if t not in stopwords and len(t) > 2]
