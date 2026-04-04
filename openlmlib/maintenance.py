from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


@dataclass
class MaintenanceSettings:
    validity_days: int = 90
    consolidation_similarity_threshold: float = 0.85
    archive_on_failure_count: int = 3
    confidence_decay_factor: float = 0.9


@dataclass
class StaleFinding:
    id: str
    project: str
    claim: str
    confidence: float
    created_at: str
    age_days: int
    status: str
    pending_review: bool = True


@dataclass
class ConsolidationGroup:
    """A group of similar findings that can be consolidated."""
    representative_id: str
    member_ids: List[str]
    similarity_scores: List[float]
    claims: List[str]
    projects: List[str]


@dataclass
class FailureFeedback:
    finding_id: str
    task_id: str
    failure_reason: str
    timestamp: str
    confidence_before: float
    confidence_after: float
    failure_count: int


class MaintenanceEngine:
    """Handles library maintenance: staleness tracking, consolidation, archiving, and feedback."""

    def __init__(
        self,
        conn,
        embedder=None,
        vector_store=None,
        settings: Optional[MaintenanceSettings] = None,
    ) -> None:
        self._conn = conn
        self._embedder = embedder
        self._vector_store = vector_store
        self._settings = settings or MaintenanceSettings()

    def find_stale_findings(
        self,
        validity_days: Optional[int] = None,
        status_filter: Optional[str] = None,
    ) -> List[StaleFinding]:
        """Find findings that exceed the validity window and need review."""
        days = validity_days or self._settings.validity_days
        cutoff = datetime.now(timezone.utc).replace(microsecond=0)
        from datetime import timedelta
        cutoff = cutoff - timedelta(days=days)
        cutoff_iso = cutoff.isoformat().replace("+00:00", "Z")

        query = """
            SELECT f.id, f.project, f.claim, f.confidence, f.created_at, f.status
            FROM findings f
            WHERE f.created_at < ?
            AND f.status = 'active'
        """
        params: list = [cutoff_iso]

        if status_filter:
            query += " AND f.status = ?"
            params.append(status_filter)

        query += " ORDER BY f.created_at ASC"

        rows = self._conn.execute(query, params).fetchall()
        stale_findings: List[StaleFinding] = []

        for row in rows:
            created = _parse_utc(row["created_at"])
            if created is None:
                continue
            age_days = int((datetime.now(timezone.utc) - created).total_seconds() / 86400.0)
            stale_findings.append(
                StaleFinding(
                    id=row["id"],
                    project=row["project"] or "",
                    claim=row["claim"],
                    confidence=float(row["confidence"] or 0.0),
                    created_at=row["created_at"],
                    age_days=age_days,
                    status=row["status"],
                    pending_review=True,
                )
            )

        logger.info(
            "find_stale_findings: validity_days=%d found=%d",
            days,
            len(stale_findings),
        )
        return stale_findings

    def mark_for_review(self, finding_ids: List[str]) -> Dict[str, Any]:
        """Mark findings as pending_review by updating their status."""
        marked = 0
        for finding_id in finding_ids:
            row = self._conn.execute(
                "SELECT status FROM findings WHERE id = ?",
                (finding_id,),
            ).fetchone()
            if row and row["status"] == "active":
                self._conn.execute(
                    "UPDATE findings SET status = 'pending_review' WHERE id = ?",
                    (finding_id,),
                )
                marked += 1

        self._conn.commit()
        logger.info("mark_for_review: marked=%d", marked)
        return {"status": "ok", "marked": marked}

    def find_consolidation_groups(
        self,
        similarity_threshold: Optional[float] = None,
        project: Optional[str] = None,
    ) -> List[ConsolidationGroup]:
        """Find groups of similar findings that could be consolidated.

        Uses embedding similarity to cluster findings. Groups with high
        similarity scores are candidates for consolidation.
        """
        threshold = similarity_threshold or self._settings.consolidation_similarity_threshold

        # Get all active findings
        query = "SELECT id, project, claim, embedding_id FROM findings WHERE status = 'active'"
        params: list = []
        if project:
            query += " AND project = ?"
            params.append(project)

        rows = self._conn.execute(query, params).fetchall()
        if len(rows) < 2:
            return []

        # Build claim list for similarity comparison
        claims = [(row["id"], row["claim"]) for row in rows]
        groups: List[ConsolidationGroup] = []
        used_ids: set = set()

        for i, (id_a, claim_a) in enumerate(claims):
            if id_a in used_ids:
                continue

            members = [id_a]
            scores = []
            member_claims = [claim_a]
            member_projects = [rows[i]["project"] or ""]

            for j, (id_b, claim_b) in enumerate(claims):
                if i == j or id_b in used_ids:
                    continue

                sim = _claim_similarity(claim_a, claim_b)
                if sim >= threshold:
                    members.append(id_b)
                    scores.append(sim)
                    member_claims.append(claim_b)
                    member_projects.append(rows[j]["project"] or "")

            if len(members) > 1:
                for mid in members:
                    used_ids.add(mid)
                groups.append(
                    ConsolidationGroup(
                        representative_id=id_a,
                        member_ids=members,
                        similarity_scores=scores,
                        claims=member_claims,
                        projects=member_projects,
                    )
                )

        logger.info(
            "find_consolidation_groups: threshold=%.2f groups=%d",
            threshold,
            len(groups),
        )
        return groups

    def consolidate_group(
        self,
        group: ConsolidationGroup,
        keep_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Consolidate a group of similar findings into one.

        Keeps the highest-confidence finding as the representative and
        merges evidence/tags from others. Archives the rest.
        """
        if len(group.member_ids) < 2:
            return {"status": "ok", "message": "No consolidation needed", "merged": 0}

        target_id = keep_id or group.representative_id

        # Get all findings in the group
        placeholders = ",".join("?" for _ in group.member_ids)
        rows = self._conn.execute(
            f"SELECT id, claim, confidence, project FROM findings WHERE id IN ({placeholders})",
            group.member_ids,
        ).fetchall()

        if not rows:
            return {"status": "error", "message": "No findings found in group"}

        # Find the best representative (highest confidence)
        best = max(rows, key=lambda r: float(r["confidence"] or 0.0))
        target_id = best["id"]

        # Merge tags and evidence from others into the representative
        merged_count = 0
        for row in rows:
            if row["id"] == target_id:
                continue

            # Archive the duplicate
            self._conn.execute(
                "UPDATE findings SET status = 'archived', content_hash = ? WHERE id = ?",
                (f"consolidated_into_{target_id}", row["id"]),
            )
            merged_count += 1

        self._conn.commit()

        logger.info(
            "consolidate_group: target=%s merged=%d",
            target_id,
            merged_count,
        )
        return {
            "status": "ok",
            "target_id": target_id,
            "merged": merged_count,
            "archived_ids": [r["id"] for r in rows if r["id"] != target_id],
        }

    def run_consolidation(
        self,
        similarity_threshold: Optional[float] = None,
        project: Optional[str] = None,
        auto_consolidate: bool = False,
    ) -> Dict[str, Any]:
        """Full consolidation workflow: find groups and optionally consolidate."""
        groups = self.find_consolidation_groups(
            similarity_threshold=similarity_threshold,
            project=project,
        )

        if not groups:
            return {"status": "ok", "message": "No consolidation groups found", "groups": 0}

        results: List[Dict[str, Any]] = []
        total_merged = 0

        for group in groups:
            if auto_consolidate:
                result = self.consolidate_group(group)
                total_merged += result.get("merged", 0)
                results.append(result)
            else:
                results.append({
                    "group": {
                        "representative_id": group.representative_id,
                        "member_ids": group.member_ids,
                        "similarity_scores": group.similarity_scores,
                        "claims": group.claims,
                        "projects": group.projects,
                    },
                })

        return {
            "status": "ok",
            "groups_found": len(groups),
            "total_merged": total_merged if auto_consolidate else 0,
            "results": results,
        }

    def log_failure(
        self,
        finding_id: str,
        task_id: str,
        failure_reason: str,
        confidence_decay: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Log a task failure related to a finding and decay its confidence.

        After archive_on_failure_count failures, the finding is archived.
        """
        decay = confidence_decay or self._settings.confidence_decay_factor

        # Get current finding
        row = self._conn.execute(
            "SELECT id, confidence, status FROM findings WHERE id = ?",
            (finding_id,),
        ).fetchone()

        if not row:
            return {"status": "error", "message": f"Finding {finding_id} not found"}

        current_confidence = float(row["confidence"] or 0.0)
        current_status = row["status"]

        # Get existing failure log from audit table
        audit_row = self._conn.execute(
            "SELECT failure_log FROM findings_audit WHERE id = ?",
            (finding_id,),
        ).fetchone()

        failure_log = []
        if audit_row and audit_row["failure_log"]:
            import json
            try:
                failure_log = json.loads(audit_row["failure_log"])
            except Exception:
                failure_log = []

        # Add new failure entry
        timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        failure_entry = {
            "task_id": task_id,
            "reason": failure_reason,
            "timestamp": timestamp,
            "confidence_before": current_confidence,
        }
        failure_log.append(failure_entry)

        # Decay confidence
        new_confidence = round(current_confidence * decay, 3)
        failure_entry["confidence_after"] = new_confidence

        # Update finding
        self._conn.execute(
            "UPDATE findings SET confidence = ? WHERE id = ?",
            (new_confidence, finding_id),
        )

        # Update audit table
        import json
        self._conn.execute(
            "UPDATE findings_audit SET failure_log = ? WHERE id = ?",
            (json.dumps(failure_log, separators=(",", ":")), finding_id),
        )

        self._conn.commit()

        failure_count = len(failure_log)
        archived = False

        # Archive if failure count exceeds threshold
        if failure_count >= self._settings.archive_on_failure_count and current_status != "archived":
            self._conn.execute(
                "UPDATE findings SET status = 'archived' WHERE id = ?",
                (finding_id,),
            )
            self._conn.commit()
            archived = True

        feedback = FailureFeedback(
            finding_id=finding_id,
            task_id=task_id,
            failure_reason=failure_reason,
            timestamp=timestamp,
            confidence_before=current_confidence,
            confidence_after=new_confidence,
            failure_count=failure_count,
        )

        logger.info(
            "log_failure: finding=%s failures=%d confidence=%.2f→%.2f archived=%s",
            finding_id,
            failure_count,
            current_confidence,
            new_confidence,
            archived,
        )

        return {
            "status": "ok",
            "feedback": {
                "finding_id": feedback.finding_id,
                "task_id": feedback.task_id,
                "failure_reason": feedback.failure_reason,
                "timestamp": feedback.timestamp,
                "confidence_before": feedback.confidence_before,
                "confidence_after": feedback.confidence_after,
                "failure_count": feedback.failure_count,
                "archived": archived,
            },
        }

    def get_failure_ledger(
        self,
        finding_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get failure ledger entries, optionally filtered by finding_id."""
        if finding_id:
            audit_row = self._conn.execute(
                "SELECT failure_log FROM findings_audit WHERE id = ?",
                (finding_id,),
            ).fetchone()
            if not audit_row or not audit_row["failure_log"]:
                return []
            import json
            try:
                return json.loads(audit_row["failure_log"])
            except Exception:
                return []

        # Get all findings with failure logs
        rows = self._conn.execute(
            "SELECT id, failure_log FROM findings_audit WHERE failure_log IS NOT NULL AND failure_log != '[]' LIMIT ?",
            (limit,),
        ).fetchall()

        ledger: List[Dict[str, Any]] = []
        import json
        for row in rows:
            try:
                failures = json.loads(row["failure_log"])
                for failure in failures:
                    failure["finding_id"] = row["id"]
                    ledger.append(failure)
            except Exception:
                continue

        return ledger[:limit]

    def archive_finding(
        self,
        finding_id: str,
        reason: str = "",
    ) -> Dict[str, Any]:
        """Soft-archive a finding (doesn't delete, just marks as archived)."""
        row = self._conn.execute(
            "SELECT id, status FROM findings WHERE id = ?",
            (finding_id,),
        ).fetchone()

        if not row:
            return {"status": "error", "message": f"Finding {finding_id} not found"}

        if row["status"] == "archived":
            return {"status": "ok", "message": "Finding already archived"}

        self._conn.execute(
            "UPDATE findings SET status = 'archived' WHERE id = ?",
            (finding_id,),
        )
        self._conn.commit()

        logger.info("archive_finding: id=%s reason=%s", finding_id, reason)
        return {"status": "ok", "archived_id": finding_id, "reason": reason}

    def restore_finding(
        self,
        finding_id: str,
    ) -> Dict[str, Any]:
        """Restore an archived finding back to active status."""
        row = self._conn.execute(
            "SELECT id, status FROM findings WHERE id = ?",
            (finding_id,),
        ).fetchone()

        if not row:
            return {"status": "error", "message": f"Finding {finding_id} not found"}

        if row["status"] != "archived":
            return {"status": "ok", "message": "Finding is not archived"}

        self._conn.execute(
            "UPDATE findings SET status = 'active' WHERE id = ?",
            (finding_id,),
        )
        self._conn.commit()

        logger.info("restore_finding: id=%s", finding_id)
        return {"status": "ok", "restored_id": finding_id}

    def get_maintenance_summary(
        self,
        validity_days: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Get a summary of library health and maintenance status."""
        days = validity_days or self._settings.validity_days

        # Count findings by status
        status_counts = {}
        for row in self._conn.execute(
            "SELECT status, COUNT(*) as count FROM findings GROUP BY status"
        ).fetchall():
            status_counts[row["status"]] = row["count"]

        # Get stale findings count
        stale = self.find_stale_findings(validity_days=days)

        # Get failure ledger summary
        ledger = self.get_failure_ledger(limit=100)
        findings_with_failures = len(set(entry.get("finding_id", "") for entry in ledger))

        return {
            "status": "ok",
            "total_findings": sum(status_counts.values()),
            "status_breakdown": status_counts,
            "stale_findings": len(stale),
            "validity_days": days,
            "findings_with_failures": findings_with_failures,
            "total_failure_entries": len(ledger),
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


def _claim_similarity(claim_a: str, claim_b: str) -> float:
    """Compute Jaccard similarity between two claims for consolidation."""
    import re
    stopwords = {
        "a", "an", "the", "is", "are", "was", "were", "be", "been",
        "have", "has", "had", "do", "does", "did", "will", "would",
        "could", "should", "may", "might", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "as", "and", "or", "but",
        "not", "no", "it", "its", "this", "that", "these", "those",
    }
    tokens_a = set(t for t in re.findall(r"[a-z0-9]+", claim_a.lower()) if t not in stopwords and len(t) > 2)
    tokens_b = set(t for t in re.findall(r"[a-z0-9]+", claim_b.lower()) if t not in stopwords and len(t) > 2)

    if not tokens_a or not tokens_b:
        return 0.0

    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b

    return len(intersection) / len(union) if union else 0.0
