"""Deterministic ranking, proximity, and evolution helpers for Co-Scientist."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
import re

from openlmlib.schema import ValidationIssue

from .evidence import evidence_quality_score
from .hypothesis import (
    HYPOTHESIS_ID_RE,
    SCORE_FIELDS,
    new_hypothesis_id,
    validate_hypothesis_packet,
)


SCORING_AXES = (
    "novelty",
    "plausibility",
    "evidence_quality",
    "impact",
    "testability",
    "project_fit",
    "safety",
)

DEFAULT_AXIS_WEIGHTS = {
    "novelty": 0.15,
    "plausibility": 0.15,
    "evidence_quality": 0.15,
    "impact": 0.15,
    "testability": 0.15,
    "project_fit": 0.15,
    "safety": 0.10,
}

COMPARISON_WINNERS = frozenset({"hypothesis_a", "hypothesis_b", "tie"})

EVOLVABLE_FIELDS = frozenset({
    "title",
    "claim",
    "rationale",
    "assumptions",
    "evidence",
    "citations",
    "novelty_score",
    "plausibility_score",
    "impact_score",
    "testability_score",
    "safety_notes",
    "status",
})

_TOKEN_RE = re.compile(r"[a-z0-9_]+")
_STOPWORDS = frozenset({
    "a",
    "an",
    "and",
    "are",
    "as",
    "be",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "with",
})


class RankingInputError(ValueError):
    """Raised when ranking or evolution input is invalid."""

    def __init__(self, message: str, issues: Sequence[ValidationIssue]):
        super().__init__(message)
        self.issues = list(issues)


@dataclass(frozen=True)
class PairwiseComparison:
    hypothesis_a: str
    hypothesis_b: str
    winner: str
    criteria: List[str]
    rationale: str
    judge_agent: str
    confidence: float

    def to_dict(self) -> Dict[str, object]:
        return {
            "hypothesis_a": self.hypothesis_a,
            "hypothesis_b": self.hypothesis_b,
            "winner": self.winner,
            "criteria": list(self.criteria),
            "rationale": self.rationale,
            "judge_agent": self.judge_agent,
            "confidence": self.confidence,
        }


def validate_pairwise_comparison(payload: Any) -> List[ValidationIssue]:
    """Validate a pairwise comparison record."""
    issues: List[ValidationIssue] = []
    if not isinstance(payload, dict):
        return [ValidationIssue("comparison", "Must be an object")]

    for field in ("hypothesis_a", "hypothesis_b", "winner", "criteria", "rationale", "judge_agent", "confidence"):
        if field not in payload:
            issues.append(ValidationIssue(field, "Field is required"))
    if issues:
        return issues

    for field in ("hypothesis_a", "hypothesis_b"):
        value = payload.get(field)
        if not isinstance(value, str) or not HYPOTHESIS_ID_RE.match(value.strip()):
            issues.append(ValidationIssue(field, "Must be a valid hyp_<12 lowercase hex chars> ID"))
    if payload.get("hypothesis_a") == payload.get("hypothesis_b"):
        issues.append(ValidationIssue("hypothesis_b", "Must compare two different hypotheses"))

    winner = payload.get("winner")
    if winner not in COMPARISON_WINNERS:
        issues.append(ValidationIssue("winner", f"Must be one of: {sorted(COMPARISON_WINNERS)}"))

    _validate_non_empty_string_list(payload.get("criteria"), "criteria", issues)
    for field in ("rationale", "judge_agent"):
        if not isinstance(payload.get(field), str) or not payload.get(field, "").strip():
            issues.append(ValidationIssue(field, "Must be a non-empty string"))

    confidence = payload.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        issues.append(ValidationIssue("confidence", "Must be a number"))
    elif not 0.0 <= float(confidence) <= 1.0:
        issues.append(ValidationIssue("confidence", "Must be between 0.0 and 1.0"))

    return issues


def score_hypothesis(packet: Dict[str, Any], axis_weights: Optional[Dict[str, float]] = None) -> Dict[str, object]:
    """Score one hypothesis across the Phase 5 axes."""
    _ensure_valid_packet(packet)
    weights = _normalize_weights(axis_weights)
    axes = {
        "novelty": float(packet["novelty_score"]),
        "plausibility": float(packet["plausibility_score"]),
        "evidence_quality": _evidence_quality(packet),
        "impact": float(packet["impact_score"]),
        "testability": float(packet["testability_score"]),
        "project_fit": _optional_score(packet, "project_fit_score", default=0.5),
        "safety": _optional_score(packet, "safety_score", default=_safety_score(packet)),
    }
    base_score = round(sum(axes[axis] * weights[axis] for axis in SCORING_AXES), 6)
    return {"hypothesis_id": packet["hypothesis_id"], "axes": axes, "base_score": base_score}


def rank_hypotheses(
    hypothesis_packets: Sequence[Dict[str, Any]],
    pairwise_comparisons: Optional[Sequence[Dict[str, Any]]] = None,
    axis_weights: Optional[Dict[str, float]] = None,
) -> Dict[str, object]:
    """Return a deterministic ranking from packet scores and optional comparisons."""
    if not hypothesis_packets:
        raise RankingInputError("At least one hypothesis packet is required", [ValidationIssue("hypotheses", "Must not be empty")])

    packets_by_id: Dict[str, Dict[str, Any]] = {}
    issues: List[ValidationIssue] = []
    for idx, packet in enumerate(hypothesis_packets):
        packet_issues = validate_hypothesis_packet(packet)
        if packet_issues:
            issues.extend(ValidationIssue(f"hypotheses[{idx}].{issue.field}", issue.message, issue.severity) for issue in packet_issues)
            continue
        hypothesis_id = packet["hypothesis_id"]
        if hypothesis_id in packets_by_id:
            issues.append(ValidationIssue(f"hypotheses[{idx}].hypothesis_id", "Duplicate hypothesis ID"))
        packets_by_id[hypothesis_id] = packet
    if issues:
        raise RankingInputError("Invalid hypothesis ranking input", issues)

    comparison_stats = {
        hypothesis_id: {"wins": 0, "losses": 0, "ties": 0, "appearances": 0, "points": 0.0}
        for hypothesis_id in packets_by_id
    }
    valid_comparisons = _validated_comparisons(pairwise_comparisons or [], set(packets_by_id))
    for comparison in valid_comparisons:
        _apply_comparison(comparison, comparison_stats)

    rows = []
    for hypothesis_id, packet in packets_by_id.items():
        scored = score_hypothesis(packet, axis_weights)
        stats = comparison_stats[hypothesis_id]
        comparison_score = _comparison_score(stats)
        final_score = (
            float(scored["base_score"])
            if stats["appearances"] == 0
            else round(float(scored["base_score"]) * 0.75 + comparison_score * 0.25, 6)
        )
        rows.append({
            "hypothesis_id": hypothesis_id,
            "title": packet["title"],
            "status": packet["status"],
            "axes": scored["axes"],
            "base_score": scored["base_score"],
            "comparison_score": comparison_score if stats["appearances"] else None,
            "final_score": final_score,
            "wins": stats["wins"],
            "losses": stats["losses"],
            "ties": stats["ties"],
            "comparison_appearances": stats["appearances"],
        })

    rows.sort(key=lambda item: (-float(item["final_score"]), -float(item["base_score"]), item["hypothesis_id"]))
    for idx, row in enumerate(rows, start=1):
        row["rank"] = idx

    return {
        "rankings": rows,
        "hypothesis_count": len(rows),
        "comparison_count": len(valid_comparisons),
        "scoring_axes": list(SCORING_AXES),
        "axis_weights": _normalize_weights(axis_weights),
    }


def cluster_similar_hypotheses(
    hypothesis_packets: Sequence[Dict[str, Any]],
    threshold: float = 0.55,
) -> Dict[str, object]:
    """Flag similar hypotheses using deterministic token Jaccard similarity."""
    if not 0.0 <= threshold <= 1.0:
        raise RankingInputError("threshold must be between 0.0 and 1.0", [ValidationIssue("threshold", "Must be between 0.0 and 1.0")])
    for packet in hypothesis_packets:
        _ensure_valid_packet(packet)

    tokens_by_id = {packet["hypothesis_id"]: _packet_tokens(packet) for packet in hypothesis_packets}
    parent = {hypothesis_id: hypothesis_id for hypothesis_id in tokens_by_id}
    edges = []
    ids = sorted(tokens_by_id)
    for i, left in enumerate(ids):
        for right in ids[i + 1:]:
            similarity = _jaccard(tokens_by_id[left], tokens_by_id[right])
            if similarity >= threshold:
                _union(parent, left, right)
                edges.append({
                    "hypothesis_a": left,
                    "hypothesis_b": right,
                    "similarity": round(similarity, 6),
                })

    grouped: Dict[str, List[str]] = {}
    for hypothesis_id in ids:
        grouped.setdefault(_find(parent, hypothesis_id), []).append(hypothesis_id)

    clusters = [
        {
            "cluster_id": f"cluster_{idx}",
            "hypothesis_ids": members,
            "size": len(members),
        }
        for idx, members in enumerate(
            sorted(grouped.values(), key=lambda members: (-len(members), members[0])),
            start=1,
        )
    ]
    return {
        "threshold": threshold,
        "clusters": clusters,
        "near_duplicates": sorted(edges, key=lambda item: (-item["similarity"], item["hypothesis_a"], item["hypothesis_b"])),
    }


def evolve_hypothesis_packet(
    parent_packet: Dict[str, Any],
    updates: Dict[str, Any],
    generated_by: Optional[str] = None,
    hypothesis_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new hypothesis packet version while preserving lineage."""
    _ensure_valid_packet(parent_packet)
    if not isinstance(updates, dict):
        raise RankingInputError("updates must be an object", [ValidationIssue("updates", "Must be an object")])

    evolved = {key: _copy_jsonish(value) for key, value in parent_packet.items()}
    for key, value in updates.items():
        if key in EVOLVABLE_FIELDS:
            evolved[key] = _copy_jsonish(value)
    evolved["hypothesis_id"] = hypothesis_id or new_hypothesis_id()
    evolved["run_id"] = parent_packet["run_id"]

    parent_lineage = parent_packet.get("lineage", {})
    parent_ids = list(parent_lineage.get("parent_hypothesis_ids", []))
    parent_ids.append(parent_packet["hypothesis_id"])
    evolved["lineage"] = {
        "parent_hypothesis_ids": _dedupe(parent_ids),
        "version": int(parent_lineage.get("version", 1)) + 1,
        "generated_by": generated_by or updates.get("generated_by") or parent_lineage.get("generated_by", ""),
    }

    issues = validate_hypothesis_packet(evolved)
    if issues:
        raise RankingInputError("Evolved hypothesis packet is invalid", issues)
    return evolved


