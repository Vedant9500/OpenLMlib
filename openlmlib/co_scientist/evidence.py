"""Evidence grounding and citation verification for Co-Scientist packets."""

from __future__ import annotations

import os
import socket
import sqlite3
import ssl
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from openlmlib.schema import ValidationIssue

# Opt-in network reachability for http(s) citations (off by default for offline/tests).
_CHECK_URL_ENV = "OPENLMLIB_CHECK_CITATION_URLS"
_URL_TIMEOUT_SEC = 3.0


EVIDENCE_LABELS = frozenset({"support", "refute", "neutral"})

EVIDENCE_QUALITY_RUBRIC: Dict[str, Dict[str, object]] = {
    "primary_source": {
        "score": 1.0,
        "description": "Primary source, official documentation, or directly authored source.",
    },
    "peer_reviewed": {
        "score": 0.9,
        "description": "Peer-reviewed paper or accepted academic preprint.",
    },
    "reproducible": {
        "score": 0.85,
        "description": "Reproducible code, benchmark, test result, or executable fixture.",
    },
    "secondary_analysis": {
        "score": 0.65,
        "description": "Secondary analysis, review, or non-primary technical summary.",
    },
    "anecdotal": {
        "score": 0.3,
        "description": "Anecdotal, low-confidence, or weakly sourced evidence.",
    },
}

EVIDENCE_QUALITY_LEVELS = frozenset(EVIDENCE_QUALITY_RUBRIC)


def get_evidence_quality_rubric() -> Dict[str, object]:
    """Return the deterministic Phase 6 evidence labels and quality rubric."""
    return {
        "labels": sorted(EVIDENCE_LABELS),
        "quality_levels": deepcopy_evidence_rubric(),
    }


def validate_evidence_items(
    evidence: Any,
    *,
    require_label: bool = True,
    require_quality: bool = False,
    field_name: str = "evidence",
) -> List[ValidationIssue]:
    """Validate Phase 6 evidence labels and optional quality levels."""
    issues: List[ValidationIssue] = []
    if not isinstance(evidence, list) or not evidence:
        return [ValidationIssue(field_name, "Must be a non-empty evidence list")]

    for idx, item in enumerate(evidence):
        prefix = f"{field_name}[{idx}]"
        if not isinstance(item, dict):
            issues.append(ValidationIssue(prefix, "Must be an object"))
            continue

        label = item.get("label")
        if label is None:
            if require_label:
                issues.append(ValidationIssue(f"{prefix}.label", "Evidence label is required"))
        elif label not in EVIDENCE_LABELS:
            issues.append(
                ValidationIssue(
                    f"{prefix}.label",
                    f"Evidence label must be one of: {sorted(EVIDENCE_LABELS)}",
                )
            )

        quality = item.get("quality")
        if quality is None:
            if require_quality:
                issues.append(ValidationIssue(f"{prefix}.quality", "Evidence quality is required"))
        elif quality not in EVIDENCE_QUALITY_LEVELS:
            issues.append(
                ValidationIssue(
                    f"{prefix}.quality",
                    f"Evidence quality must be one of: {sorted(EVIDENCE_QUALITY_LEVELS)}",
                )
            )

    return issues


def evidence_quality_score(evidence_item: Dict[str, Any]) -> float:
    """Return rubric score for an evidence item, falling back to confidence."""
    quality = evidence_item.get("quality")
    if quality in EVIDENCE_QUALITY_RUBRIC:
        return float(EVIDENCE_QUALITY_RUBRIC[quality]["score"])
    confidence = evidence_item.get("confidence", 0.0)
    if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
        return max(0.0, min(1.0, float(confidence)))
    return 0.0


def verify_citations(
    citations: Any,
    *,
    conn: Optional[sqlite3.Connection] = None,
    session_ids: Optional[Sequence[str]] = None,
    workspace_root: Optional[Path] = None,
    check_url_reachability: Optional[bool] = None,
) -> Dict[str, object]:
    """Verify that citations refer to a URL, local file, or known artifact.

    External URLs require valid syntax. When check_url_reachability is true
    (or OPENLMLIB_CHECK_CITATION_URLS=1), a short HEAD/GET probe is performed.
    Local paths and artifact IDs are checked against the filesystem/database.
    """
    issues: List[ValidationIssue] = []
    results: List[Dict[str, object]] = []
    if not isinstance(citations, list) or not citations:
        return {
            "valid": False,
            "citations": [],
            "issues": _issues_to_dicts([ValidationIssue("citations", "Must be a non-empty citation list")]),
        }

    for idx, citation in enumerate(citations):
        field = f"citations[{idx}]"
        if not isinstance(citation, str) or not citation.strip():
            issues.append(ValidationIssue(field, "Citation must be a non-empty string"))
            continue
        result = resolve_citation(
            citation.strip(),
            conn=conn,
            session_ids=session_ids,
            workspace_root=workspace_root,
            check_url_reachability=check_url_reachability,
        )
        results.append(result)
        if not result["resolved"]:
            detail = result.get("detail") or f"Citation could not be resolved: {citation.strip()}"
            issues.append(ValidationIssue(field, str(detail)))

    return {
        "valid": not issues,
        "citations": results,
        "issues": _issues_to_dicts(issues),
    }


