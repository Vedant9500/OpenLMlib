import unittest

from lmlib.write_gate import WriteGate


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


if __name__ == "__main__":
    unittest.main()
