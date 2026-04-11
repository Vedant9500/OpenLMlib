from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List
import datetime
import hashlib
import json
import uuid


@dataclass
class PaperContext:
    """Lightweight reference to source paper and what else it covers."""
    title: str = ""
    url: str = ""
    also_covers: List[str] = field(default_factory=list)


@dataclass
class FindingText:
    tags: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    caveats: List[str] = field(default_factory=list)
    reasoning: str = ""
    # Domain/field for high-level categorization (e.g., "LLM", "Symbolic Regression")
    domain: str = ""
    # Source paper context (what else the paper mentions beyond this finding)
    paper: PaperContext = field(default_factory=PaperContext)
    # Related papers worth noting
    related_papers: List[Dict[str, str]] = field(default_factory=list)  # [{title, url}]


@dataclass
class FindingAudit:
    proposed_by: str = ""
    evidence_provided: bool = False
    reasoning_length: int = 0
    failure_log: List[Dict[str, Any]] = field(default_factory=list)
    confidence_history: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class Finding:
    id: str
    project: str
    claim: str
    confidence: float
    created_at: str
    embedding_id: int
    content_hash: str
    status: str
    text: FindingText
    audit: FindingAudit
    full_text: str = ""

    def to_content_dict(self, include_hash: bool = True) -> Dict[str, Any]:
        data = {
            "id": self.id,
            "project": self.project,
            "claim": self.claim,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "embedding_id": self.embedding_id,
            "status": self.status,
            "domain": self.text.domain,
            "tags": self.text.tags,
            "evidence": self.text.evidence,
            "reasoning": self.text.reasoning,
            "caveats": self.text.caveats,
            "paper": {
                "title": self.text.paper.title,
                "url": self.text.paper.url,
                "also_covers": self.text.paper.also_covers,
            } if self.text.paper.title or self.text.paper.url or self.text.paper.also_covers else None,
            "related_papers": self.text.related_papers,
            "full_text": self.full_text,
            "audit": {
                "proposed_by": self.audit.proposed_by,
                "evidence_provided": self.audit.evidence_provided,
                "reasoning_length": self.audit.reasoning_length,
                "failure_log": self.audit.failure_log,
                "confidence_history": self.audit.confidence_history,
            },
        }
        if include_hash:
            data["content_hash"] = self.content_hash
        return data


@dataclass
class ValidationIssue:
    field: str
    message: str
    severity: str = "error"


def utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_finding_id() -> str:
    return "fnd-" + uuid.uuid4().hex[:12]


def compute_content_hash(data: Dict[str, Any]) -> str:
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def make_embedding_id(finding_id: str) -> int:
    digest = hashlib.sha256(finding_id.encode("utf-8")).digest()
    raw = int.from_bytes(digest[:8], "big")
    return raw & 0x7FFFFFFFFFFFFFFF
