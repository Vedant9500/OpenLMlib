import tempfile
import unittest
from pathlib import Path

from openlmlib import db
from openlmlib.schema import Finding, FindingAudit, FindingText, compute_content_hash


class TestStorage(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