def _ensure_valid_packet(packet: Dict[str, Any]) -> None:
    issues = validate_hypothesis_packet(packet)
    if issues:
        raise RankingInputError("Invalid hypothesis packet", issues)


def _validated_comparisons(comparisons: Sequence[Dict[str, Any]], valid_ids: set[str]) -> List[PairwiseComparison]:
    parsed: List[PairwiseComparison] = []
    issues: List[ValidationIssue] = []
    for idx, comparison in enumerate(comparisons):
        comparison_issues = validate_pairwise_comparison(comparison)
        if comparison_issues:
            issues.extend(ValidationIssue(f"comparisons[{idx}].{issue.field}", issue.message, issue.severity) for issue in comparison_issues)
            continue
        missing = [
            field
            for field in ("hypothesis_a", "hypothesis_b")
            if comparison[field] not in valid_ids
        ]
        for field in missing:
            issues.append(ValidationIssue(f"comparisons[{idx}].{field}", "Hypothesis ID is not in the ranking input"))
        if missing:
            continue
        parsed.append(PairwiseComparison(
            hypothesis_a=comparison["hypothesis_a"],
            hypothesis_b=comparison["hypothesis_b"],
            winner=comparison["winner"],
            criteria=list(comparison["criteria"]),
            rationale=comparison["rationale"],
            judge_agent=comparison["judge_agent"],
            confidence=float(comparison["confidence"]),
        ))
    if issues:
        raise RankingInputError("Invalid pairwise comparison input", issues)
    return parsed


