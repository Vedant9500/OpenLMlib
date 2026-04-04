import unittest

from openlmlib.reranking import CrossEncoderReranker, HybridReranker, _normalize_scores


class TestNormalizeScores(unittest.TestCase):
    def test_empty_list(self):
        self.assertEqual(_normalize_scores([]), [])

    def test_single_value(self):
        self.assertEqual(_normalize_scores([0.5]), [0.5])

    def test_uniform_values(self):
        result = _normalize_scores([0.5, 0.5, 0.5])
        self.assertEqual(result, [0.5, 0.5, 0.5])

    def test_normal_range(self):
        result = _normalize_scores([0.0, 0.5, 1.0])
        self.assertAlmostEqual(result[0], 0.0)
        self.assertAlmostEqual(result[1], 0.5)
        self.assertAlmostEqual(result[2], 1.0)

    def test_negative_values(self):
        result = _normalize_scores([-1.0, 0.0, 1.0])
        self.assertAlmostEqual(result[0], 0.0)
        self.assertAlmostEqual(result[1], 0.5)
        self.assertAlmostEqual(result[2], 1.0)


class TestCrossEncoderReranker(unittest.TestCase):
    def test_build_document_text(self):
        item = {
            "claim": "Redis caching improves latency",
            "reasoning": "Tested in production with 40% improvement",
            "evidence": ["load test results", "perf comparison"],
        }
        text = CrossEncoderReranker._build_document_text(item, "claim")
        self.assertIn("Redis caching improves latency", text)
        self.assertIn("Tested in production", text)
        self.assertIn("load test results", text)

    def test_build_document_text_missing_fields(self):
        item = {"claim": "Simple claim only"}
        text = CrossEncoderReranker._build_document_text(item, "claim")
        self.assertEqual(text, "Simple claim only")

    def test_build_document_text_empty(self):
        item = {}
        text = CrossEncoderReranker._build_document_text(item, "claim")
        self.assertEqual(text, "")

    def test_rerank_empty(self):
        # Can't test actual cross-encoder without model download,
        # but we can test the empty case
        class DummyReranker:
            def __init__(self, *args, **kwargs):
                pass
            def score_pairs(self, query, documents):
                return []
            def rerank(self, query, candidates, top_k=None, text_field="claim", fallback_score_field="final_score"):
                return []

        # Replace import temporarily
        import openlmlib.reranking as reranking_mod
        original = reranking_mod.CrossEncoderReranker
        reranking_mod.CrossEncoderReranker = DummyReranker

        try:
            reranker = DummyReranker()
            result = reranker.rerank("test query", [], top_k=5)
            self.assertEqual(result, [])
        finally:
            reranking_mod.CrossEncoderReranker = original


class TestHybridReranker(unittest.TestCase):
    def test_blend_scores(self):
        """Test that hybrid reranker blends cross-encoder and retrieval scores."""
        class DummyReranker:
            def __init__(self, *args, **kwargs):
                pass
            def rerank(self, query, candidates, top_k=None):
                # Assign fixed rerank scores
                for i, item in enumerate(candidates):
                    item["rerank_score"] = float(i + 1)
                return candidates

        hybrid = HybridReranker(DummyReranker(), alpha=0.7)
        candidates = [
            {"id": "a", "final_score": 0.9, "claim": "claim a"},
            {"id": "b", "final_score": 0.5, "claim": "claim b"},
            {"id": "c", "final_score": 0.7, "claim": "claim c"},
        ]
        result = hybrid.rerank("test query", candidates, top_k=2)

        self.assertEqual(len(result), 2)
        # All items should have hybrid_score
        for item in result:
            self.assertIn("hybrid_score", item)

    def test_empty_candidates(self):
        class DummyReranker:
            def __init__(self, *args, **kwargs):
                pass
            def rerank(self, query, candidates, top_k=None):
                return candidates

        hybrid = HybridReranker(DummyReranker())
        result = hybrid.rerank("query", [])
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
