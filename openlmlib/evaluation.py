from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence

from .write_gate import _cosine_similarity


@dataclass
class RetrievalMetrics:
	precision_at_k: Dict[int, float]
	recall_at_k: Dict[int, float]

	def to_dict(self) -> Dict[str, Dict[str, float]]:
		return {
			"precision_at_k": {str(k): v for k, v in self.precision_at_k.items()},
			"recall_at_k": {str(k): v for k, v in self.recall_at_k.items()},
		}


def evaluate_retrieval(
	expected_ids: Sequence[str],
	retrieved_ids: Sequence[str],
	k_values: Sequence[int] = (5, 10),
) -> RetrievalMetrics:
	expected_set = set(expected_ids)
	precision: Dict[int, float] = {}
	recall: Dict[int, float] = {}

	for k in k_values:
		top_k = list(retrieved_ids[:k])
		hits = len([finding_id for finding_id in top_k if finding_id in expected_set])
		precision[k] = (hits / max(1, len(top_k)))
		recall[k] = (hits / max(1, len(expected_set)))

	return RetrievalMetrics(precision_at_k=precision, recall_at_k=recall)


def faithfulness_score(answer: str, retrieved_items: Iterable[Dict]) -> float:
	answer_lower = answer.lower()
	if not answer_lower.strip():
		return 0.0

	checks = 0
	supported = 0
	for item in retrieved_items:
		claim = str(item.get("claim") or "").strip().lower()
		evidence = [str(v).strip().lower() for v in (item.get("evidence") or []) if str(v).strip()]
		for snippet in [claim] + evidence:
			if not snippet:
				continue
			checks += 1
			if snippet in answer_lower:
				supported += 1

	if checks == 0:
		return 0.0
	return supported / checks


def relevance_alignment(
	query: str,
	retrieved_items: Iterable[Dict],
	embedder,
) -> float:
	items = list(retrieved_items)
	if not query.strip() or not items:
		return 0.0

	query_vec = embedder.encode([query])[0]
	sims: List[float] = []
	for item in items:
		text = " ".join(
			[
				str(item.get("claim") or ""),
				str(item.get("reasoning") or ""),
				" ".join([str(v) for v in (item.get("evidence") or [])]),
			]
		).strip()
		if not text:
			continue
		item_vec = embedder.encode([text])[0]
		sims.append(float(_cosine_similarity(query_vec, item_vec)))

	if not sims:
		return 0.0
	return sum(sims) / len(sims)
