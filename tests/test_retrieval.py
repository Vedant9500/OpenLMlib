import tempfile
import unittest
from pathlib import Path

from openlmlib import db
from openlmlib.retrieval import RetrievalEngine, RetrievalFilters, Phase4Options
from openlmlib.schema import Finding, FindingAudit, FindingText, compute_content_hash
from openlmlib.settings import (
    DecompositionSettings,
    PackingSettings,
    Phase4Settings,
    QueryExpansionSettings,
    RerankingSettings,
    RetrievalSettings,
)
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


class ExpansionDummyEmbedder:
    def encode(self, texts):
        vectors = []
        for text in texts:
            lower = text.lower()
            if "database" in lower or "schema" in lower or "migration" in lower:
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
        self.phase4 = Phase4Settings(
            reranking=RerankingSettings(enabled=False),
            query_expansion=QueryExpansionSettings(enabled=False),
            decomposition=DecompositionSettings(enabled=True),
            packing=PackingSettings(enabled=False),
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

    def test_marks_old_findings_pending_review(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "findings.db"
            conn = db.connect(db_path)
            db.init_db(conn)

            _insert_finding(
                conn,
                finding_id="f-old",
                embedding_id=303,
                project="glassbox",
                claim="Legacy cache behavior",
                tags=["cache"],
                confidence=0.9,
                created_at="2025-10-01T00:00:00Z",
            )

            store = NumpyVectorStore(dim=2, metric="cosine")
            store.add([303], [[1.0, 0.0]])

            engine = RetrievalEngine(
                conn=conn,
                embedder=DummyEmbedder(),
                vector_store=store,
                settings=DummySettings(),
            )

            result = engine.search("cache latency")
            conn.close()

            self.assertEqual(result["items"][0]["id"], "f-old")
            self.assertTrue(result["items"][0]["pending_review"])

    def test_lexical_scores_are_normalized_in_fusion(self):
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
                claim="Latency investigations and error budgets",
                tags=["perf"],
                confidence=0.9,
                created_at="2026-03-30T00:00:00Z",
            )

            store = NumpyVectorStore(dim=2, metric="cosine")
            store.add([101, 202], [[1.0, 0.0], [0.0, 1.0]])

            engine = RetrievalEngine(
                conn=conn,
                embedder=DummyEmbedder(),
                vector_store=store,
                settings=DummySettings(),
            )

            result = engine.search("cache api latency")
            conn.close()

            lexical_scores = [item.get("lexical_score") for item in result["items"] if "lexical_score" in item]
            self.assertTrue(lexical_scores)
            for score in lexical_scores:
                self.assertGreaterEqual(score, 0.0)
                self.assertLessEqual(score, 1.0)

    def test_enhanced_decomposition_preserves_metadata(self):
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

            store = NumpyVectorStore(dim=2, metric="cosine")
            store.add([101], [[1.0, 0.0]])

            engine = RetrievalEngine(
                conn=conn,
                embedder=DummyEmbedder(),
                vector_store=store,
                settings=DummySettings(),
            )

            result = engine.search_enhanced(
                "cache latency",
                options=Phase4Options(
                    rerank=False,
                    decompose=True,
                    deduplicate=False,
                    reasoning_trace=False,
                    pack_context=False,
                ),
            )
            conn.close()

            self.assertEqual(len(result["items"]), 1)
            item = result["items"][0]
            self.assertEqual(item["id"], "f-1")
            self.assertEqual(item["project"], "glassbox")
            self.assertIn("confidence", item)
            self.assertIn("pending_review", item)

    def test_enhanced_query_expansion_uses_variant_results(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "findings.db"
            conn = db.connect(db_path)
            db.init_db(conn)

            _insert_finding(
                conn,
                finding_id="f-schema",
                embedding_id=101,
                project="glassbox",
                claim="Schema migration checklist",
                tags=["db"],
                confidence=0.9,
                created_at="2026-03-30T00:00:00Z",
            )
            _insert_finding(
                conn,
                finding_id="f-queue",
                embedding_id=202,
                project="glassbox",
                claim="Queue workers need backoff",
                tags=["queue"],
                confidence=0.85,
                created_at="2025-03-30T00:00:00Z",
            )

            store = NumpyVectorStore(dim=2, metric="cosine")
            store.add([101, 202], [[1.0, 0.0], [0.0, 1.0]])

            engine = RetrievalEngine(
                conn=conn,
                embedder=ExpansionDummyEmbedder(),
                vector_store=store,
                settings=DummySettings(),
            )

            result = engine.search_enhanced(
                "sql query",
                options=Phase4Options(
                    rerank=False,
                    expand_query=True,
                    decompose=False,
                    deduplicate=False,
                    reasoning_trace=False,
                    pack_context=False,
                ),
            )
            conn.close()

            self.assertEqual(result["items"][0]["id"], "f-schema")
            self.assertIn(
                "sql query database schema migration",
                result["items"][0]["expansion_variants"],
            )
            self.assertGreaterEqual(
                result["meta"]["phase4"]["expansion"]["merged_count"],
                2,
            )

    def test_lexical_hits_include_text_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "findings.db"
            conn = db.connect(db_path)
            db.init_db(conn)

            _insert_finding(
                conn,
                finding_id="f-lex",
                embedding_id=301,
                project="glassbox",
                claim="Redis cache reduced API latency",
                tags=["perf", "cache"],
                confidence=0.9,
                created_at="2026-03-30T00:00:00Z",
            )

            # Empty vector store forces pure lexical path.
            store = NumpyVectorStore(dim=2, metric="cosine")
            engine = RetrievalEngine(
                conn=conn,
                embedder=DummyEmbedder(),
                vector_store=store,
                settings=DummySettings(),
            )
            result = engine.search("cache latency", final_k=5)
            conn.close()

            self.assertEqual(len(result["items"]), 1)
            item = result["items"][0]
            self.assertEqual(item["evidence"], ["load test evidence"])
            self.assertEqual(item["tags"], ["perf", "cache"])
            self.assertTrue(item["reasoning"])
            self.assertEqual(item["caveats"], [])

    def test_archived_findings_excluded_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "findings.db"
            conn = db.connect(db_path)
            db.init_db(conn)

            _insert_finding(
                conn,
                finding_id="f-active",
                embedding_id=401,
                project="glassbox",
                claim="Redis cache reduced API latency",
                tags=["perf"],
                confidence=0.9,
                created_at="2026-03-30T00:00:00Z",
            )
            _insert_finding(
                conn,
                finding_id="f-archived",
                embedding_id=402,
                project="glassbox",
                claim="Redis cache reduced API latency archived",
                tags=["perf"],
                confidence=0.95,
                created_at="2026-03-30T00:00:00Z",
            )
            conn.execute("UPDATE findings SET status='archived' WHERE id='f-archived'")
            conn.commit()

            store = NumpyVectorStore(dim=2, metric="cosine")
            store.add([401, 402], [[1.0, 0.0], [1.0, 0.0]])
            engine = RetrievalEngine(
                conn=conn,
                embedder=DummyEmbedder(),
                vector_store=store,
                settings=DummySettings(),
            )
            result = engine.search("cache latency", final_k=10)
            conn.close()

            ids = [item["id"] for item in result["items"]]
            self.assertIn("f-active", ids)
            self.assertNotIn("f-archived", ids)

    def test_pack_context_uses_max_context_tokens(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "findings.db"
            conn = db.connect(db_path)
            db.init_db(conn)

            for i in range(5):
                _insert_finding(
                    conn,
                    finding_id=f"f-pack-{i}",
                    embedding_id=500 + i,
                    project="glassbox",
                    claim=f"Redis cache latency finding {i} " + ("word " * 40),
                    tags=["perf"],
                    confidence=0.9,
                    created_at="2026-03-30T00:00:00Z",
                )

            store = NumpyVectorStore(dim=2, metric="cosine")
            store.add(
                [500 + i for i in range(5)],
                [[1.0, 0.0] for _ in range(5)],
            )
            settings = DummySettings()
            settings.phase4.packing.enabled = True
            settings.phase4.packing.max_tokens = 4000
            engine = RetrievalEngine(
                conn=conn,
                embedder=DummyEmbedder(),
                vector_store=store,
                settings=settings,
            )
            result = engine.search_enhanced(
                "cache latency",
                options=Phase4Options(
                    rerank=False,
                    decompose=False,
                    deduplicate=False,
                    reasoning_trace=False,
                    pack_context=True,
                    max_context_tokens=80,
                ),
                final_k=5,
            )
            conn.close()

            packing = result["meta"]["phase4"]["packing"]
            self.assertEqual(packing["status"], "ok")
            self.assertEqual(packing["max_tokens"], 80)
            self.assertLess(packing["output_count"], 5)


if __name__ == "__main__":
    unittest.main()
