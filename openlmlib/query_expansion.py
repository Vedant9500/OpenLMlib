from __future__ import annotations

from typing import Any, Dict, List, Optional
import logging
import re

logger = logging.getLogger(__name__)


class QueryExpander:
    """Expands a search query into multiple rephrased variants.

    This implements the "Rewrite-Retrieve-Read" pattern (Ma et al., 2023)
    where query expansion helps bridge the gap between user intent and
    the vocabulary used in stored findings.

    Two strategies are supported:
    1. Rule-based expansion (no LLM required) — synonym generation, keyword extraction
    2. LLM-based expansion (requires an LLM client) — semantic rephrasing

    For Phase 4, we use rule-based expansion to keep the system local and free.
    LLM-based expansion can be added later as an optional flag.
    """

    def __init__(
        self,
        max_variants: int = 3,
        include_original: bool = True,
    ) -> None:
        self.max_variants = max_variants
        self.include_original = include_original

    def expand(
        self,
        query: str,
        strategy: str = "rule_based",
    ) -> List[str]:
        """Expand a query into multiple variants.

        Args:
            query: The original search query.
            strategy: Expansion strategy ('rule_based' or 'llm').

        Returns:
            List of query variants (includes original if include_original=True).
        """
        variants: List[str] = []

        if strategy == "rule_based":
            variants = self._rule_based_expand(query)
        elif strategy == "llm":
            variants = self._llm_expand(query)
        else:
            variants = self._rule_based_expand(query)

        # Deduplicate while preserving order
        seen = set()
        unique: List[str] = []
        for v in variants:
            normalized = v.strip().lower()
            if normalized and normalized not in seen:
                seen.add(normalized)
                unique.append(v.strip())

        # Ensure original query is first if requested
        if self.include_original and query.strip() not in seen:
            unique.insert(0, query.strip())

        return unique[: self.max_variants + (1 if self.include_original else 0)]

    def _rule_based_expand(self, query: str) -> List[str]:
        """Generate query variants using rule-based transformations."""
        variants: List[str] = [query]

        # Strategy 1: Keyword-focused variant (extract key terms)
        keywords = _extract_keywords(query)
        if keywords:
            keyword_query = " ".join(keywords)
            if keyword_query != query.strip():
                variants.append(keyword_query)

        # Strategy 2: Broader variant (remove modifiers)
        broader = _remove_modifiers(query)
        if broader and broader != query.strip():
            variants.append(broader)

        # Strategy 3: More specific variant (add common technical qualifiers)
        specific = _add_qualifiers(query)
        if specific != query.strip():
            variants.append(specific)

        return variants

    def _llm_expand(self, query: str) -> List[str]:
        """LLM-based query expansion (placeholder for future integration).

        When an LLM client is available, this would prompt the model to
        generate semantically equivalent rephrasings of the query.

        For now, falls back to rule-based expansion.
        """
        logger.warning("LLM-based query expansion not yet implemented; using rule-based fallback")
        return self._rule_based_expand(query)

    def expand_and_retrieve(
        self,
        query: str,
        retrieve_fn,
        strategy: str = "rule_based",
        final_k: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Expand query, retrieve for each variant, and merge results.

        Args:
            query: Original query.
            retrieve_fn: Callable(query) -> dict with 'items' key.
            strategy: Expansion strategy.
            final_k: Maximum total results after merging.

        Returns:
            Merged and deduplicated retrieval results.
        """
        variants = self.expand(query, strategy)
        all_items: Dict[str, Dict[str, Any]] = {}

        for variant in variants:
            result = retrieve_fn(variant)
            for item in result.get("items", []):
                item_id = item.get("id")
                if item_id and item_id not in all_items:
                    item["expansion_variant"] = variant
                    all_items[item_id] = item

        merged = list(all_items.values())

        # Sort by existing score
        merged.sort(key=lambda x: x.get("final_score", 0.0), reverse=True)

        if final_k is not None:
            merged = merged[:final_k]

        logger.info(
            "expand_and_retrieve: query='%s' variants=%d merged=%d",
            query,
            len(variants),
            len(merged),
        )
        return merged


def _extract_keywords(query: str) -> List[str]:
    """Extract content words from query, removing stopwords."""
    stopwords = {
        "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "shall", "can", "need", "dare", "ought",
        "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
        "as", "into", "through", "during", "before", "after", "above", "below",
        "between", "out", "off", "over", "under", "again", "further", "then",
        "once", "and", "but", "or", "nor", "not", "so", "yet", "both",
        "either", "neither", "each", "every", "all", "any", "few", "more",
        "most", "other", "some", "such", "no", "only", "own", "same", "than",
        "too", "very", "just", "because", "if", "when", "where", "how", "what",
        "which", "who", "whom", "this", "that", "these", "those", "i", "me",
        "my", "myself", "we", "our", "ours", "ourselves", "you", "your",
        "yours", "yourself", "yourselves", "he", "him", "his", "himself",
        "she", "her", "hers", "herself", "it", "its", "itself", "they",
        "them", "their", "theirs", "themselves",
    }

    tokens = re.findall(r"[a-zA-Z0-9]+", query.lower())
    return [t for t in tokens if t not in stopwords and len(t) > 2]


def _remove_modifiers(query: str) -> str:
    """Remove adverbial modifiers to create a broader query."""
    modifiers = [
        r"\b(very|really|quite|extremely|highly|particularly|specifically)\b",
        r"\b(best|top|most|great|good|better|worst|bad|worse)\b",
        r"\b(fast|quick|quickly|slow|slowly|efficient|efficiently)\b",
    ]
    result = query
    for pattern in modifiers:
        result = re.sub(pattern, "", result, flags=re.IGNORECASE)
    # Clean up extra whitespace
    result = re.sub(r"\s+", " ", result).strip()
    return result


def _add_qualifiers(query: str) -> str:
    """Add common technical qualifiers to make the query more specific."""
    tokens = set(re.findall(r"[a-zA-Z0-9]+", query.lower()))

    # Detect domain and add relevant qualifiers
    if any(word in tokens for word in ["api", "endpoint", "request", "response"]):
        return f"{query} performance optimization latency"
    if any(word in tokens for word in ["cache", "caching", "redis", "memcached"]):
        return f"{query} caching strategy implementation"
    if any(word in tokens for word in ["database", "db", "sql", "query", "migration"]):
        return f"{query} database schema migration"
    if any(word in tokens for word in ["deploy", "deployment", "ci", "cd", "pipeline"]):
        return f"{query} deployment ci cd pipeline"
    if any(word in tokens for word in ["test", "testing", "unit", "integration"]):
        return f"{query} testing strategy unit integration"
    if any(word in tokens for word in ["security", "auth", "authentication", "authorization"]):
        return f"{query} security authentication authorization"

    return query
