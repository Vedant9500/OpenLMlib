import unittest

from openlmlib.library import _check_duplicate_warning


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


if __name__ == "__main__":
    unittest.main()
