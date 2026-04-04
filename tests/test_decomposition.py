import unittest

from openlmlib.decomposition import DocumentDecomposer, DecomposedFinding, _component_relevance


class TestComponentRelevance(unittest.TestCase):
    def test_exact_match(self):
        score = _component_relevance("Redis caching", "Redis caching improves performance")
        self.assertGreater(score, 0.5)

    def test_no_overlap(self):
        score = _component_relevance("database migration", "frontend CSS styling")
        self.assertEqual(score, 0.0)

    def test_partial_overlap(self):
        score = _component_relevance("API latency", "API response time optimization")
        self.assertGreater(score, 0.0)

    def test_empty_inputs(self):
        self.assertEqual(_component_relevance("", "some text"), 0.0)
        self.assertEqual(_component_relevance("query", ""), 0.0)
        self.assertEqual(_component_relevance("", ""), 0.0)


class TestDocumentDecomposer(unittest.TestCase):
    def setUp(self):
        self.decomposer = DocumentDecomposer(
            min_relevance_threshold=0.3,
            include_caveats=True,
            max_evidence_items=3,
        )

    def test_decompose_basic(self):
        finding = {
            "id": "fnd-001",
            "claim": "Redis caching reduces API latency by 40%",
            "evidence": ["load test results", "perf comparison", "irrelevant data about UI"],
            "reasoning": "Tested in production with measurable improvement",
            "caveats": ["Requires distributed setup", "Only works for read-heavy workloads"],
        }
        result = self.decomposer.decompose(finding, "Redis caching API latency")

        self.assertEqual(result.id, "fnd-001")
        self.assertEqual(result.claim, finding["claim"])
        self.assertFalse(result.filtered)
        self.assertGreater(result.relevance_score, 0.0)

    def test_decompose_filters_irrelevant_evidence(self):
        finding = {
            "id": "fnd-002",
            "claim": "Database migration best practices",
            "evidence": ["migration test results", "completely unrelated UI testing data"],
            "reasoning": "Validated across multiple environments",
            "caveats": [],
        }
        result = self.decomposer.decompose(finding, "database migration")

        # Evidence about UI should be filtered out
        evidence = result.evidence
        for ev in evidence:
            self.assertNotIn("UI", ev)

    def test_decompose_caps_evidence_items(self):
        finding = {
            "id": "fnd-003",
            "claim": "Test claim",
            "evidence": ["ev1", "ev2", "ev3", "ev4", "ev5"],
            "reasoning": "Test reasoning",
            "caveats": [],
        }
        decomposer = DocumentDecomposer(max_evidence_items=2)
        result = decomposer.decompose(finding, "test")

        self.assertLessEqual(len(result.evidence), 2)

    def test_decompose_filters_low_relevance_finding(self):
        finding = {
            "id": "fnd-004",
            "claim": "Frontend CSS styling patterns",
            "evidence": ["CSS test"],
            "reasoning": "UI related reasoning",
            "caveats": [],
        }
        result = self.decomposer.decompose(finding, "database migration SQL")

        # Should be filtered due to low relevance
        self.assertTrue(result.filtered)
        self.assertEqual(result.filter_reason, "low_relevance")

    def test_decompose_many(self):
        findings = [
            {
                "id": "f1",
                "claim": "Redis caching",
                "evidence": ["test"],
                "reasoning": "reasoning",
                "caveats": [],
            },
            {
                "id": "f2",
                "claim": "Database migration",
                "evidence": ["test"],
                "reasoning": "reasoning",
                "caveats": [],
            },
        ]
        results = self.decomposer.decompose_many(findings, "Redis caching")
        self.assertEqual(len(results), 2)

    def test_recompose_filters_out_decomposed(self):
        decomposed = [
            DecomposedFinding(
                id="f1",
                claim="Relevant claim",
                evidence=["evidence"],
                reasoning="reasoning",
                caveats=[],
                relevance_score=0.8,
                filtered=False,
            ),
            DecomposedFinding(
                id="f2",
                claim="Irrelevant claim",
                evidence=[],
                reasoning="",
                caveats=[],
                relevance_score=0.1,
                filtered=True,
                filter_reason="low_relevance",
            ),
        ]
        recomposed = self.decomposer.recompose(decomposed, max_findings=5)
        self.assertEqual(len(recomposed), 1)
        self.assertEqual(recomposed[0]["id"], "f1")

    def test_recompose_respects_max_findings(self):
        decomposed = [
            DecomposedFinding(id=f"f{i}", claim=f"Claim {i}", evidence=[], reasoning="", caveats=[], relevance_score=0.9 - i * 0.1)
            for i in range(10)
        ]
        recomposed = self.decomposer.recompose(decomposed, max_findings=3)
        self.assertEqual(len(recomposed), 3)

    def test_decompose_and_recompose_pipeline(self):
        findings = [
            {
                "id": "f1",
                "claim": "Redis caching improves API performance",
                "evidence": ["load test"],
                "reasoning": "40% improvement observed",
                "caveats": ["Requires Redis"],
                "project": "glassbox",
                "confidence": 0.9,
                "created_at": "2026-04-01T00:00:00Z",
                "pending_review": False,
            },
            {
                "id": "f2",
                "claim": "CSS grid layout techniques",
                "evidence": ["browser test"],
                "reasoning": "Works in modern browsers",
                "caveats": [],
            },
        ]
        result = self.decomposer.decompose_and_recompose(findings, "Redis caching API", max_findings=5)
        # f1 should be included, f2 should be filtered
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "f1")
        # Metadata needed by downstream retrieval trace should be preserved.
        self.assertEqual(result[0]["project"], "glassbox")
        self.assertEqual(result[0]["confidence"], 0.9)
        self.assertIn("pending_review", result[0])

    def test_decompose_excludes_caveats_when_disabled(self):
        finding = {
            "id": "f1",
            "claim": "Test claim",
            "evidence": ["evidence"],
            "reasoning": "reasoning",
            "caveats": ["important caveat"],
        }
        decomposer = DocumentDecomposer(include_caveats=False)
        result = decomposer.decompose(finding, "test")
        self.assertEqual(result.caveats, [])


if __name__ == "__main__":
    unittest.main()
