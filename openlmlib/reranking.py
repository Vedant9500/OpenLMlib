from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import logging

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class RerankerSettings:
    model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    top_k: int = 10
    enabled: bool = True
    batch_size: int = 32


class CrossEncoderReranker:
    """Reranks retrieval candidates using a cross-encoder model.

    Cross-encoders process (query, document) pairs jointly through attention,
    producing more accurate relevance scores than bi-encoder similarity alone.
    This follows the retrieve-then-rerank pattern from Sentence Transformers.

    Usage:
        reranker = CrossEncoderReranker()
        reranked = reranker.rerank(query, candidates)
    """

    def __init__(
        self,
        model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        batch_size: int = 32,
    ) -> None:
        try:
            from sentence_transformers import CrossEncoder  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "sentence-transformers is required for cross-encoder reranking. "
                "Install it with 'pip install sentence-transformers'."
            ) from exc

        self._model = CrossEncoder(model_name)
        self.model_name = model_name
        self.batch_size = batch_size

    def score_pairs(
        self,
        query: str,
        documents: List[str],
    ) -> List[float]:
        """Score (query, document) pairs and return raw cross-encoder scores."""
        if not documents:
            return []

        pairs = [(query, doc) for doc in documents]
        raw_scores = self._model.predict(
            pairs,
            batch_size=self.batch_size,
            show_progress_bar=False,
        )
        # CrossEncoder may return numpy scalars or arrays; normalize to float
        return [float(s) for s in raw_scores]

    def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        top_k: Optional[int] = None,
        text_field: str = "claim",
        fallback_score_field: str = "final_score",
    ) -> List[Dict[str, Any]]:
        """Rerank candidate findings by cross-encoder relevance.

        Each candidate is scored by passing (query, candidate_text) through the
        cross-encoder. Results are sorted by rerank_score descending and trimmed
        to top_k.

        Args:
            query: The search query.
            candidates: List of finding dicts from the retrieval engine.
            top_k: Maximum number of results to return. Defaults to self.top_k.
            text_field: Which field to use as the document text for scoring.
            fallback_score_field: Field to use as a tiebreaker when rerank scores are equal.

        Returns:
            Reranked list with 'rerank_score' added to each item.
        """
        if not candidates:
            return []

        documents = []
        for item in candidates:
            # Build a rich text representation for scoring
            text = self._build_document_text(item, text_field)
            documents.append(text)

        scores = self.score_pairs(query, documents)

        # Attach rerank scores
        for item, score in zip(candidates, scores):
            item["rerank_score"] = float(score)

        # Sort by rerank_score descending, then by fallback_score as tiebreaker
        reranked = sorted(
            candidates,
            key=lambda x: (
                x.get("rerank_score", float("-inf")),
                x.get(fallback_score_field, 0.0),
            ),
            reverse=True,
        )

        if top_k is not None:
            reranked = reranked[:top_k]

        logger.info(
            "rerank: query='%s' candidates=%d top_k=%s returned=%d",
            query,
            len(candidates),
            top_k,
            len(reranked),
        )
        return reranked

    @staticmethod
    def _build_document_text(item: Dict[str, Any], text_field: str) -> str:
        """Build a text representation of a finding for cross-encoder scoring."""
        parts: List[str] = []

        # Primary text field
        primary = item.get(text_field, "")
        if primary:
            parts.append(primary)

        # Add reasoning for context (helps cross-encoder understand relevance)
        reasoning = item.get("reasoning", "")
        if reasoning:
            parts.append(reasoning)

        # Add evidence snippets
        evidence = item.get("evidence") or []
        if evidence:
            parts.append(" ".join(evidence))

        return " ".join(parts).strip()


class HybridReranker:
    """Combines cross-encoder reranking with existing retrieval scores.

    Produces a blended score: alpha * rerank_score + (1 - alpha) * retrieval_score.
    This preserves signal from the dual-index retrieval while boosting
    cross-encoder precision.
    """

    def __init__(
        self,
        reranker: CrossEncoderReranker,
        alpha: float = 0.7,
    ) -> None:
        """
        Args:
            reranker: The cross-encoder reranker instance.
            alpha: Weight for rerank_score vs retrieval_score (0.0-1.0).
                   Higher alpha = more trust in cross-encoder.
        """
        self.reranker = reranker
        self.alpha = alpha

    def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        top_k: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Rerank with blended scoring."""
        if not candidates:
            return []

        # Get cross-encoder scores
        reranked = self.reranker.rerank(query, candidates, top_k=None)

        # Normalize scores to [0, 1] range for blending
        rerank_scores = [item.get("rerank_score", 0.0) for item in reranked]
        retrieval_scores = [item.get("final_score", 0.0) for item in reranked]

        rerank_norm = _normalize_scores(rerank_scores)
        retrieval_norm = _normalize_scores(retrieval_scores)

        # Blend scores
        for i, item in enumerate(reranked):
            blended = (self.alpha * rerank_norm[i]) + ((1 - self.alpha) * retrieval_norm[i])
            item["hybrid_score"] = float(round(blended, 4))

        # Sort by hybrid score
        reranked.sort(key=lambda x: x.get("hybrid_score", 0.0), reverse=True)

        if top_k is not None:
            reranked = reranked[:top_k]

        return reranked


def _normalize_scores(scores: List[float]) -> List[float]:
    """Min-max normalize scores to [0, 1]. Returns zeros for empty or uniform lists."""
    if not scores:
        return []
    min_s = min(scores)
    max_s = max(scores)
    if max_s == min_s:
        return [0.5] * len(scores)
    return [(s - min_s) / (max_s - min_s) for s in scores]
