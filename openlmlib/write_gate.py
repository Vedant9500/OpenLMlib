from __future__ import annotations

from typing import Iterable, List, Optional
import math

from .schema import ValidationIssue


def _cosine_similarity(vec_a: Iterable[float], vec_b: Iterable[float]) -> float:
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for a, b in zip(vec_a, vec_b):
        dot += a * b
        norm_a += a * a
        norm_b += b * b
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / math.sqrt(norm_a * norm_b)


class WriteGate:
    def __init__(
        self,
        min_confidence: float,
        min_reasoning_length: int,
        min_claim_evidence_sim: float,
        novelty_similarity_threshold: float,
        novelty_top_k: int,
        embedder=None,
        vector_store=None,
    ) -> None:
        self.min_confidence = min_confidence
        self.min_reasoning_length = min_reasoning_length
        self.min_claim_evidence_sim = min_claim_evidence_sim
        self.novelty_similarity_threshold = novelty_similarity_threshold
        self.novelty_top_k = novelty_top_k
        self.embedder = embedder
        self.vector_store = vector_store

    def validate(
        self,
        claim: str,
        evidence: List[str],
        reasoning: str,
        confidence: float,
    ) -> List[ValidationIssue]:
        issues: List[ValidationIssue] = []

        if confidence < self.min_confidence:
            issues.append(
                ValidationIssue(
                    field="confidence",
                    message=f"Confidence must be >= {self.min_confidence}",
                )
            )

        if len(reasoning.strip()) < self.min_reasoning_length:
            issues.append(
                ValidationIssue(
                    field="reasoning",
                    message=f"Reasoning must be at least {self.min_reasoning_length} characters",
                )
            )

        if not evidence:
            issues.append(
                ValidationIssue(
                    field="evidence",
                    message="Evidence is required",
                )
            )

        if self.embedder is None:
            issues.append(
                ValidationIssue(
                    field="embedding",
                    message="Embedding model not available; similarity checks skipped",
                    severity="warning",
                )
            )
            return issues

        claim_vec = self.embedder.encode([claim])[0]
        evidence_text = " ".join(evidence)
        evidence_vec = self.embedder.encode([evidence_text])[0]
        similarity = _cosine_similarity(claim_vec, evidence_vec)

        if similarity < self.min_claim_evidence_sim:
            issues.append(
                ValidationIssue(
                    field="evidence",
                    message=f"Claim/evidence similarity {similarity:.2f} below threshold {self.min_claim_evidence_sim}",
                )
            )

        if self.vector_store is not None:
            if getattr(self.vector_store, "count", lambda: 0)() > 0 and self.vector_store.dim > 0:
                matches = self.vector_store.search(claim_vec, self.novelty_top_k)
                if matches:
                    best_id, best_score = matches[0]
                    if best_score >= self.novelty_similarity_threshold:
                        issues.append(
                            ValidationIssue(
                                field="novelty",
                                message=f"Similar finding detected (id={best_id}, score={best_score:.2f})",
                                severity="warning",
                            )
                        )

        return issues

    @staticmethod
    def is_allowed(issues: List[ValidationIssue]) -> bool:
        return all(issue.severity != "error" for issue in issues)
