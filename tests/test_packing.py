import unittest

from openlmlib.packing import ContextPacker, _interleave_ends, _estimate_tokens


class TestEstimateTokens(unittest.TestCase):
    def test_basic_estimation(self):
        item = {"claim": "Hello world", "reasoning": "This is a test"}
        # "Hello world" = 11 chars, "This is a test" = 16 chars = 27 chars total
        # 27 // 4 = 6 tokens (minimum 1)
        tokens = _estimate_tokens(item)
        self.assertGreater(tokens, 0)

    def test_empty_item(self):
        item = {}
        tokens = _estimate_tokens(item)
        self.assertEqual(tokens, 1)  # Minimum is 1

    def test_with_lists(self):
        item = {
            "claim": "Test",
            "evidence": ["evidence one", "evidence two"],
            "caveats": ["caveat one"],
        }
        tokens = _estimate_tokens(item)
        self.assertGreater(tokens, 0)


class TestInterleaveEnds(unittest.TestCase):
    def test_small_list_unchanged(self):
        items = [1, 2, 3]
        result = _interleave_ends(items)
        self.assertEqual(result, [1, 2, 3])

    def test_empty_list(self):
        self.assertEqual(_interleave_ends([]), [])

    def test_four_items(self):
        # [A, B, C, D] → [A, C, D, B] (A first, B last, C second, D second-to-last)
        items = ["A", "B", "C", "D"]
        result = _interleave_ends(items)
        # A goes to position 0, B goes to position 3, C goes to position 1, D goes to position 2
        self.assertEqual(result[0], "A")
        self.assertEqual(result[-1], "B")

    def test_six_items(self):
        items = [1, 2, 3, 4, 5, 6]
        result = _interleave_ends(items)
        # 1→0, 2→5, 3→1, 4→4, 5→2, 6→3
        self.assertEqual(result[0], 1)
        self.assertEqual(result[-1], 2)
        self.assertEqual(len(result), 6)

    def test_preserves_all_items(self):
        items = list(range(10))
        result = _interleave_ends(items)
        self.assertEqual(sorted(result), sorted(items))


class TestContextPacker(unittest.TestCase):
    def setUp(self):
        self.packer = ContextPacker(max_tokens=1000)

    def test_pack_empty(self):
        self.assertEqual(self.packer.pack([]), [])

    def test_pack_preserves_items(self):
        findings = [
            {"id": "f1", "claim": "Claim 1", "final_score": 0.9},
            {"id": "f2", "claim": "Claim 2", "final_score": 0.7},
        ]
        result = self.packer.pack(findings)
        self.assertEqual(len(result), 2)
        ids = [item["id"] for item in result]
        self.assertIn("f1", ids)
        self.assertIn("f2", ids)

    def test_pack_reorders_by_position(self):
        findings = [
            {"id": f"f{i}", "claim": f"Claim {i}", "final_score": 0.9 - i * 0.1}
            for i in range(6)
        ]
        result = self.packer.pack(findings)
        # Highest score item should be first
        self.assertEqual(result[0]["id"], "f0")

    def test_pack_trims_to_budget(self):
        # Create items that will exceed budget
        large_claim = "x" * 500  # ~125 tokens each
        findings = [
            {"id": f"f{i}", "claim": large_claim, "final_score": 0.9 - i * 0.1}
            for i in range(10)
        ]
        packer = ContextPacker(max_tokens=300)
        result = packer.pack(findings)
        # Should only fit a few items
        self.assertLess(len(result), 10)

    def test_render_context(self):
        findings = [
            {
                "id": "f1",
                "claim": "Redis caching works",
                "reasoning": "Tested in production",
                "evidence": ["load test"],
                "caveats": ["Needs Redis"],
                "final_score": 0.9,
            }
        ]
        context = self.packer.render_context(findings, include_scores=True)
        self.assertIn("Redis caching works", context)
        self.assertIn("Tested in production", context)
        self.assertIn("load test", context)
        self.assertIn("Needs Redis", context)
        self.assertIn("0.9", context)

    def test_render_context_without_scores(self):
        findings = [{"id": "f1", "claim": "Test claim"}]
        context = self.packer.render_context(findings, include_scores=False)
        self.assertNotIn("score", context.lower())

    def test_custom_token_estimator(self):
        def always_100(item):
            return 100

        packer = ContextPacker(max_tokens=250, token_estimate_fn=always_100)
        findings = [{"id": f"f{i}"} for i in range(5)]
        result = packer.pack(findings)
        # 250 / 100 = 2 items fit
        self.assertEqual(len(result), 2)


if __name__ == "__main__":
    unittest.main()
