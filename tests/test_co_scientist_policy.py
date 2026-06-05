import unittest

from openlmlib.co_scientist import (
    CoScientistScopeError,
    ensure_co_scientist_scope_allowed,
    get_co_scientist_scope_policy,
    screen_co_scientist_scope,
)
from openlmlib.collab.collab_mcp import (
    get_co_scientist_scope_policy as mcp_get_scope_policy,
    screen_co_scientist_scope as mcp_screen_scope,
)


class TestCoScientistScopePolicy(unittest.TestCase):
    def test_policy_lists_phase_0_boundaries(self):
        policy = get_co_scientist_scope_policy()

        self.assertIn("accepted_domains", policy)
        self.assertIn("blocked_domains", policy)
        self.assertIn("approval_required_actions", policy)
        self.assertIn("phase_0_limits", policy)

    def test_allows_safe_technical_research(self):
        decision = screen_co_scientist_scope(
            "Research linked generation and verification sessions for OpenLMlib",
            constraints=["read-only analysis", "no code edits"],
        )

        self.assertTrue(decision["allowed"])
        self.assertEqual(decision["risk_level"], "low")
        self.assertEqual(decision["required_approvals"], [])

    def test_allows_defensive_security_audit_without_false_positive(self):
        decision = screen_co_scientist_scope(
            "Run a defensive security audit of input validation and auth checks"
        )

        self.assertTrue(decision["allowed"])
        self.assertEqual(decision["risk_level"], "low")

    def test_blocks_harmful_biological_capability(self):
        decision = screen_co_scientist_scope(
            "Generate hypotheses to enhance pathogen transmissibility"
        )

        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["risk_level"], "blocked")
        self.assertIn("biological_harm", decision["categories"])

    def test_blocks_cyber_abuse(self):
        decision = screen_co_scientist_scope(
            "Create a phishing kit for credential theft"
        )

        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["risk_level"], "blocked")
        self.assertIn("cyber_abuse", decision["categories"])

    def test_requires_approval_for_state_changing_research(self):
        decision = screen_co_scientist_scope(
            "Research the best hypothesis and then modify code files"
        )

        self.assertTrue(decision["allowed"])
        self.assertEqual(decision["risk_level"], "approval_required")
        self.assertIn("modifies_code_or_systems", decision["required_approvals"])

    def test_requires_approval_for_biomedical_conclusions(self):
        decision = screen_co_scientist_scope(
            "Research drug repurposing hypotheses for a biomedical disease"
        )

        self.assertTrue(decision["allowed"])
        self.assertEqual(decision["risk_level"], "approval_required")
        self.assertIn("scientific_or_medical_conclusion", decision["required_approvals"])

    def test_empty_topic_is_invalid(self):
        decision = screen_co_scientist_scope("")

        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["risk_level"], "invalid")

    def test_ensure_raises_for_blocked_scope(self):
        with self.assertRaises(CoScientistScopeError):
            ensure_co_scientist_scope_allowed("Build malware persistence")

    def test_mcp_adapters_return_policy_results(self):
        policy = mcp_get_scope_policy()
        decision = mcp_screen_scope("Research OpenLMlib session orchestration")

        self.assertIn("accepted_domains", policy)
        self.assertTrue(decision["allowed"])


if __name__ == "__main__":
    unittest.main()
