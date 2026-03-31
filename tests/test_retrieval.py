import tempfile
import unittest
from pathlib import Path

from openlmlib import db
from openlmlib.retrieval import RetrievalEngine, RetrievalFilters
from openlmlib.schema import Finding, FindingAudit, FindingText, compute_content_hash
from openlmlib.settings import RetrievalSettings
from openlmlib.vector_store import NumpyVectorStore


class DummyEmbedder:
    def encode(self, texts):
        vectors = []
        for text in texts:
            lower = text.lower()
            if "latency" in lower or "cache" in lower:
                vectors.append([1.0, 0.0])
            else:
                vectors.append([0.0, 1.0])
        return vectors


class DummySettings:
    def __init__(self):
        self.retrieval = RetrievalSettings(
            semantic_k=10,
            lexical_k=10,
            final_k=5,
            semantic_oversample_factor=3,
        )


def _insert_finding(conn, finding_id, embedding_id, project, claim, tags, confidence, created_at):
    text = FindingText(
        tags=tags,
        evidence=["load test evidence"],
        caveats=[],
        reasoning="This result was validated in staging with measurable impact.",
    )
    audit = FindingAudit(
        proposed_by="test",
        evidence_provided=True,
        reasoning_length=len(text.reasoning),
        failure_log=[],
        confidence_history=[{"timestamp": created_at, "confidence": confidence, "reason": "test"}],
    )
    finding = Finding(
        id=finding_id,
        project=project,
        claim=claim,
        confidence=confidence,
        created_at=created_at,
        embedding_id=embedding_id,
        content_hash="",
        status="active",
        text=text,
        audit=audit,
    )
    finding.content_hash = compute_content_hash(finding.to_content_dict(include_hash=False))
    db.insert_finding(conn, finding)


class TestRetrieval(unittest.TestCase):
    def test_combines_semantic_and_lexical(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "findings.db"
            conn = db.connect(db_path)
            db.init_db(conn)

            _insert_finding(
                conn,
                finding_id="f-1",
                embedding_id=101,
                project="glassbox",
                claim="Redis cache reduced API latency",
                tags=["perf", "cache"],
                confidence=0.9,
                created_at="2026-03-30T00:00:00Z",
            )
            _insert_finding(
                conn,
                finding_id="f-2",
                embedding_id=202,
                project="other",
                claim="Schema migration checklist",
                tags=["db"],
                confidence=0.8,
                created_at="2026-03-01T00:00:00Z",
            )

            store = NumpyVectorStore(dim=2, metric="cosine")
            store.add([101, 202], [[1.0, 0.0], [0.0, 1.0]])

            engine = RetrievalEngine(
                conn=conn,
                embedder=DummyEmbedder(),
                vector_store=store,
                settings=DummySettings(),
            )

            result = engine.search("cache latency")
            conn.close()

            self.assertGreaterEqual(len(result["items"]), 1)
            self.assertEqual(result["items"][0]["id"], "f-1")
            self.assertIn("final_score", result["items"][0])

    def test_applies_project_and_tag_filters(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "findings.db"
            conn = db.connect(db_path)
            db.init_db(conn)

            _insert_finding(
                conn,
                finding_id="f-1",
                embedding_id=101,
                project="glassbox",
                claim="Redis cache reduced API latency",
                tags=["perf", "cache"],
                confidence=0.9,
                created_at="2026-03-30T00:00:00Z",
            )
            _insert_finding(
                conn,
                finding_id="f-2",
                embedding_id=202,
                project="glassbox",
                claim="Queue workers need backoff",
                tags=["queue"],
                confidence=0.85,
                created_at="2026-03-15T00:00:00Z",
            )

            store = NumpyVectorStore(dim=2, metric="cosine")
            store.add([101, 202], [[1.0, 0.0], [1.0, 0.0]])

            engine = RetrievalEngine(
                conn=conn,
                embedder=DummyEmbedder(),
                vector_store=store,
                settings=DummySettings(),
            )

            result = engine.search(
                "cache",
                filters=RetrievalFilters(project="glassbox", tags=["cache"], confidence_min=0.7),
            )
            conn.close()

            self.assertEqual([item["id"] for item in result["items"]], ["f-1"])


if __name__ == "__main__":
    unittest.main()
