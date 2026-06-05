import unittest

from openlmlib.co_scientist import (
    HYPOTHESIS_ID_RE,
    RUN_ID_RE,
    HypothesisPacket,
    get_hypothesis_packet_schema,
    new_co_scientist_run_id,
    new_hypothesis_id,
    validate_hypothesis_packet,
)
from openlmlib.collab.collab_mcp import (
    get_hypothesis_packet_schema as mcp_get_hypothesis_packet_schema,
    validate_hypothesis_packet as mcp_validate_hypothesis_packet,
)


def valid_packet():
    return {
        "hypothesis_id": new_hypothesis_id(),
        "run_id": new_co_scientist_run_id(),
        "title": "Artifact-first hypothesis packets",
        "claim": "Structured packets reduce generator-verifier context leakage.",
        "rationale": (
            "A fixed packet boundary gives verifiers only the claim, evidence, "
            "assumptions, citations, and lineage they need."
        ),
        "assumptions": [
            "Verification agents should not need the full generation transcript.",
        ],
        "evidence": [
            {
                "source": "docs/CO_SCIENTIST_PHASE_PLAN.md",
                "summary": "The phase plan requires explicit citations and assumptions.",
                "supports": "claim",
                "confidence": 0.86,
            }
        ],
        "citations": ["docs/CO_SCIENTIST_PHASE_PLAN.md"],
        "novelty_score": 0.6,
        "plausibility_score": 0.8,
        "impact_score": 0.7,
        "testability_score": 0.9,
        "safety_notes": ["Read-only workflow boundary."],
        "lineage": {
            "parent_hypothesis_ids": [],
            "version": 1,
            "generated_by": "agent_research_scout",
        },
        "status": "draft",
    }


class TestCoScientistHypothesisPacket(unittest.TestCase):
    def test_generated_ids_match_schema_formats(self):
        self.assertRegex(new_hypothesis_id(), HYPOTHESIS_ID_RE)
        self.assertRegex(new_co_scientist_run_id(), RUN_ID_RE)

    def test_schema_lists_required_phase_1_fields(self):
        schema = get_hypothesis_packet_schema()

        self.assertEqual(schema["type"], "object")
        for field in (
            "hypothesis_id",
            "run_id",
            "claim",
            "rationale",
            "assumptions",
            "evidence",
            "citations",
            "lineage",
            "status",
        ):
            self.assertIn(field, schema["required"])

    def test_valid_packet_has_no_validation_issues(self):
        self.assertEqual(validate_hypothesis_packet(valid_packet()), [])

    def test_missing_required_fields_are_actionable(self):
        packet = valid_packet()
        del packet["citations"]
        del packet["lineage"]

        issues = validate_hypothesis_packet(packet)
        fields = {issue.field for issue in issues}

        self.assertIn("citations", fields)
        self.assertIn("lineage", fields)
        self.assertTrue(all(issue.message for issue in issues))

    def test_requires_evidence_and_citations(self):
        packet = valid_packet()
        packet["evidence"] = []
        packet["citations"] = []

        issues = validate_hypothesis_packet(packet)
        fields = {issue.field for issue in issues}

        self.assertIn("evidence", fields)
        self.assertIn("citations", fields)

    def test_rejects_invalid_scores_and_boolean_numbers(self):
        packet = valid_packet()
        packet["novelty_score"] = 1.2
        packet["plausibility_score"] = True
        packet["evidence"][0]["confidence"] = -0.1

        issues = validate_hypothesis_packet(packet)
        fields = {issue.field for issue in issues}

        self.assertIn("novelty_score", fields)
        self.assertIn("plausibility_score", fields)
        self.assertIn("evidence[0].confidence", fields)

    def test_validates_lineage_parent_ids_and_version(self):
        packet = valid_packet()
        packet["lineage"]["parent_hypothesis_ids"] = ["bad-parent"]
        packet["lineage"]["version"] = 0

        issues = validate_hypothesis_packet(packet)
        fields = {issue.field for issue in issues}

        self.assertIn("lineage.parent_hypothesis_ids[0]", fields)
        self.assertIn("lineage.version", fields)

    def test_dataclass_roundtrip_preserves_lineage(self):
        packet = valid_packet()
        parent_id = new_hypothesis_id()
        packet["lineage"]["parent_hypothesis_ids"] = [parent_id]
        packet["lineage"]["version"] = 2
        packet["status"] = "ranked"

        parsed = HypothesisPacket.from_dict(packet)
        serialized = parsed.to_dict()

        self.assertEqual(serialized["lineage"]["parent_hypothesis_ids"], [parent_id])
        self.assertEqual(serialized["lineage"]["version"], 2)
        self.assertEqual(serialized["status"], "ranked")

    def test_dataclass_from_dict_rejects_invalid_payload(self):
        packet = valid_packet()
        packet["hypothesis_id"] = "hyp_bad"

        with self.assertRaises(ValueError) as raised:
            HypothesisPacket.from_dict(packet)

        self.assertIn("hypothesis_id", str(raised.exception))

    def test_mcp_adapters_return_schema_and_validation_results(self):
        schema = mcp_get_hypothesis_packet_schema()
        valid_result = mcp_validate_hypothesis_packet(valid_packet())
        invalid = valid_packet()
        invalid["status"] = "unknown"
        invalid_result = mcp_validate_hypothesis_packet(invalid)

        self.assertIn("required", schema)
        self.assertTrue(valid_result["valid"])
        self.assertEqual(valid_result["issue_count"], 0)
        self.assertFalse(invalid_result["valid"])
        self.assertEqual(invalid_result["issues"][0]["field"], "status")


if __name__ == "__main__":
    unittest.main()
