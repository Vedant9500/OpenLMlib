from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional
import logging

logger = logging.getLogger(__name__)


class ContextPacker:
    """Packs retrieved findings into an optimized context window.

    Implements position-aware ranking based on "Lost in the Middle" research
    (Liu et al., 2023): models pay more attention to content at the beginning
    and end of context windows, with reduced attention to the middle.

    Strategy:
    - Most relevant findings go first and last
    - Medium-relevance findings fill the middle
    - Total token count stays within the context budget
    """

    def __init__(
        self,
        max_tokens: int = 4000,
        token_estimate_fn=None,
    ) -> None:
        self.max_tokens = max_tokens
        self._token_estimate_fn = token_estimate_fn or _estimate_tokens

    def pack(
        self,
        findings: List[Dict[str, Any]],
        score_field: str = "final_score",
    ) -> List[Dict[str, Any]]:
        """Pack findings with position-aware ranking.

        Args:
            findings: List of finding dicts (should already be sorted by score).
            score_field: Field name to use for relevance scoring.

        Returns:
            Findings reordered for optimal model attention.
        """
        if not findings:
            return []

        # Sort by score descending
        sorted_findings = sorted(
            findings,
            key=lambda x: x.get(score_field, 0.0),
            reverse=True,
        )

        # Position-aware reordering: most relevant first and last
        reordered = _interleave_ends(sorted_findings)

        # Trim to fit token budget
        packed = self._trim_to_budget(reordered)

        logger.info(
            "pack: input=%d output=%d tokens=%d/%d",
            len(findings),
            len(packed),
            self._total_tokens(packed),
            self.max_tokens,
        )
        return packed

    def _trim_to_budget(self, findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove findings that would exceed the token budget."""
        result: List[Dict[str, Any]] = []
        total = 0

        for item in findings:
            item_tokens = self._token_estimate_fn(item)
            if total + item_tokens > self.max_tokens:
                break
            result.append(item)
            total += item_tokens

        return result

    def _total_tokens(self, findings: List[Dict[str, Any]]) -> int:
        return sum(self._token_estimate_fn(item) for item in findings)

    def render_context(
        self,
        findings: List[Dict[str, Any]],
        include_scores: bool = True,
    ) -> str:
        """Render packed findings as a context string for LLM injection.

        Args:
            findings: Packed findings from self.pack().
            include_scores: Whether to include score metadata.

        Returns:
            Formatted context string.
        """
        lines: List[str] = []

        for idx, item in enumerate(findings, start=1):
            header = f"### Finding {idx}"
            if include_scores:
                score = item.get("final_score", item.get("hybrid_score", item.get("rerank_score", 0.0)))
                header += f" (score: {score:.4f})"
            lines.append(header)

            claim = item.get("claim", "")
            if claim:
                lines.append(f"Claim: {claim}")

            reasoning = item.get("reasoning", "")
            if reasoning:
                lines.append(f"Reasoning: {reasoning}")

            evidence = item.get("evidence") or []
            if evidence:
                lines.append(f"Evidence: {'; '.join(evidence)}")

            caveats = item.get("caveats") or []
            if caveats:
                lines.append(f"Caveats: {'; '.join(caveats)}")

            lines.append("")  # Blank line between findings

        return "\n".join(lines).strip()


def _interleave_ends(items: List[Any]) -> List[Any]:
    """Reorder items so highest-score items are at the beginning and end.

    Implements the "Lost in the Middle" position-aware ranking:
    - Take the top-scored item → put at position 0
    - Take the next top-scored item → put at the last position
    - Take the next → put at position 1
    - Take the next → put at second-to-last position
    - Continue until all items are placed

    For small lists (< 4 items), returns as-is since position effects are minimal.
    """
    if len(items) < 4:
        return list(items)

    result: List[Any] = [None] * len(items)
    left = 0
    right = len(items) - 1

    for i, item in enumerate(items):
        if i % 2 == 0:
            result[left] = item
            left += 1
        else:
            result[right] = item
            right -= 1

        if left > right:
            break

    # Fill any remaining None slots (shouldn't happen, but safety)
    remaining = [item for item in result if item is not None]
    return remaining


def _estimate_tokens(item: Dict[str, Any]) -> int:
    """Rough token count estimate (4 chars ≈ 1 token for English text)."""
    total_chars = 0
    for field in ("claim", "reasoning", "full_text"):
        value = item.get(field, "")
        if isinstance(value, str):
            total_chars += len(value)

    for field in ("evidence", "caveats", "tags"):
        values = item.get(field) or []
        if isinstance(values, list):
            for v in values:
                if isinstance(v, str):
                    total_chars += len(v)

    # Rough estimate: ~4 characters per token
    return max(1, total_chars // 4)
