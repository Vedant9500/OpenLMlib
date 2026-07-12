import tempfile
import unittest
from pathlib import Path

from openlmlib import db
from openlmlib.maintenance import ConsolidationGroup, MaintenanceEngine
from openlmlib.schema import Finding, FindingAudit, FindingText, compute_content_hash


def _insert(
    conn,
    finding_id,
    claim,
    confidence,
    *,
    tags=None,
    evidence=None,
    caveats=None,
    status="active",
    created_at="2020-01-01T00:00:00Z",
    embedding_id=1,
):
    text = FindingText(
        tags=tags or [],
        evidence=evidence or [],
        caveats=caveats or [],
        reasoning="Reasoning long enough for maintenance consolidation tests.",
    )
    audit = FindingAudit(
        proposed_by="tester",
        evidence_provided=True,
        reasoning_length=len(text.reasoning),
        failure_log=[],
        confidence_history=[{"timestamp": created_at, "confidence": confidence}],
    )
    finding = Finding(
        id=finding_id,
        project="openlmlib",
        claim=claim,
        confidence=confidence,
        created_at=created_at,
        embedding_id=embedding_id,
        content_hash="",
        status=status,
        text=text,
        audit=audit,
    )
    finding.content_hash = compute_content_hash(finding.to_content_dict(include_hash=False))
    db.insert_finding(conn, finding)
    return finding.content_hash


class TestMaintenance(unittest.TestCase):
    def test_consolidate_merges_text_and_honors_keep_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "findings.db")
            db.init_db(conn)

            hash_keep = _insert(
                conn,
                "keep-me",
                "Redis caching reduces latency",
                0.5,
                tags=["cache"],
                evidence=["a"],
                caveats=["c1"],
                embedding_id=1,
            )
            hash_drop = _insert(
                conn,
                "drop-me",
                "Redis caching reduces API latency",
                0.9,
                tags=["perf"],
                evidence=["b"],
                caveats=["c2"],
                embedding_id=2,
            )

            engine = MaintenanceEngine(conn)
            group = ConsolidationGroup(
                representative_id="drop-me",
                member_ids=["keep-me", "drop-me"],
                similarity_scores=[0.95],
                claims=["Redis caching reduces latency", "Redis caching reduces API latency"],
                projects=["openlmlib", "openlmlib"],
            )
            result = engine.consolidate_group(group, keep_id="keep-me")
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["target_id"], "keep-me")
            self.assertEqual(result["archived_ids"], ["drop-me"])

            survivor = db.get_finding(conn, "keep-me")
            archived = db.get_finding(conn, "drop-me")
            self.assertIsNotNone(survivor)
            self.assertIsNotNone(archived)
            self.assertEqual(survivor.status, "active")
            self.assertEqual(archived.status, "archived")
            self.assertEqual(set(survivor.text.tags), {"cache", "perf"})
            self.assertEqual(set(survivor.text.evidence), {"a", "b"})
            self.assertEqual(set(survivor.text.caveats), {"c1", "c2"})
            # content_hash must remain a content digest, not a marker string.
            self.assertEqual(archived.content_hash, hash_drop)
            self.assertEqual(survivor.content_hash, hash_keep)
            self.assertFalse(str(archived.content_hash).startswith("consolidated_into_"))

            audit = conn.execute(
                "SELECT failure_log FROM findings_audit WHERE id = ?",
                ("drop-me",),
            ).fetchone()
            self.assertIn("consolidated", audit["failure_log"])
            self.assertIn("keep-me", audit["failure_log"])
            conn.close()

    def test_consolidate_defaults_to_highest_confidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "findings.db")
            db.init_db(conn)
            _insert(conn, "low", "claim a", 0.4, evidence=["x"], embedding_id=1)
            _insert(conn, "high", "claim b", 0.95, evidence=["y"], embedding_id=2)
            engine = MaintenanceEngine(conn)
            group = ConsolidationGroup(
                representative_id="low",
                member_ids=["low", "high"],
                similarity_scores=[0.9],
                claims=["claim a", "claim b"],
                projects=["openlmlib", "openlmlib"],
            )
            result = engine.consolidate_group(group)
            self.assertEqual(result["target_id"], "high")
            conn.close()

    def test_find_stale_status_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "findings.db")
            db.init_db(conn)
            _insert(
                conn,
                "active-old",
                "old active claim",
                0.8,
                status="active",
                created_at="2020-01-01T00:00:00Z",
                embedding_id=1,
            )
            _insert(
                conn,
                "pending-old",
                "old pending claim",
                0.8,
                status="pending_review",
                created_at="2020-01-01T00:00:00Z",
                embedding_id=2,
            )
            engine = MaintenanceEngine(conn)
            active_only = engine.find_stale_findings(validity_days=30)
            pending = engine.find_stale_findings(
                validity_days=30,
                status_filter="pending_review",
            )
            self.assertEqual({f.id for f in active_only}, {"active-old"})
            self.assertEqual({f.id for f in pending}, {"pending-old"})
            conn.close()


if __name__ == "__main__":
    unittest.main()