def _apply_comparison(comparison: PairwiseComparison, stats: Dict[str, Dict[str, float]]) -> None:
    left = stats[comparison.hypothesis_a]
    right = stats[comparison.hypothesis_b]
    left["appearances"] += 1
    right["appearances"] += 1
    if comparison.winner == "tie":
        left["ties"] += 1
        right["ties"] += 1
        left["points"] += comparison.confidence * 0.25
        right["points"] += comparison.confidence * 0.25
        return
    winner_id = comparison.hypothesis_a if comparison.winner == "hypothesis_a" else comparison.hypothesis_b
    loser_id = comparison.hypothesis_b if winner_id == comparison.hypothesis_a else comparison.hypothesis_a
    stats[winner_id]["wins"] += 1
    stats[loser_id]["losses"] += 1
    stats[winner_id]["points"] += comparison.confidence
    stats[loser_id]["points"] -= comparison.confidence * 0.25


def _comparison_score(stats: Dict[str, float]) -> float:
    appearances = int(stats["appearances"])
    if appearances == 0:
        return 0.5
    raw = 0.5 + float(stats["points"]) / (2.0 * appearances)
    return round(max(0.0, min(1.0, raw)), 6)


def _normalize_weights(axis_weights: Optional[Dict[str, float]]) -> Dict[str, float]:
    raw = dict(DEFAULT_AXIS_WEIGHTS)
    if axis_weights:
        for axis, value in axis_weights.items():
            if axis in SCORING_AXES and isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
                raw[axis] = float(value)
    total = sum(raw.values())
    return {axis: raw[axis] / total for axis in SCORING_AXES}


