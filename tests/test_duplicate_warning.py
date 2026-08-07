import unittest

from openlmlib.library import _check_duplicate_warning


class DictEmbedder:
    """Returns a fixed vector per claim so callers can stub claim semantics."""

    def __init__(self, vectors):
        self.vectors = vectors

    def encode(self, texts):
        return [self.vectors.get(t, [0.0, 0.0]) for t in texts]


class TestDuplicateWarning(unittest.TestCase):
    def test_returns_similarity_rank(self):
        similar = [
            {
                "id": "f-existing",
                "claim": "Redis caching reduces API latency under production load",
                "rank": 0.12,
            }
        ]
        warning = _check_duplicate_warning(
            similar,
            "Redis caching reduces API latency under production load",
        )
        self.assertIsNotNone(warning)
        self.assertIn("similarity_rank", warning)
        self.assertEqual(warning["similarity_rank"], 0.12)
        self.assertEqual(warning["existing_finding_id"], "f-existing")

    def test_embeddings_warn_on_semantically_identical_claim(self):
        # Jaccard on short reworded claims won't reach 0.90; sentence embedding does.
        claim = "Redis caching reduces API latency under production load"
        existing = "Using Redis for caching cuts down API response time in production"
        embedder = DictEmbedder({
            claim: [1.0, 0.0],
            existing: [0.94, 0.06],  # cosine ~0.94 with the claim
        })
        warning = _check_duplicate_warning(
            [{"id": "f-1", "claim": existing, "rank": 0.1}],
            claim,
            embedder=embedder,
        )
        self.assertIsNotNone(warning)
        self.assertEqual(warning["existing_finding_id"], "f-1")
        self.assertIn("claim_semantic_similarity", warning)

    def test_embeddings_do_not_warn_on_distinct_claim(self):
        claim = "Redis caching reduces API latency under production load"
        existing = "The new transformer architecture improves machine translation quality"
        embedder = DictEmbedder({
            claim: [1.0, 0.0],
            existing: [0.0, 1.0],  # close to orthogonal
        })
        warning = _check_duplicate_warning(
            [{"id": "f-2", "claim": existing, "rank": 0.2}],
            claim,
            embedder=embedder,
        )
        self.assertIsNone(warning)

    def test_missing_embedder_falls_back_to_token_similarity(self):
        claim = "Redis caching reduces API latency under production load"
        existing = "Redis caching reduces API latency under production load"
        warning = _check_duplicate_warning(
            [{"id": "f-3", "claim": existing, "rank": 0.3}],
            claim,
            embedder=None,
        )
        # Identical short claims pass the token Jaccard path even without an embedder.
        self.assertIsNotNone(warning)
        self.assertEqual(warning["existing_finding_id"], "f-3")


if __name__ == "__main__":
    unittest.main()