def resolve_citation(
    citation: str,
    *,
    conn: Optional[sqlite3.Connection] = None,
    session_ids: Optional[Sequence[str]] = None,
    workspace_root: Optional[Path] = None,
    check_url_reachability: Optional[bool] = None,
) -> Dict[str, object]:
    """Resolve one citation to a URL, local file, or artifact record."""
    parsed = urlparse(citation)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        do_check = (
            check_url_reachability
            if check_url_reachability is not None
            else _env_check_url_reachability()
        )
        if not do_check:
            return {
                "citation": citation,
                "resolved": True,
                "kind": "external_url",
                "reachable": None,
                "detail": (
                    "URL syntax is valid; reachability not checked "
                    f"(set {_CHECK_URL_ENV}=1 to probe)."
                ),
            }
        reachable, detail = _probe_url(citation)
        return {
            "citation": citation,
            "resolved": reachable,
            "kind": "external_url",
            "reachable": reachable,
            "detail": detail,
        }

    artifact = _resolve_artifact(citation, conn=conn, session_ids=session_ids)
    if artifact is not None:
        return {
            "citation": citation,
            "resolved": True,
            "kind": "artifact",
            "artifact_id": artifact["artifact_id"],
            "session_id": artifact["session_id"],
            "artifact_type": artifact.get("artifact_type"),
        }

    path = _resolve_path(citation, workspace_root)
    if path is not None:
        return {
            "citation": citation,
            "resolved": True,
            "kind": "local_path",
            "path": str(path),
        }

    return {
        "citation": citation,
        "resolved": False,
        "kind": "unresolved",
    }


def validate_hypothesis_grounding(
    packet: Dict[str, Any],
    *,
    conn: Optional[sqlite3.Connection] = None,
    session_ids: Optional[Sequence[str]] = None,
    workspace_root: Optional[Path] = None,
) -> List[ValidationIssue]:
    """Validate evidence labels and citation resolution before verification."""
    issues = validate_evidence_items(packet.get("evidence"), require_label=True)
    citation_result = verify_citations(
        packet.get("citations"),
        conn=conn,
        session_ids=session_ids,
        workspace_root=workspace_root,
    )
    issues.extend(
        ValidationIssue(issue["field"], issue["message"], issue.get("severity", "error"))
        for issue in citation_result["issues"]
    )
    return issues


def evidence_issues_to_dicts(issues: Iterable[ValidationIssue]) -> List[Dict[str, str]]:
    return _issues_to_dicts(issues)


def deepcopy_evidence_rubric() -> Dict[str, Dict[str, object]]:
    return {
        name: {
            "score": item["score"],
            "description": item["description"],
        }
        for name, item in EVIDENCE_QUALITY_RUBRIC.items()
    }


def _resolve_artifact(
    citation: str,
    *,
    conn: Optional[sqlite3.Connection],
    session_ids: Optional[Sequence[str]],
) -> Optional[Dict[str, Any]]:
    if conn is None:
        return None
    try:
        if session_ids:
            for session_id in session_ids:
                row = conn.execute(
                    "SELECT * FROM artifacts WHERE artifact_id = ? AND session_id = ?",
                    (citation, session_id),
                ).fetchone()
                if row is not None:
                    return dict(row)
            return None
        row = conn.execute(
            "SELECT * FROM artifacts WHERE artifact_id = ?",
            (citation,),
        ).fetchone()
        return dict(row) if row is not None else None
    except sqlite3.DatabaseError:
        return None


def _resolve_path(citation: str, workspace_root: Optional[Path]) -> Optional[Path]:
    path = Path(citation)
    root = (workspace_root or Path.cwd()).resolve()
    candidates = [path]
    if not path.is_absolute():
        candidates.insert(0, root / path)
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        if resolved.exists() and resolved.is_file():
            return resolved
    return None


def _env_check_url_reachability() -> bool:
    raw = os.environ.get(_CHECK_URL_ENV, "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _probe_url(url: str, timeout: float = _URL_TIMEOUT_SEC) -> tuple:
    """Best-effort HEAD then GET; returns (reachable, detail)."""
    headers = {"User-Agent": "OpenLMlib-citation-check/1.0"}
    ctx = ssl.create_default_context()
    for method in ("HEAD", "GET"):
        try:
            req = Request(url, method=method, headers=headers)
            with urlopen(req, timeout=timeout, context=ctx) as resp:
                code = getattr(resp, "status", None) or resp.getcode()
                if code is not None and int(code) >= 400:
                    return False, f"URL returned HTTP {code}"
                return True, f"URL reachable via {method} (HTTP {code})"
        except HTTPError as exc:
            # Some hosts reject HEAD; try GET. 4xx/5xx on GET is unreachable.
            if method == "HEAD" and exc.code in {403, 405, 501}:
                continue
            return False, f"URL returned HTTP {exc.code}"
        except (URLError, socket.timeout, TimeoutError, ssl.SSLError, ValueError, OSError) as exc:
            if method == "HEAD":
                continue
            return False, f"URL not reachable: {exc}"
    return False, "URL not reachable"


def _issues_to_dicts(issues: Iterable[ValidationIssue]) -> List[Dict[str, str]]:
    return [
        {"field": issue.field, "message": issue.message, "severity": issue.severity}
        for issue in issues
    ]
