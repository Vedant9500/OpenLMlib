from __future__ import annotations

from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class SummaryGenerator:
    """Generates summaries for clusters of findings.

    Uses simple extractive summarization based on keyword frequency
    and claim overlap. In a future iteration, this could use an LLM
    for abstractive summarization.
    """

    def __init__(
        self,
        max_summary_length: int = 200,
        max_key_points: int = 5,
    ) -> None:
        self.max_summary_length = max_summary_length
        self.max_key_points = max_key_points

    def generate_cluster_summary(
        self,
        findings: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Generate a summary for a cluster of similar findings.

        Args:
            findings: List of finding dicts with claim, evidence, reasoning.

        Returns:
            Summary dict with overview, key_points, and common_themes.
        """
        if not findings:
            return {
                "overview": "",
                "key_points": [],
                "common_themes": [],
                "finding_count": 0,
            }

        # Extract key themes from claims
        all_claims = [f.get("claim", "") for f in findings]
        common_themes = _extract_common_themes(all_claims)

        # Extract key points from evidence
        all_evidence = []
        for f in findings:
            all_evidence.extend(f.get("evidence") or [])
        key_points = _extract_key_points(all_evidence, self.max_key_points)

        # Generate overview from most representative claim
        overview = _generate_overview(findings, self.max_summary_length)

        return {
            "overview": overview,
            "key_points": key_points,
            "common_themes": common_themes,
            "finding_count": len(findings),
            "projects": list(set(f.get("project", "") for f in findings if f.get("project"))),
        }

    def generate_finding_summary(
        self,
        finding: Dict[str, Any],
    ) -> str:
        """Generate a short summary for a single finding."""
        claim = finding.get("claim", "")
        evidence = finding.get("evidence") or []
        reasoning = finding.get("reasoning", "")

        parts = [claim]
        if evidence:
            parts.append(f"Supported by: {', '.join(evidence[:2])}")
        if reasoning and len(reasoning) < 100:
            parts.append(reasoning)

        summary = " ".join(parts)
        if len(summary) > self.max_summary_length:
            summary = summary[: self.max_summary_length - 3] + "..."

        return summary


def _extract_common_themes(claims: List[str]) -> List[str]:
    """Extract common themes from a list of claims using term frequency."""
    import re
    from collections import Counter

    stopwords = {
        "a", "an", "the", "is", "are", "was", "were", "be", "been",
        "have", "has", "had", "do", "does", "did", "will", "would",
        "could", "should", "may", "might", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "as", "and", "or", "but",
        "not", "no", "it", "its", "this", "that", "these", "those",
        "improved", "reduced", "increased", "using", "used", "with",
    }

    all_tokens = []
    for claim in claims:
        tokens = re.findall(r"[a-z0-9]+", claim.lower())
        all_tokens.extend(t for t in tokens if t not in stopwords and len(t) > 2)

    # Get terms that appear in multiple claims
    claim_token_sets = [
        set(t for t in re.findall(r"[a-z0-9]+", claim.lower()) if t not in stopwords and len(t) > 2)
        for claim in claims
    ]

    theme_scores: Dict[str, int] = Counter()
    for token_set in claim_token_sets:
        for token in token_set:
            theme_scores[token] += 1

    # Themes that appear in at least 2 claims
    min_occurrences = 2 if len(claims) >= 3 else 1
    themes = [
        token for token, count in theme_scores.most_common(10)
        if count >= min_occurrences
    ]

    return themes[:5]


def _extract_key_points(evidence_items: List[str], max_points: int) -> List[str]:
    """Extract key points from evidence items."""
    if not evidence_items:
        return []

    # Deduplicate and limit
    seen = set()
    unique = []
    for ev in evidence_items:
        normalized = ev.strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append(ev.strip())

    return unique[:max_points]


def _generate_overview(findings: List[Dict[str, Any]], max_length: int) -> str:
    """Generate an overview from the most representative finding."""
    if not findings:
        return ""

    # Use the highest-confidence finding as the representative
    best = max(findings, key=lambda f: f.get("confidence", 0.0))
    claim = best.get("claim", "")

    # Add project context if multiple projects
    projects = list(set(f.get("project", "") for f in findings if f.get("project")))
    if len(projects) > 1:
        claim = f"{claim} (across {len(projects)} projects: {', '.join(projects[:3])})"
    elif len(projects) == 1:
        claim = f"{claim} (project: {projects[0]})"

    if len(claim) > max_length:
        claim = claim[: max_length - 3] + "..."

    return claim
