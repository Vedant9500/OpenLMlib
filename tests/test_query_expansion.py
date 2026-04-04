import unittest

from openlmlib.query_expansion import (
    QueryExpander,
    _extract_keywords,
    _remove_modifiers,
    _add_qualifiers,
)


class TestExtractKeywords(unittest.TestCase):
    def test_basic_extraction(self):
        keywords = _extract_keywords("how to optimize API response time")
        self.assertIn("optimize", keywords)
        self.assertIn("api", keywords)
        self.assertIn("response", keywords)
        self.assertIn("time", keywords)
        # Stopwords should be excluded
        self.assertNotIn("to", keywords)
        self.assertNotIn("how", keywords)

    def test_empty_query(self):
        self.assertEqual(_extract_keywords(""), [])

    def test_short_tokens_filtered(self):
        keywords = _extract_keywords("a an the is")
        self.assertEqual(keywords, [])


class TestRemoveModifiers(unittest.TestCase):
    def test_remove_adverbs(self):
        result = _remove_modifiers("very fast API optimization")
        self.assertNotIn("very", result.lower())
        self.assertNotIn("fast", result.lower())

    def test_remove_quality_words(self):
        result = _remove_modifiers("best caching strategy")
        self.assertNotIn("best", result.lower())

    def test_no_modifiers(self):
        result = _remove_modifiers("database migration")
        self.assertEqual(result, "database migration")


class TestAddQualifiers(unittest.TestCase):
    def test_api_domain(self):
        result = _add_qualifiers("API response time")
        self.assertIn("performance", result.lower())
        self.assertIn("optimization", result.lower())

    def test_cache_domain(self):
        result = _add_qualifiers("Redis caching")
        self.assertIn("caching strategy", result.lower())

    def test_database_domain(self):
        result = _add_qualifiers("SQL migration")
        self.assertIn("database", result.lower())

    def test_unknown_domain(self):
        result = _add_qualifiers("general topic")
        self.assertEqual(result, "general topic")

    def test_does_not_match_substring_tokens(self):
        result = _add_qualifiers("apiary maintenance guide")
        self.assertEqual(result, "apiary maintenance guide")


class TestQueryExpander(unittest.TestCase):
    def test_expand_includes_original(self):
        expander = QueryExpander(max_variants=3, include_original=True)
        variants = expander.expand("API optimization")
        self.assertIn("API optimization", variants)
        # Original should be first
        self.assertEqual(variants[0], "API optimization")

    def test_expand_without_original(self):
        expander = QueryExpander(max_variants=2, include_original=False)
        variants = expander.expand("very fast API optimization")
        # The original query may still appear if no transformation removes all modifiers
        # Just verify we get some variants
        self.assertGreater(len(variants), 0)
        self.assertLessEqual(len(variants), 2)

    def test_expand_deduplicates(self):
        expander = QueryExpander(max_variants=5, include_original=True)
        variants = expander.expand("test")
        # Should not have duplicates
        self.assertEqual(len(variants), len(set(v.lower() for v in variants)))

    def test_expand_respects_max_variants(self):
        expander = QueryExpander(max_variants=1, include_original=True)
        variants = expander.expand("API optimization patterns")
        # Original + at most 1 variant
        self.assertLessEqual(len(variants), 2)

    def test_expand_and_retrieve(self):
        """Test expand_and_retrieve with a mock retrieve function."""
        expander = QueryExpander(max_variants=2, include_original=True)

        def mock_retrieve(query):
            if "api" in query.lower():
                return {"items": [{"id": "f1", "final_score": 0.9}]}
            return {"items": []}

        results = expander.expand_and_retrieve("API optimization", mock_retrieve, final_k=5)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], "f1")

    def test_expand_and_retrieve_deduplicates(self):
        """Test that expand_and_retrieve deduplicates by ID."""
        expander = QueryExpander(max_variants=3, include_original=True)

        def mock_retrieve(query):
            return {"items": [{"id": "f1", "final_score": 0.9, "variant": query}]}

        results = expander.expand_and_retrieve("test query", mock_retrieve, final_k=5)
        # Same ID should only appear once
        self.assertEqual(len(results), 1)


if __name__ == "__main__":
    unittest.main()
