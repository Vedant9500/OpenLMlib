import unittest

from openlmlib.co_scientist import (
    RankingInputError,
    cluster_similar_hypotheses,
    evolve_hypothesis_packet,
    new_co_scientist_run_id,
    new_hypothesis_id,
    rank_hypotheses,
    score_hypothesis,
    validate_pairwise_comparison,
)


def packet(run_id, title, claim, score, hypothesis_id=None):
    return {
        "hypothesis_id": hypothesis_id or new_hypothesis_id(),
        "run_id": run_id,
        "title": title,
        "claim": claim,
        "rationale": f"{claim} because it improves the workflow under test.",
        "assumptions": ["The workflow remains artifact-first."],
        "evidence": [
            {
                "source": "test fixture",
                "summary": "Fixed evidence for deterministic ranking tests.",
                "supports": "claim",
                "confidence": score,
            }
        ],
        "citations": ["tests/test_co_scientist_ranking.py"],
        "novelty_score": score,
        "plausibility_score": score,
        "impact_score": score,
        "testability_score": score,
        "safety_notes": ["Read-only ranking test."],
        "lineage": {
            "parent_hypothesis_ids": [],
            "version": 1,
            "generated_by": "agent_ranker",
        },
        "status": "ranked",
    }


class TestCoScientistRanking(unittest.TestCase):
    def test_score_hypothesis_uses_phase_5_axes(self):
        run_id = new_co_scientist_run_id()
        item = packet(run_id, "Seven axis scoring", "Seven-axis scoring is deterministic", 0.8)

        score = score_hypothesis(item)

        self.assertIn("evidence_quality", score["axes"])
        self.assertIn("project_fit", score["axes"])
        self.assertIn("safety", score["axes"])
        self.assertGreater(score["base_score"], 0.0)

    def test_deterministic_ranking_from_fixed_comparisons(self):
        run_id = new_co_scientist_run_id()
        strong = packet(run_id, "Strong packet", "Strong packet has high base score", 0.9)
        middle = packet(run_id, "Middle packet", "Middle packet has moderate score", 0.7)
        weak = packet(run_id, "Weak packet", "Weak packet has low score", 0.3)
        comparisons = [
            {
                "hypothesis_a": middle["hypothesis_id"],
                "hypothesis_b": strong["hypothesis_id"],
                "winner": "hypothesis_a",
                "criteria": ["project_fit", "testability"],
                "rationale": "Middle packet is easier to test in this fixture.",
                "judge_agent": "agent_judge",
                "confidence": 0.9,
            },
            {
                "hypothesis_a": middle["hypothesis_id"],
                "hypothesis_b": weak["hypothesis_id"],
                "winner": "hypothesis_a",
                "criteria": ["evidence_quality"],
                "rationale": "Middle packet has better evidence.",
                "judge_agent": "agent_judge",
                "confidence": 0.8,
            },
        ]

        first = rank_hypotheses([strong, middle, weak], comparisons)
        second = rank_hypotheses([strong, middle, weak], comparisons)

        self.assertEqual(first, second)
        self.assertEqual(first["rankings"][0]["hypothesis_id"], middle["hypothesis_id"])
        self.assertEqual(first["comparison_count"], 2)

    def test_pairwise_comparison_validation_is_actionable(self):
        issues = validate_pairwise_comparison(
            {
                "hypothesis_a": "bad",
                "hypothesis_b": "bad",
                "winner": "unknown",
                "criteria": [],
                "rationale": "",
                "judge_agent": "",
                "confidence": 1.5,
            }
        )

        fields = {issue.field for issue in issues}
        self.assertIn("hypothesis_a", fields)
        self.assertIn("winner", fields)
        self.assertIn("confidence", fields)

    def test_unknown_comparison_ids_are_rejected(self):
        run_id = new_co_scientist_run_id()
        item = packet(run_id, "Known packet", "Known packet exists", 0.7)

        with self.assertRaises(RankingInputError) as raised:
            rank_hypotheses(
                [item],
                [
                    {
                        "hypothesis_a": item["hypothesis_id"],
                        "hypothesis_b": new_hypothesis_id(),
                        "winner": "hypothesis_a",
                        "criteria": ["novelty"],
                        "rationale": "Unknown opponent.",
                        "judge_agent": "agent_judge",
                        "confidence": 0.8,
                    }
                ],
            )

        self.assertTrue(any("hypothesis_b" in issue.field for issue in raised.exception.issues))

    def test_proximity_clustering_flags_similar_hypotheses(self):
        run_id = new_co_scientist_run_id()
        first = packet(
            run_id,
            "Artifact handoff validation",
            "Artifact handoff validation reduces transcript leakage",
            0.8,
        )
        second = packet(
            run_id,
            "Validate artifact handoffs",
            "Validating artifact handoffs reduces transcript leakage",
            0.7,
        )
        third = packet(
            run_id,
            "Vector index compaction",
            "Vector index compaction improves retrieval storage",
            0.6,
        )

        clustered = cluster_similar_hypotheses([first, second, third], threshold=0.35)

        near_duplicate_ids = {
            frozenset((edge["hypothesis_a"], edge["hypothesis_b"]))
            for edge in clustered["near_duplicates"]
        }
        self.assertIn(frozenset((first["hypothesis_id"], second["hypothesis_id"])), near_duplicate_ids)

    def test_evolved_hypothesis_preserves_parent_lineage(self):
        run_id = new_co_scientist_run_id()
        parent = packet(run_id, "Parent hypothesis", "Parent claim is plausible", 0.6)

        evolved = evolve_hypothesis_packet(
            parent,
            {
                "title": "Evolved hypothesis",
                "claim": "Evolved claim is more testable",
                "testability_score": 0.9,
            },
            generated_by="agent_evolver",
        )

        self.assertNotEqual(evolved["hypothesis_id"], parent["hypothesis_id"])
        self.assertEqual(evolved["run_id"], parent["run_id"])
        self.assertEqual(evolved["lineage"]["parent_hypothesis_ids"], [parent["hypothesis_id"]])
        self.assertEqual(evolved["lineage"]["version"], 2)
        self.assertEqual(evolved["lineage"]["generated_by"], "agent_evolver")
        self.assertEqual(evolved["status"], "ranked")


if __name__ == "__main__":
    unittest.main()
