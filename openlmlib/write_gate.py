from __future__ import annotations

from typing import Callable, Dict, Iterable, List, Optional
import math
import re

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
        contradiction_similarity_threshold: Optional[float] = None,
        embedder=None,
        vector_store=None,
        finding_lookup: Optional[Callable[[int], Optional[Dict[str, str]]]] = None,
    ) -> None:
        self.min_confidence = min_confidence
        self.min_reasoning_length = min_reasoning_length
        self.min_claim_evidence_sim = min_claim_evidence_sim
        self.novelty_similarity_threshold = novelty_similarity_threshold
        self.contradiction_similarity_threshold = (
            0.8
            if contradiction_similarity_threshold is None
            else contradiction_similarity_threshold
        )
        self.novelty_top_k = novelty_top_k
        self.embedder = embedder
        self.vector_store = vector_store
        self.finding_lookup = finding_lookup

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

                if self.finding_lookup is not None:
                    for match_id, match_score in matches:
                        if match_score < self.contradiction_similarity_threshold:
                            continue
                        existing = self.finding_lookup(int(match_id))
                        if not existing:
                            continue
                        existing_claim = str(existing.get("claim") or "")
                        if _claims_contradict(claim, existing_claim):
                            issues.append(
                                ValidationIssue(
                                    field="contradiction",
                                    message=(
                                        "Potential contradiction with existing finding "
                                        f"(id={existing.get('id')}, score={match_score:.2f})"
                                    ),
                                    severity="warning",
                                )
                            )
                            break

        return issues

    def adjust_confidence(
        self,
        claim: str,
        evidence: List[str],
        proposed_confidence: float,
        issues: Optional[List[ValidationIssue]] = None,
    ) -> float:
        adjusted = float(proposed_confidence)
        if self.embedder is not None and evidence:
            claim_vec = self.embedder.encode([claim])[0]
            evidence_vec = self.embedder.encode([" ".join(evidence)])[0]
            sim = _cosine_similarity(claim_vec, evidence_vec)
            adjusted = (0.7 * adjusted) + (0.3 * sim)

        for issue in issues or []:
            if issue.severity != "warning":
                continue
            if issue.field == "contradiction":
                adjusted -= 0.1
            elif issue.field == "novelty":
                adjusted -= 0.05

        adjusted = max(0.0, min(1.0, adjusted))
        return float(round(float(adjusted), 3))

    @staticmethod
    def is_allowed(issues: List[ValidationIssue]) -> bool:
        return all(issue.severity != "error" for issue in issues)


_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "is", "it", "of", "on", "or", "that", "the", "to", "with",
}
_NEGATION_TERMS = {"not", "no", "never", "without", "cannot", "can't", "fails", "failed", "avoid"}


def _tokenize(text: str) -> List[str]:
    return [token for token in re.findall(r"[a-z0-9']+", text.lower()) if token not in _STOPWORDS]


def _has_negation(tokens: List[str]) -> bool:
    return any(token in _NEGATION_TERMS for token in tokens)


def _claims_contradict(candidate: str, existing: str) -> bool:
    candidate_tokens = _tokenize(candidate)
    existing_tokens = _tokenize(existing)
    if not candidate_tokens or not existing_tokens:
        return False

    shared = set(candidate_tokens).intersection(existing_tokens)
    if len(shared) < 3:
        return False

    return _has_negation(candidate_tokens) != _has_negation(existing_tokens)
