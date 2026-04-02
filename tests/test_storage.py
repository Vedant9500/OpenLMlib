import tempfile
import unittest
from pathlib import Path

from openlmlib import db
from openlmlib.schema import Finding, FindingAudit, FindingText, compute_content_hash


class TestStorage(unittest.TestCase):
    def test_connect_sets_perf_pragmas(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "findings.db"
            conn = db.connect(db_path)
            journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
            synchronous = conn.execute("PRAGMA synchronous;").fetchone()[0]
            temp_store = conn.execute("PRAGMA temp_store;").fetchone()[0]
            cache_size = conn.execute("PRAGMA cache_size;").fetchone()[0]
            wal_autocheckpoint = conn.execute("PRAGMA wal_autocheckpoint;").fetchone()[0]
            conn.close()

            self.assertEqual(str(journal_mode).lower(), "wal")
            self.assertEqual(int(synchronous), 1)
            self.assertEqual(int(temp_store), 2)
            self.assertEqual(int(cache_size), -20000)
            self.assertEqual(int(wal_autocheckpoint), 4000)

    def test_insert_and_get(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "findings.db"
            conn = db.connect(db_path)
            db.init_db(conn)

            text = FindingText(
                tags=["perf"],
                evidence=["load test"],
                caveats=["redis required"],
                reasoning="Observed lower p99 latency in staging.",
            )
            audit = FindingAudit(
                proposed_by="tester",
                evidence_provided=True,
                reasoning_length=len(text.reasoning),
                failure_log=[],
                confidence_history=[{"timestamp": "2026-03-31T00:00:00Z", "confidence": 0.8}],
            )
            finding = Finding(
                id="test-001",
                project="glassbox",
                claim="Cache improved latency",
                confidence=0.8,
                created_at="2026-03-31T00:00:00Z",
                embedding_id=123,
                content_hash="",
                status="active",
                text=text,
                audit=audit,
                full_text="Extended benchmark notes for rebuilds and deep inspection.",
            )
            finding.content_hash = compute_content_hash(finding.to_content_dict(include_hash=False))

            db.insert_finding(conn, finding)
            loaded = db.get_finding(conn, "test-001")
            conn.close()

            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.id, finding.id)
            self.assertEqual(loaded.claim, finding.claim)
            self.assertEqual(loaded.text.evidence, finding.text.evidence)
            self.assertEqual(loaded.full_text, finding.full_text)

    def test_logs_retrieval_usage(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "findings.db"
            conn = db.connect(db_path)
            db.init_db(conn)

            text = FindingText(
                tags=["retrieval"],
                evidence=["source"],
                caveats=[],
                reasoning="Reasoning with enough length for testing storage behavior.",
            )
            audit = FindingAudit(
                proposed_by="tester",
                evidence_provided=True,
                reasoning_length=len(text.reasoning),
                failure_log=[],
                confidence_history=[{"timestamp": "2026-04-01T00:00:00Z", "confidence": 0.8}],
            )
            finding = Finding(
                id="test-usage-001",
                project="openlmlib",
                claim="Test retrieval usage logging",
                confidence=0.8,
                created_at="2026-04-01T00:00:00Z",
                embedding_id=456,
                content_hash="",
                status="active",
                text=text,
                audit=audit,
            )
            finding.content_hash = compute_content_hash(finding.to_content_dict(include_hash=False))
            db.insert_finding(conn, finding)

            db.log_retrieval_usage(
                conn,
                query_id="qry-test-001",
                query="test query",
                created_at="2026-04-02T00:00:00Z",
                items=[{"id": "test-usage-001"}],
                project="openlmlib",
                tags=["retrieval"],
            )

            usage = db.list_retrieval_usage(conn, "qry-test-001")
            conn.close()

            self.assertEqual(len(usage), 1)
            self.assertEqual(usage[0]["finding_id"], "test-usage-001")
            self.assertEqual(usage[0]["rank"], 1)
            self.assertTrue(usage[0]["cited"])

    def test_search_handles_hyphenated_query(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "findings.db"
            conn = db.connect(db_path)
            db.init_db(conn)

            text = FindingText(
                tags=["retrieval"],
                evidence=["top-20 report"],
                caveats=[],
                reasoning="Reported top-20 improvements for contextual retrieval.",
            )
            audit = FindingAudit(
                proposed_by="tester",
                evidence_provided=True,
                reasoning_length=len(text.reasoning),
                failure_log=[],
                confidence_history=[{"timestamp": "2026-04-01T00:00:00Z", "confidence": 0.8}],
            )
            finding = Finding(
                id="test-hyphen-001",
                project="lmlib",
                claim="top-20 retrieval failure metric",
                confidence=0.8,
                created_at="2026-04-01T00:00:00Z",
                embedding_id=789,
                content_hash="",
                status="active",
                text=text,
                audit=audit,
            )
            finding.content_hash = compute_content_hash(finding.to_content_dict(include_hash=False))
            db.insert_finding(conn, finding)

            rows = db.search_findings_filtered(conn, query="top-20 retrieval", limit=5)
            conn.close()

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["id"], "test-hyphen-001")


if __name__ == "__main__":
    unittest.main()
