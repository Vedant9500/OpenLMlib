import unittest

from openlmlib.evaluation import evaluate_retrieval, faithfulness_score, relevance_alignment


class DummyEmbedder:
    def encode(self, texts):
        vectors = []
        for text in texts:
            lower = text.lower()
            if "cache" in lower:
                vectors.append([1.0, 0.0])
            else:
                vectors.append([0.0, 1.0])
        return vectors


class TestEvaluation(unittest.TestCase):
    def test_retrieval_metrics(self):
        metrics = evaluate_retrieval(
            expected_ids=["f-1", "f-2"],
            retrieved_ids=["f-1", "f-9", "f-2"],
            k_values=(1, 3),
        )
        self.assertEqual(metrics.precision_at_k[1], 1.0)
        self.assertEqual(metrics.recall_at_k[1], 0.5)
        self.assertAlmostEqual(metrics.precision_at_k[3], 2 / 3)
        self.assertEqual(metrics.recall_at_k[3], 1.0)

    def test_faithfulness_score(self):
        score = faithfulness_score(
            answer="Redis cache reduced API latency based on load test evidence.",
            retrieved_items=[
                {
                    "claim": "Redis cache reduced API latency",
                    "evidence": ["load test evidence"],
                }
            ],
        )
        self.assertGreater(score, 0.5)

    def test_relevance_alignment(self):
        score = relevance_alignment(
            query="cache latency",
            retrieved_items=[
                {"claim": "cache latency improved", "reasoning": "", "evidence": []},
                {"claim": "schema migration notes", "reasoning": "", "evidence": []},
            ],
            embedder=DummyEmbedder(),
        )
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)


if __name__ == "__main__":
    unittest.main()