def _evidence_quality(packet: Dict[str, Any]) -> float:
    evidence = packet.get("evidence") or []
    if not evidence:
        return 0.0
    return sum(evidence_quality_score(item) for item in evidence) / len(evidence)


def _optional_score(packet: Dict[str, Any], field: str, default: float) -> float:
    value = packet.get(field, default)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return default
    return max(0.0, min(1.0, float(value)))


def _safety_score(packet: Dict[str, Any]) -> float:
    notes = " ".join(str(item).lower() for item in packet.get("safety_notes", []))
    if any(term in notes for term in ("unsafe", "out of scope", "blocked")):
        return 0.2
    if any(term in notes for term in ("approval", "risk", "caution")):
        return 0.6
    return 1.0


def _validate_non_empty_string_list(value: Any, field: str, issues: List[ValidationIssue]) -> None:
    if not isinstance(value, list) or not value:
        issues.append(ValidationIssue(field, "Must be a non-empty list"))
        return
    for idx, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            issues.append(ValidationIssue(f"{field}[{idx}]", "Must be a non-empty string"))


def _packet_tokens(packet: Dict[str, Any]) -> set[str]:
    parts: List[str] = [
        packet.get("title", ""),
        packet.get("claim", ""),
        packet.get("rationale", ""),
    ]
    parts.extend(str(item) for item in packet.get("assumptions", []))
    text = " ".join(parts).lower()
    return {token for token in _TOKEN_RE.findall(text) if token not in _STOPWORDS and len(token) > 2}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _find(parent: Dict[str, str], item: str) -> str:
    while parent[item] != item:
        parent[item] = parent[parent[item]]
        item = parent[item]
    return item


def _union(parent: Dict[str, str], left: str, right: str) -> None:
    root_left = _find(parent, left)
    root_right = _find(parent, right)
    if root_left != root_right:
        parent[max(root_left, root_right)] = min(root_left, root_right)


def _dedupe(items: Iterable[str]) -> List[str]:
    result: List[str] = []
    seen = set()
    for item in items:
        if item not in seen:
            result.append(item)
            seen.add(item)
    return result


def _copy_jsonish(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _copy_jsonish(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy_jsonish(item) for item in value]
    return value
