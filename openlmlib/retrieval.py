from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import db
from .embeddings import build_contextual_query


@dataclass
class RetrievalFilters:
    project: Optional[str] = None
    tags: Optional[List[str]] = None
    created_after: Optional[str] = None
    created_before: Optional[str] = None
    confidence_min: Optional[float] = None


@dataclass
class Phase4Options:
    """Optional Phase 4 retrieval enhancements."""
    rerank: bool = True
    rerank_top_k: Optional[int] = None
    expand_query: bool = False
    decompose: bool = True
    deduplicate: bool = True
    dedup_threshold: float = 0.85
    pack_context: bool = False
    max_context_tokens: int = 4000
    reasoning_trace: bool = True


class RetrievalEngine:
    def __init__(self, conn, embedder, vector_store, settings) -> None:
        self._conn = conn
        self._embedder = embedder
        self._vector_store = vector_store
        self._settings = settings

    def search(
        self,
        query: str,
        filters: Optional[RetrievalFilters] = None,
        semantic_k: Optional[int] = None,
        lexical_k: Optional[int] = None,
        final_k: Optional[int] = None,
    ) -> Dict[str, Any]:
        filters = filters or RetrievalFilters()
        if semantic_k is None:
            semantic_k = self._settings.retrieval.semantic_k
        if lexical_k is None:
            lexical_k = self._settings.retrieval.lexical_k
        if final_k is None:
            final_k = self._settings.retrieval.final_k

        semantic_items = self._semantic_search(query, filters, semantic_k)
        lexical_items = self._lexical_search(query, filters, lexical_k)

        merged = self._merge_results(semantic_items, lexical_items)
        ranked = sorted(merged.values(), key=lambda item: item["_sort"], reverse=True)
        top = ranked[:final_k]
        for item in top:
            item.pop("_sort", None)

        return {
            "query": query,
            "filters": {
                "project": filters.project,
                "tags": filters.tags or [],
                "created_after": filters.created_after,
                "created_before": filters.created_before,
                "confidence_min": filters.confidence_min,
            },
            "items": top,
            "meta": {
                "semantic_candidates": len(semantic_items),
                "lexical_candidates": len(lexical_items),
                "combined_candidates": len(ranked),
            },
        }

    def search_enhanced(
        self,
        query: str,
        filters: Optional[RetrievalFilters] = None,
        options: Optional[Phase4Options] = None,
        semantic_k: Optional[int] = None,
        lexical_k: Optional[int] = None,
        final_k: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Enhanced search with Phase 4 features: reranking, query expansion, decomposition, packing."""
        from time import monotonic

        options = options or Phase4Options()
        filters = filters or RetrievalFilters()
        timings: Dict[str, float] = {}

        # Step 1: Query expansion (optional)
        t0 = monotonic()
        effective_query = query
        expansion_info: Dict[str, Any] = {}
        if options.expand_query:
            expansion_info = self._expand_query(query, filters)
            effective_query = expansion_info.get("primary_query", query)
        timings["expansion"] = monotonic() - t0

        # Step 2: Base retrieval (dual-index search)
        t1 = monotonic()
        if semantic_k is None:
            semantic_k = self._settings.retrieval.semantic_k
        if lexical_k is None:
            lexical_k = self._settings.retrieval.lexical_k

        # Oversample for reranking
        effective_semantic_k = semantic_k
        if options.rerank:
            effective_semantic_k = semantic_k * max(1, self._settings.retrieval.semantic_oversample_factor)

        semantic_items = self._semantic_search(effective_query, filters, effective_semantic_k)
        lexical_items = self._lexical_search(effective_query, filters, lexical_k)
        merged = self._merge_results(semantic_items, lexical_items)
        candidates = sorted(merged.values(), key=lambda item: item["_sort"], reverse=True)
        for item in candidates:
            item.pop("_sort", None)
        timings["retrieval"] = monotonic() - t1

        # Step 3: Reranking (optional)
        t2 = monotonic()
        rerank_info: Dict[str, Any] = {}
        if options.rerank and candidates:
            rerank_top_k = options.rerank_top_k or self._settings.phase4.reranking.top_k
            candidates, rerank_info = self._rerank(query, candidates, rerank_top_k)
        timings["reranking"] = monotonic() - t2

        # Step 4: Document decomposition (optional)
        t3 = monotonic()
        decomposition_info: Dict[str, Any] = {}
        if options.decompose and candidates:
            candidates, decomposition_info = self._decompose(query, candidates)
        timings["decomposition"] = monotonic() - t3

        # Step 5: Deduplication (optional)
        t4 = monotonic()
        dedup_info: Dict[str, Any] = {}
        if options.deduplicate and candidates:
            candidates, dedup_info = self._deduplicate(candidates, options.dedup_threshold)
        timings["deduplication"] = monotonic() - t4

        # Step 6: Final trimming
        if final_k is None:
            final_k = self._settings.retrieval.final_k
        top = candidates[:final_k]

        # Step 7: Reasoning trace (optional)
        if options.reasoning_trace and top:
            top = self._add_reasoning_trace(top, query)

        # Step 8: Context packing (optional, affects rendering not the items themselves)
        packing_info: Dict[str, Any] = {}
        if options.pack_context and top:
            top, packing_info = self._pack_context(top)

        total_time = sum(timings.values())

        return {
            "query": query,
            "effective_query": effective_query,
            "filters": {
                "project": filters.project,
                "tags": filters.tags or [],
                "created_after": filters.created_after,
                "created_before": filters.created_before,
                "confidence_min": filters.confidence_min,
            },
            "items": top,
            "meta": {
                "semantic_candidates": len(semantic_items),
                "lexical_candidates": len(lexical_items),
                "combined_candidates": len(candidates),
                "final_k": final_k,
                "phase4": {
                    "expansion": expansion_info,
                    "reranking": rerank_info,
                    "decomposition": decomposition_info,
                    "deduplication": dedup_info,
                    "packing": packing_info,
                },
                "timings": timings,
                "total_time": total_time,
            },
        }

    def _deduplicate(
        self,
        candidates: List[Dict[str, Any]],
        threshold: float = 0.85,
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Merge similar findings across projects to reduce redundancy.

        Uses claim text similarity (Jaccard token overlap) to detect near-duplicates.
        When duplicates are found, keeps the highest-scored one and merges project tags.
        """
        if len(candidates) < 2:
            return candidates, {"status": "ok", "duplicates_removed": 0}

        # Pre-tokenize all candidates once to avoid repeated regex scans
        candidate_tokens = []
        for candidate in candidates:
            candidate_tokens.append(set(_tokenize_for_trace(candidate.get("claim", ""))))

        kept: List[Dict[str, Any]] = []
        kept_tokens: List[set[str]] = []
        duplicates_removed = 0
        merged_from: Dict[str, List[str]] = {}  # kept_id → [merged_ids]

        for idx, candidate in enumerate(candidates):
            is_duplicate = False
            cand_tok = candidate_tokens[idx]

            for kept_idx, existing in enumerate(kept):
                # Use pre-computed tokens instead of re-tokenizing
                sim = _jaccard_similarity(cand_tok, kept_tokens[kept_idx])
                if sim >= threshold:
                    # Merge: add project/tag info to the existing item
                    if candidate.get("project") and candidate["project"] != existing.get("project"):
                        existing_projects = existing.get("projects", [existing.get("project", "")])
                        if candidate["project"] not in existing_projects:
                            existing["projects"] = existing_projects + [candidate["project"]]
                            existing["claim"] = f"{existing.get('claim', '')} [also in {candidate['project']}]"

                    # Merge tags
                    existing_tags = set(existing.get("tags") or [])
                    candidate_tags = set(candidate.get("tags") or [])
                    merged_tags = existing_tags | candidate_tags
                    if merged_tags != existing_tags:
                        existing["tags"] = list(merged_tags)

                    merged_from.setdefault(existing["id"], []).append(candidate["id"])
                    is_duplicate = True
                    duplicates_removed += 1
                    break

            if not is_duplicate:
                kept.append(candidate)
                kept_tokens.append(cand_tok)

        # Add merge metadata
        for item in kept:
            if item["id"] in merged_from:
                item["merged_from"] = merged_from[item["id"]]

        return kept, {
            "status": "ok",
            "input_count": len(candidates),
            "output_count": len(kept),
            "duplicates_removed": duplicates_removed,
        }

    def _add_reasoning_trace(
        self,
        items: List[Dict[str, Any]],
        query: str,
    ) -> List[Dict[str, Any]]:
        """Add a reasoning trace explaining why each finding was retrieved.

        The trace includes which retrieval path matched (semantic/lexical/both),
        score breakdown, and key matching terms.
        """
        query_tokens = set(_tokenize_for_trace(query))

        for item in items:
            trace: Dict[str, Any] = {}

            # Which retrieval paths matched
            has_semantic = "semantic_score" in item
            has_lexical = "lexical_score" in item
            if has_semantic and has_lexical:
                trace["retrieval_path"] = "semantic + lexical"
            elif has_semantic:
                trace["retrieval_path"] = "semantic only"
            else:
                trace["retrieval_path"] = "lexical only"

            # Score breakdown
            trace["scores"] = {
                "semantic": item.get("semantic_score"),
                "lexical": item.get("lexical_score"),
                "recency": item.get("recency_score"),
                "final": item.get("final_score"),
            }
            if "rerank_score" in item:
                trace["scores"]["rerank"] = item["rerank_score"]
            if "hybrid_score" in item:
                trace["scores"]["hybrid"] = item["hybrid_score"]

            # Matching terms
            claim_tokens = set(_tokenize_for_trace(item.get("claim", "")))
            matching = query_tokens & claim_tokens
            trace["matching_terms"] = list(matching) if matching else []

            # Confidence and staleness context
            trace["confidence"] = item.get("confidence")
            if item.get("pending_review"):
                trace["staleness_warning"] = "Finding is pending review (age exceeds validity window)"

            item["reasoning_trace"] = trace

        return items

    def _expand_query(
        self,
        query: str,
        filters: RetrievalFilters,
    ) -> Dict[str, Any]:
        """Expand query and retrieve with multiple variants, merging results."""
        try:
            from .query_expansion import QueryExpander
        except ImportError:
            return {"status": "error", "message": "query_expansion module not available"}

        expander = QueryExpander(
            max_variants=self._settings.phase4.query_expansion.max_variants,
            include_original=True,
        )
        variants = expander.expand(query, strategy=self._settings.phase4.query_expansion.strategy)

        all_items: Dict[str, Dict[str, Any]] = {}
        for variant in variants:
            semantic_items = self._semantic_search(variant, filters, self._settings.retrieval.semantic_k)
            lexical_items = self._lexical_search(variant, filters, self._settings.retrieval.lexical_k)
            merged = self._merge_results(semantic_items, lexical_items)
            for item_id, item in merged.items():
                if item_id not in all_items:
                    item["expansion_variant"] = variant
                    all_items[item_id] = item

        merged_list = list(all_items.values())
        merged_list.sort(key=lambda x: x.get("final_score", 0.0), reverse=True)

        return {
            "status": "ok",
            "variants": variants,
            "primary_query": query,
            "merged_count": len(merged_list),
        }

    def _rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        top_k: int,
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Rerank candidates using cross-encoder."""
        rerank_settings = self._settings.phase4.reranking
        if not rerank_settings.enabled:
            return candidates, {"status": "disabled"}

        try:
            from .reranking import CrossEncoderReranker, HybridReranker
        except ImportError:
            return candidates, {"status": "error", "message": "reranking module not available"}

        try:
            reranker = CrossEncoderReranker(
                model_name=rerank_settings.model_name,
                batch_size=rerank_settings.batch_size,
            )
            hybrid = HybridReranker(reranker, alpha=rerank_settings.alpha)
            reranked = hybrid.rerank(query, candidates, top_k=top_k)

            return reranked, {
                "status": "ok",
                "model": rerank_settings.model_name,
                "input_count": len(candidates),
                "output_count": len(reranked),
            }
        except Exception as exc:
            # Fallback: return candidates without reranking
            return candidates, {
                "status": "error",
                "message": str(exc),
                "fallback": True,
            }

    def _decompose(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Decompose and recompose candidates to filter low-relevance sections."""
        decomp_settings = self._settings.phase4.decomposition
        if not decomp_settings.enabled:
            return candidates, {"status": "disabled"}

        try:
            from .decomposition import DocumentDecomposer
        except ImportError:
            return candidates, {"status": "error", "message": "decomposition module not available"}

        try:
            decomposer = DocumentDecomposer(
                min_relevance_threshold=decomp_settings.min_relevance_threshold,
                include_caveats=decomp_settings.include_caveats,
                max_evidence_items=decomp_settings.max_evidence_items,
            )
            recomposed = decomposer.decompose_and_recompose(candidates, query)

            return recomposed, {
                "status": "ok",
                "input_count": len(candidates),
                "output_count": len(recomposed),
                "filtered_count": len(candidates) - len(recomposed),
            }
        except Exception as exc:
            return candidates, {
                "status": "error",
                "message": str(exc),
                "fallback": True,
            }

    def _pack_context(
        self,
        items: List[Dict[str, Any]],
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Apply position-aware context packing."""
        pack_settings = self._settings.phase4.packing
        if not pack_settings.enabled:
            return items, {"status": "disabled"}

        try:
            from .packing import ContextPacker
        except ImportError:
            return items, {"status": "error", "message": "packing module not available"}

        try:
            packer = ContextPacker(max_tokens=pack_settings.max_tokens)
            packed = packer.pack(items)
            rendered = packer.render_context(packed)

            return packed, {
                "status": "ok",
                "input_count": len(items),
                "output_count": len(packed),
                "estimated_tokens": packer._total_tokens(packed),
                "max_tokens": pack_settings.max_tokens,
                "rendered_context": rendered,
            }
        except Exception as exc:
            return items, {
                "status": "error",
                "message": str(exc),
                "fallback": True,
            }

    def _semantic_search(
        self,
        query: str,
        filters: RetrievalFilters,
        semantic_k: int,
    ) -> List[Dict[str, Any]]:
        if self._vector_store.dim <= 0 or self._vector_store.count() <= 0:
            return []

        contextual_query = build_contextual_query(query, project=filters.project, tags=filters.tags)
        query_vec = self._embedder.encode([contextual_query])[0]
        raw_limit = max(
            semantic_k,
            semantic_k * max(1, self._settings.retrieval.semantic_oversample_factor),
        )
        matches = self._vector_store.search(query_vec, raw_limit)
        rows_by_embedding_id = db.get_findings_by_embedding_ids(
            self._conn,
            [embedding_id for embedding_id, _ in matches],
        )

        items: List[Dict[str, Any]] = []
        for embedding_id, score in matches:
            row = rows_by_embedding_id.get(embedding_id)
            if row is None:
                continue
            if not _passes_filters(row, filters):
                continue
            item = _to_result(row, validity_days=self._settings.retrieval.validity_days)
            item["semantic_score"] = float(score)
            items.append(item)
            if len(items) >= semantic_k:
                break
        return items

    def _lexical_search(
        self,
        query: str,
        filters: RetrievalFilters,
        lexical_k: int,
    ) -> List[Dict[str, Any]]:
        rows = db.search_findings_filtered(
            self._conn,
            query=query,
            limit=lexical_k,
            project=filters.project,
            tags=filters.tags,
            created_after=filters.created_after,
            created_before=filters.created_before,
            confidence_min=filters.confidence_min,
        )

        items: List[Dict[str, Any]] = []
        for row in rows:
            item = _to_result(row, validity_days=self._settings.retrieval.validity_days)
            lexical_rank = float(row.get("lexical_rank", 0.0))
            item["lexical_score"] = -lexical_rank
            items.append(item)
        return items

    def _merge_results(
        self,
        semantic_items: List[Dict[str, Any]],
        lexical_items: List[Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        merged: Dict[str, Dict[str, Any]] = {}

        for item in semantic_items:
            merged[item["id"]] = item

        for item in lexical_items:
            existing = merged.get(item["id"])
            if existing is None:
                merged[item["id"]] = item
            else:
                existing["lexical_score"] = item.get("lexical_score")

        lexical_by_id: Dict[str, float] = {
            item_id: float(item.get("lexical_score", 0.0))
            for item_id, item in merged.items()
            if "lexical_score" in item
        }
        lexical_norm = _normalize_map(lexical_by_id)
        for item_id, score in lexical_norm.items():
            merged[item_id]["lexical_score"] = score

        for item in merged.values():
            semantic_score = float(item.get("semantic_score", 0.0))
            lexical_score = float(item.get("lexical_score", 0.0))
            # Use pre-parsed datetime to avoid re-parsing
            created_dt = item.get("_created_dt")
            recency_score = _recency_score_from_dt(created_dt)
            hit_count = 0
            if "semantic_score" in item:
                hit_count += 1
            if "lexical_score" in item:
                hit_count += 1
            final_score = (semantic_score * 0.55) + (lexical_score * 0.25) + (recency_score * 0.2)
            item["recency_score"] = recency_score
            item["final_score"] = final_score
            item["_sort"] = (hit_count, final_score)

        return merged


def _to_result(row: Dict[str, Any], validity_days: int = 90) -> Dict[str, Any]:
    created_at = row.get("created_at")
    created_dt = _parse_utc(created_at or "")
    stale, age_days = _staleness_from_dt(created_dt, validity_days=validity_days)
    return {
        "id": row.get("id"),
        "project": row.get("project"),
        "claim": row.get("claim"),
        "confidence": float(row.get("confidence") or 0.0),
        "created_at": created_at,
        "status": row.get("status"),
        "tags": row.get("tags", []),
        "evidence": row.get("evidence", []),
        "reasoning": row.get("reasoning", ""),
        "caveats": row.get("caveats", []),
        "pending_review": stale,
        "age_days": age_days,
        "_created_dt": created_dt,  # Internal: pass to downstream functions
    }


def _staleness_from_dt(created_dt: Optional[datetime], validity_days: int = 90) -> tuple[bool, int]:
    """Compute staleness from already-parsed datetime."""
    if created_dt is None:
        return (False, 0)
    age_days = int(max(0.0, (datetime.now(timezone.utc) - created_dt).total_seconds() / 86400.0))
    return (age_days >= validity_days, age_days)


def _recency_score_from_dt(created_dt: Optional[datetime]) -> float:
    """Compute recency score from already-parsed datetime."""
    if created_dt is None:
        return 0.0
    age_days = max(0.0, (datetime.now(timezone.utc) - created_dt).total_seconds() / 86400.0)
    return 1.0 / (1.0 + (age_days / 30.0))


def _parse_utc(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            return datetime.fromisoformat(value[:-1]).replace(tzinfo=timezone.utc)
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _recency_score(created_at: str) -> float:
    created = _parse_utc(created_at)
    if created is None:
        return 0.0
    age_days = max(0.0, (datetime.now(timezone.utc) - created).total_seconds() / 86400.0)
    return 1.0 / (1.0 + (age_days / 30.0))


def _passes_filters(row: Dict[str, Any], filters: RetrievalFilters) -> bool:
    if filters.project and row.get("project") != filters.project:
        return False

    if filters.confidence_min is not None:
        confidence = float(row.get("confidence") or 0.0)
        if confidence < float(filters.confidence_min):
            return False

    tags = row.get("tags") or []
    if filters.tags:
        required = set(filters.tags)
        if not required.issubset(set(tags)):
            return False

    created = _parse_utc(str(row.get("created_at") or ""))
    if filters.created_after:
        lower = _parse_utc(filters.created_after)
        if lower and (created is None or created < lower):
            return False

    if filters.created_before:
        upper = _parse_utc(filters.created_before)
        if upper and (created is None or created > upper):
            return False

    return True


def _staleness(created_at: Optional[str], validity_days: int = 90) -> tuple[bool, int]:
    created = _parse_utc(created_at or "")
    if created is None:
        return (False, 0)
    age_days = int(max(0.0, (datetime.now(timezone.utc) - created).total_seconds() / 86400.0))
    return (age_days >= validity_days, age_days)


_STOPWORDS_TRACE = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "to", "of", "in", "for", "on", "with",
    "at", "by", "from", "as", "and", "or", "but", "not", "no", "it",
    "its", "this", "that", "these", "those", "i", "me", "my", "we",
    "our", "you", "your", "he", "him", "his", "she", "her", "they",
    "them", "their",
}


def _tokenize_for_trace(text: str) -> List[str]:
    """Simple tokenizer for reasoning trace matching."""
    import re
    tokens = re.findall(r"[a-zA-Z0-9]+", text.lower())
    return [t for t in tokens if t not in _STOPWORDS_TRACE and len(t) > 2]


def _jaccard_similarity(tokens_a: set[str], tokens_b: set[str]) -> float:
    """Compute Jaccard similarity from pre-computed token sets."""
    if not tokens_a or not tokens_b:
        return 0.0

    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b

    return len(intersection) / len(union) if union else 0.0


def _claim_similarity(claim_a: str, claim_b: str) -> float:
    """Compute Jaccard similarity between two claims for deduplication."""
    tokens_a = set(_tokenize_for_trace(claim_a))
    tokens_b = set(_tokenize_for_trace(claim_b))
    return _jaccard_similarity(tokens_a, tokens_b)


def _normalize_map(values: Dict[str, float]) -> Dict[str, float]:
    """Min-max normalize keyed scores to [0, 1]."""
    if not values:
        return {}

    min_v = min(values.values())
    max_v = max(values.values())
    if max_v == min_v:
        return {key: 1.0 for key in values}

    scale = max_v - min_v
    return {key: (value - min_v) / scale for key, value in values.items()}
