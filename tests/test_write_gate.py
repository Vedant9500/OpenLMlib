import unittest

from openlmlib.write_gate import WriteGate
from openlmlib.schema import ValidationIssue


class FixedEmbedder:
    def encode(self, texts):
        return [[1.0, 0.0] for _ in texts]


class SplitEmbedder:
    def encode(self, texts):
        vectors = []
        for text in texts:
            if "evidence" in text:
                vectors.append([0.0, 1.0])
            else:
                vectors.append([1.0, 0.0])
        return vectors


class SimpleVectorStore:
    dim = 2

    def count(self):
        return 1

    def search(self, vec, top_k):
        return [(101, 0.91)]


class TestWriteGate(unittest.TestCase):
    def test_rejects_low_confidence(self):
        gate = WriteGate(
            min_confidence=0.6,
            min_reasoning_length=10,
            min_claim_evidence_sim=0.7,
            novelty_similarity_threshold=0.85,
            novelty_top_k=5,
            embedder=FixedEmbedder(),
        )
        issues = gate.validate("claim", ["evidence"], "reasoning text", 0.5)
        self.assertFalse(gate.is_allowed(issues))

    def test_rejects_low_similarity(self):
        gate = WriteGate(
            min_confidence=0.6,
            min_reasoning_length=10,
            min_claim_evidence_sim=0.7,
            novelty_similarity_threshold=0.85,
            novelty_top_k=5,
            embedder=SplitEmbedder(),
        )
        issues = gate.validate("claim", ["evidence"], "reasoning text", 0.7)
        self.assertFalse(gate.is_allowed(issues))

    def test_accepts_valid(self):
        gate = WriteGate(
            min_confidence=0.6,
            min_reasoning_length=10,
            min_claim_evidence_sim=0.7,
            novelty_similarity_threshold=0.85,
            novelty_top_k=5,
            embedder=FixedEmbedder(),
        )
        issues = gate.validate("claim", ["evidence"], "reasoning text", 0.9)
        self.assertTrue(gate.is_allowed(issues))

    def test_flags_potential_contradiction(self):
        gate = WriteGate(
            min_confidence=0.6,
            min_reasoning_length=10,
            min_claim_evidence_sim=0.7,
            novelty_similarity_threshold=0.85,
            novelty_top_k=5,
            embedder=FixedEmbedder(),
            vector_store=SimpleVectorStore(),
            finding_lookup=lambda embedding_id: {
                "id": "f-1",
                "claim": "Redis caching does not reduce API latency under production load",
            },
        )

        issues = gate.validate(
            "Redis caching reduces API latency under production load",
            ["evidence"],
            "reasoning text",
            0.9,
        )
        contradiction_issues = [issue for issue in issues if issue.field == "contradiction"]
        self.assertTrue(contradiction_issues)
        self.assertTrue(gate.is_allowed(issues))

    def test_adjusts_confidence_down_for_warnings(self):
        gate = WriteGate(
            min_confidence=0.6,
            min_reasoning_length=10,
            min_claim_evidence_sim=0.7,
            novelty_similarity_threshold=0.85,
            novelty_top_k=5,
            embedder=FixedEmbedder(),
        )
        adjusted = gate.adjust_confidence(
            claim="claim",
            evidence=["evidence"],
            proposed_confidence=0.9,
            issues=[ValidationIssue(field="novelty", message="similar", severity="warning")],
        )
        self.assertLess(adjusted, 0.9)


if __name__ == "__main__":
    unittest.main()
