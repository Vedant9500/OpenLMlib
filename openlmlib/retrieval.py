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
            item = _to_result(row)
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
            item = _to_result(row)
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

        for item in merged.values():
            semantic_score = float(item.get("semantic_score", 0.0))
            lexical_score = float(item.get("lexical_score", 0.0))
            recency_score = _recency_score(item.get("created_at", ""))
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


def _to_result(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row.get("id"),
        "project": row.get("project"),
        "claim": row.get("claim"),
        "confidence": float(row.get("confidence") or 0.0),
        "created_at": row.get("created_at"),
        "status": row.get("status"),
        "tags": row.get("tags", []),
        "evidence": row.get("evidence", []),
        "reasoning": row.get("reasoning", ""),
        "caveats": row.get("caveats", []),
    }


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
