"""Hypothesis packet schema for Co-Scientist runs.

Phase 1 uses JSON-serializable dataclasses and deterministic validation rather
than a database table. Packets can be saved directly as artifacts and later
indexed if cross-run querying becomes necessary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List
import re
import uuid

from openlmlib.schema import ValidationIssue


HYPOTHESIS_ID_RE = re.compile(r"^hyp_[a-f0-9]{12}$")
RUN_ID_RE = re.compile(r"^cosci_[a-f0-9]{12}$")

EVIDENCE_SUPPORTS = frozenset({"claim", "rationale", "assumption"})
HYPOTHESIS_STATUSES = frozenset({
    "draft",
    "ranked",
    "sent_to_verification",
    "verified",
    "rejected",
})

SCORE_FIELDS = (
    "novelty_score",
    "plausibility_score",
    "impact_score",
    "testability_score",
)


@dataclass(frozen=True)
class HypothesisEvidence:
    source: str
    summary: str
    supports: str
    confidence: float

    def to_dict(self) -> Dict[str, object]:
        return {
            "source": self.source,
            "summary": self.summary,
            "supports": self.supports,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class HypothesisLineage:
    parent_hypothesis_ids: List[str] = field(default_factory=list)
    version: int = 1
    generated_by: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "parent_hypothesis_ids": list(self.parent_hypothesis_ids),
            "version": self.version,
            "generated_by": self.generated_by,
        }


@dataclass(frozen=True)
class HypothesisPacket:
    hypothesis_id: str
    run_id: str
    title: str
    claim: str
    rationale: str
    assumptions: List[str]
    evidence: List[HypothesisEvidence]
    citations: List[str]
    novelty_score: float
    plausibility_score: float
    impact_score: float
    testability_score: float
    safety_notes: List[str]
    lineage: HypothesisLineage
    status: str = "draft"

    def to_dict(self) -> Dict[str, object]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "run_id": self.run_id,
            "title": self.title,
            "claim": self.claim,
            "rationale": self.rationale,
            "assumptions": list(self.assumptions),
            "evidence": [item.to_dict() for item in self.evidence],
            "citations": list(self.citations),
            "novelty_score": self.novelty_score,
            "plausibility_score": self.plausibility_score,
            "impact_score": self.impact_score,
            "testability_score": self.testability_score,
            "safety_notes": list(self.safety_notes),
            "lineage": self.lineage.to_dict(),
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "HypothesisPacket":
        issues = validate_hypothesis_packet(payload)
        if issues:
            message = "; ".join(f"{issue.field}: {issue.message}" for issue in issues)
            raise ValueError(message)

        lineage_payload = payload["lineage"]
        evidence_payload = payload["evidence"]
        return cls(
            hypothesis_id=str(payload["hypothesis_id"]).strip(),
            run_id=str(payload["run_id"]).strip(),
            title=str(payload["title"]).strip(),
            claim=str(payload["claim"]).strip(),
            rationale=str(payload["rationale"]).strip(),
            assumptions=[str(item).strip() for item in payload["assumptions"]],
            evidence=[
                HypothesisEvidence(
                    source=str(item["source"]).strip(),
                    summary=str(item["summary"]).strip(),
                    supports=str(item["supports"]).strip(),
                    confidence=float(item["confidence"]),
                )
                for item in evidence_payload
            ],
            citations=[str(item).strip() for item in payload["citations"]],
            novelty_score=float(payload["novelty_score"]),
            plausibility_score=float(payload["plausibility_score"]),
            impact_score=float(payload["impact_score"]),
            testability_score=float(payload["testability_score"]),
            safety_notes=[str(item).strip() for item in payload.get("safety_notes", [])],
            lineage=HypothesisLineage(
                parent_hypothesis_ids=[
                    str(item).strip()
                    for item in lineage_payload["parent_hypothesis_ids"]
                ],
                version=int(lineage_payload["version"]),
                generated_by=str(lineage_payload["generated_by"]).strip(),
            ),
            status=str(payload["status"]).strip(),
        )


def new_co_scientist_run_id() -> str:
    """Generate a stable Co-Scientist run ID."""
    return "cosci_" + uuid.uuid4().hex[:12]


def new_hypothesis_id() -> str:
    """Generate a stable hypothesis packet ID."""
    return "hyp_" + uuid.uuid4().hex[:12]


def get_hypothesis_packet_schema() -> Dict[str, object]:
    """Return a JSON-schema-like description of a hypothesis packet."""
    return {
        "type": "object",
        "required": [
            "hypothesis_id",
            "run_id",
            "title",
            "claim",
            "rationale",
            "assumptions",
            "evidence",
            "citations",
            *SCORE_FIELDS,
            "safety_notes",
            "lineage",
            "status",
        ],
        "id_formats": {
            "hypothesis_id": "hyp_<12 lowercase hex chars>",
            "run_id": "cosci_<12 lowercase hex chars>",
        },
        "enums": {
            "evidence.supports": sorted(EVIDENCE_SUPPORTS),
            "status": sorted(HYPOTHESIS_STATUSES),
        },
        "score_fields": {
            field: "number between 0.0 and 1.0"
            for field in SCORE_FIELDS
        },
        "lineage": {
            "parent_hypothesis_ids": "list of hyp_<12 lowercase hex chars>",
            "version": "integer >= 1",
            "generated_by": "non-empty agent/model identifier",
        },
    }


def validate_hypothesis_packet(payload: Any) -> List[ValidationIssue]:
    """Validate a hypothesis packet and return actionable issues."""
    issues: List[ValidationIssue] = []
    if not isinstance(payload, dict):
        return [
            ValidationIssue(
                field="packet",
                message="Hypothesis packet must be a JSON object",
            )
        ]

    required = get_hypothesis_packet_schema()["required"]
    for field_name in required:
        if field_name not in payload:
            issues.append(ValidationIssue(field=str(field_name), message="Field is required"))

    if issues:
        return issues

    _validate_id(payload.get("hypothesis_id"), "hypothesis_id", HYPOTHESIS_ID_RE, issues)
    _validate_id(payload.get("run_id"), "run_id", RUN_ID_RE, issues)

    for field_name in ("title", "claim", "rationale"):
        _validate_non_empty_string(payload.get(field_name), field_name, issues)

    _validate_string_list(payload.get("assumptions"), "assumptions", issues, min_items=1)
    _validate_string_list(payload.get("citations"), "citations", issues, min_items=1)
    _validate_string_list(payload.get("safety_notes"), "safety_notes", issues, min_items=0)

    _validate_evidence(payload.get("evidence"), issues)

    for field_name in SCORE_FIELDS:
        _validate_score(payload.get(field_name), field_name, issues)

    _validate_lineage(payload.get("lineage"), issues)

    status = payload.get("status")
    if status not in HYPOTHESIS_STATUSES:
        issues.append(
            ValidationIssue(
                field="status",
                message=f"Status must be one of: {sorted(HYPOTHESIS_STATUSES)}",
            )
        )

    return issues


def hypothesis_packet_is_valid(payload: Any) -> bool:
    return not validate_hypothesis_packet(payload)


def validation_issues_to_dicts(issues: Iterable[ValidationIssue]) -> List[Dict[str, str]]:
    return [
        {
            "field": issue.field,
            "message": issue.message,
            "severity": issue.severity,
        }
        for issue in issues
    ]


def _validate_id(
    value: Any,
    field_name: str,
    pattern: re.Pattern[str],
    issues: List[ValidationIssue],
) -> None:
    if not isinstance(value, str) or not pattern.match(value.strip()):
        issues.append(
            ValidationIssue(
                field=field_name,
                message=f"{field_name} has invalid format",
            )
        )


def _validate_non_empty_string(
    value: Any,
    field_name: str,
    issues: List[ValidationIssue],
) -> None:
    if not isinstance(value, str) or not value.strip():
        issues.append(
            ValidationIssue(
                field=field_name,
                message="Must be a non-empty string",
            )
        )


def _validate_string_list(
    value: Any,
    field_name: str,
    issues: List[ValidationIssue],
    min_items: int,
) -> None:
    if not isinstance(value, list):
        issues.append(ValidationIssue(field=field_name, message="Must be a list"))
        return
    if len(value) < min_items:
        issues.append(
            ValidationIssue(
                field=field_name,
                message=f"Must contain at least {min_items} item(s)",
            )
        )
    for idx, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            issues.append(
                ValidationIssue(
                    field=f"{field_name}[{idx}]",
                    message="Must be a non-empty string",
                )
            )


def _validate_score(value: Any, field_name: str, issues: List[ValidationIssue]) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        issues.append(ValidationIssue(field=field_name, message="Must be a number"))
        return
    if not 0.0 <= float(value) <= 1.0:
        issues.append(
            ValidationIssue(
                field=field_name,
                message="Must be between 0.0 and 1.0",
            )
        )


def _validate_evidence(value: Any, issues: List[ValidationIssue]) -> None:
    if not isinstance(value, list):
        issues.append(ValidationIssue(field="evidence", message="Must be a list"))
        return
    if not value:
        issues.append(
            ValidationIssue(
                field="evidence",
                message="Must contain at least one evidence item",
            )
        )
        return

    for idx, item in enumerate(value):
        field_prefix = f"evidence[{idx}]"
        if not isinstance(item, dict):
            issues.append(ValidationIssue(field=field_prefix, message="Must be an object"))
            continue
        for key in ("source", "summary"):
            _validate_non_empty_string(item.get(key), f"{field_prefix}.{key}", issues)
        supports = item.get("supports")
        if supports not in EVIDENCE_SUPPORTS:
            issues.append(
                ValidationIssue(
                    field=f"{field_prefix}.supports",
                    message=f"Must be one of: {sorted(EVIDENCE_SUPPORTS)}",
                )
            )
        _validate_score(item.get("confidence"), f"{field_prefix}.confidence", issues)


def _validate_lineage(value: Any, issues: List[ValidationIssue]) -> None:
    if not isinstance(value, dict):
        issues.append(ValidationIssue(field="lineage", message="Must be an object"))
        return

    parents = value.get("parent_hypothesis_ids")
    if not isinstance(parents, list):
        issues.append(
            ValidationIssue(
                field="lineage.parent_hypothesis_ids",
                message="Must be a list",
            )
        )
    else:
        for idx, parent_id in enumerate(parents):
            if not isinstance(parent_id, str) or not HYPOTHESIS_ID_RE.match(parent_id.strip()):
                issues.append(
                    ValidationIssue(
                        field=f"lineage.parent_hypothesis_ids[{idx}]",
                        message="Parent hypothesis ID has invalid format",
                    )
                )

    version = value.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        issues.append(
            ValidationIssue(
                field="lineage.version",
                message="Must be an integer >= 1",
            )
        )

    _validate_non_empty_string(value.get("generated_by"), "lineage.generated_by", issues)
