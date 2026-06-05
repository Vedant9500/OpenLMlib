import json
import os
import tempfile
import unittest
from pathlib import Path

from openlmlib.co_scientist import (
    CO_SCIENTIST_GENERATE_TEMPLATE,
    CO_SCIENTIST_VERIFY_TEMPLATE,
    VERIFICATION_CONFIDENCE_RULES,
    VERIFICATION_VERDICTS,
    new_co_scientist_run_id,
    new_hypothesis_id,
    validate_hypothesis_packet,
)
from openlmlib.collab.artifact_store import ArtifactStore
from openlmlib.collab.db import (
    connect_collab_db,
    get_session,
    get_session_artifacts,
    get_session_tasks,
)
from openlmlib.collab.templates import get_template, list_templates


def valid_shortlist_packet():
    return {
        "hypothesis_id": new_hypothesis_id(),
        "run_id": new_co_scientist_run_id(),
        "title": "Template-driven hypothesis shortlist",
        "claim": "A fixed generation template improves verifier handoff quality.",
        "rationale": (
            "The generation template requires explicit artifacts, packet schema "
            "usage, validation, and lineage before verification."
        ),
        "assumptions": [
            "Agents follow template task instructions before sending the shortlist.",
        ],
        "evidence": [
            {
                "source": "co_scientist_generate template",
                "summary": "The template requires schema validation and a shortlist artifact.",
                "supports": "claim",
                "confidence": 0.8,
            }
        ],
        "citations": ["openlmlib/co_scientist/templates.py"],
        "novelty_score": 0.5,
        "plausibility_score": 0.8,
        "impact_score": 0.7,
        "testability_score": 0.9,
        "safety_notes": ["Read-only generation workflow."],
        "lineage": {
            "parent_hypothesis_ids": [],
            "version": 1,
            "generated_by": "agent_ranker",
        },
        "status": "ranked",
    }


class TestCoScientistGenerationTemplate(unittest.TestCase):
    def test_generation_template_is_listed(self):
        templates = list_templates()
        template_ids = {template["template_id"] for template in templates}

        self.assertIn("co_scientist_generate", template_ids)

    def test_generation_template_has_phase_2_contract(self):
        template = get_template("co_scientist_generate")

        self.assertIsNotNone(template)
        self.assertEqual(template["name"], "Co-Scientist Hypothesis Generation")
        self.assertEqual(template["source"], "built-in")
        self.assertEqual(len(template["plan"]), 6)
        self.assertEqual(template["rules"]["co_scientist_phase"], "generation")
        self.assertTrue(template["rules"]["require_artifact_for_results"])
        self.assertIn("hypothesis_shortlist", template["rules"]["expected_artifacts"])
        self.assertIn(
            "validate_hypothesis_packet before shortlist handoff",
            template["rules"]["required_gates"],
        )

        for task in template["plan"]:
            self.assertIn("step", task)
            self.assertIn("task", task)
            self.assertIn("assigned_to", task)
            self.assertTrue(task["task"])

    def test_template_mentions_required_generation_roles(self):
        task_text = "\n".join(task["task"] for task in CO_SCIENTIST_GENERATE_TEMPLATE["plan"])

        for role in (
            "Research Scout",
            "Hypothesis Generator",
            "Reflection Critic",
            "Proximity/Dedup Agent",
            "Evolution Agent",
            "Ranker/Meta-reviewer",
        ):
            self.assertIn(role, task_text)

    def test_shortlist_packet_contract_can_pass_validation(self):
        self.assertEqual(validate_hypothesis_packet(valid_shortlist_packet()), [])


class TestCoScientistVerificationTemplate(unittest.TestCase):
    def test_verification_template_is_listed(self):
        templates = list_templates()
        template_ids = {template["template_id"] for template in templates}

        self.assertIn("co_scientist_verify", template_ids)

    def test_verification_template_has_phase_3_contract(self):
        template = get_template("co_scientist_verify")

        self.assertIsNotNone(template)
        self.assertEqual(template["name"], "Co-Scientist Hypothesis Verification")
        self.assertEqual(template["source"], "built-in")
        self.assertEqual(len(template["plan"]), 5)
        self.assertEqual(template["rules"]["co_scientist_phase"], "verification")
        self.assertTrue(template["rules"]["require_artifact_for_results"])
        self.assertIn("hypothesis_shortlist", template["rules"]["expected_input_artifacts"])
        self.assertIn("verification_report", template["rules"]["expected_artifacts"])
        self.assertEqual(
            template["rules"]["artifact_cardinality"]["verification_report"],
            "one artifact per input hypothesis_id",
        )
        self.assertEqual(
            set(template["rules"]["verification_verdicts"]),
            set(VERIFICATION_VERDICTS),
        )
        self.assertIn("disconfirming_evidence", template["rules"]["required_report_fields"])

    def test_verification_template_mentions_required_roles(self):
        task_text = "\n".join(task["task"] for task in CO_SCIENTIST_VERIFY_TEMPLATE["plan"])

        for role in (
            "Evidence Verifier",
            "Contradiction Hunter",
            "Reproduction/Test Designer",
            "Feasibility Reviewer",
            "Final Adjudicator",
        ):
            self.assertIn(role, task_text)

    def test_verification_verdicts_and_confidence_rules_are_defined(self):
        self.assertEqual(
            set(VERIFICATION_VERDICTS),
            {
                "supported",
                "partially_supported",
                "inconclusive",
                "contradicted",
                "unsafe_or_out_of_scope",
            },
        )
        self.assertEqual(VERIFICATION_CONFIDENCE_RULES["range"], "0.0 to 1.0")
        self.assertIn("requirements", VERIFICATION_CONFIDENCE_RULES)
        self.assertIn(
            "Disconfirming evidence must be listed even when the verdict is supported.",
            VERIFICATION_CONFIDENCE_RULES["requirements"],
        )


class TestCoScientistGenerationTemplateMCP(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.tmp.name) / "config" / "settings.json"
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.data_root = Path(self.tmp.name) / "data"
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(
            json.dumps({"data_root": str(self.data_root)}),
            encoding="utf-8",
        )
        self.prev_settings = os.environ.get("OPENLMLIB_SETTINGS")
        os.environ["OPENLMLIB_SETTINGS"] = str(self.settings_path)

        import openlmlib.collab.collab_mcp as collab_mcp_module
        import openlmlib.collab.templates as templates_module

        collab_mcp_module._cached_paths = None
        collab_mcp_module._cached_paths_mtime = 0.0
        templates_module._custom_templates_dir = None
        templates_module._clear_template_cache()
        self.collab_mcp_module = collab_mcp_module

    def tearDown(self):
        from openlmlib.collab.db import close_thread_connections

        close_thread_connections()
        if self.prev_settings is None:
            os.environ.pop("OPENLMLIB_SETTINGS", None)
        else:
            os.environ["OPENLMLIB_SETTINGS"] = self.prev_settings
        self.tmp.cleanup()

    def test_create_from_generation_template_creates_all_tasks(self):
        result = self.collab_mcp_module.create_from_template(
            template_id="co_scientist_generate",
            title="Generate OpenLMlib hypotheses",
            task_description="Generate and rank safe implementation hypotheses.",
            created_by="orchestrator-model",
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["template"], "co_scientist_generate")
        self.assertEqual(result["plan_steps"], 6)

        db_path, _ = self.collab_mcp_module._get_collab_paths()
        conn = connect_collab_db(db_path)
        try:
            session = get_session(conn, result["session_id"])
            tasks = get_session_tasks(conn, result["session_id"])
        finally:
            conn.close()

        self.assertEqual(session["rules"]["co_scientist_phase"], "generation")
        self.assertIn("hypothesis_shortlist", session["rules"]["expected_artifacts"])
        self.assertEqual(len(tasks), 6)
        self.assertTrue(
            any("hypothesis_shortlist" in task["description"] for task in tasks)
        )

    def test_create_from_verification_template_creates_all_tasks(self):
        result = self.collab_mcp_module.create_from_template(
            template_id="co_scientist_verify",
            title="Verify OpenLMlib hypotheses",
            task_description="Verify ranked hypothesis packets independently.",
            created_by="orchestrator-model",
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["template"], "co_scientist_verify")
        self.assertEqual(result["plan_steps"], 5)

        db_path, _ = self.collab_mcp_module._get_collab_paths()
        conn = connect_collab_db(db_path)
        try:
            session = get_session(conn, result["session_id"])
            tasks = get_session_tasks(conn, result["session_id"])
        finally:
            conn.close()

        self.assertEqual(session["rules"]["co_scientist_phase"], "verification")
        self.assertIn("verification_report", session["rules"]["expected_artifacts"])
        self.assertEqual(len(tasks), 5)
        self.assertTrue(
            any("verification_report" in task["description"] for task in tasks)
        )

    def test_verification_report_artifact_cardinality_can_be_satisfied(self):
        result = self.collab_mcp_module.create_from_template(
            template_id="co_scientist_verify",
            title="Verify two hypotheses",
            task_description="Verify two ranked hypothesis packets independently.",
            created_by="orchestrator-model",
        )
        hypothesis_ids = [new_hypothesis_id(), new_hypothesis_id()]

        db_path, sessions_dir = self.collab_mcp_module._get_collab_paths()
        from openlmlib.collab.db import close_thread_connections

        close_thread_connections()
        conn = connect_collab_db(db_path)
        try:
            store = ArtifactStore(conn, sessions_dir)
            for hypothesis_id in hypothesis_ids:
                store.save(
                    session_id=result["session_id"],
                    created_by=result["your_agent_id"],
                    title=f"Verification Report {hypothesis_id}",
                    content=(
                        f"# Verification Report\n\n"
                        f"hypothesis_id: {hypothesis_id}\n"
                        f"verdict: inconclusive\n"
                        f"confidence: 0.5\n"
                        f"supporting_evidence:\n- Pending\n"
                        f"disconfirming_evidence:\n- None found yet\n"
                        f"citations:\n- test fixture\n"
                    ),
                    created_at="2026-06-05T12:00:00Z",
                    artifact_type="verification_report",
                    tags=["co_scientist", f"hypothesis_id:{hypothesis_id}"],
                    shared=True,
                )

            artifacts = get_session_artifacts(conn, result["session_id"])
        finally:
            conn.close()

        verification_reports = [
            artifact
            for artifact in artifacts
            if artifact["artifact_type"] == "verification_report"
        ]
        report_tags = {tag for artifact in verification_reports for tag in artifact["tags"]}

        self.assertEqual(len(verification_reports), len(hypothesis_ids))
        for hypothesis_id in hypothesis_ids:
            self.assertIn(f"hypothesis_id:{hypothesis_id}", report_tags)


if __name__ == "__main__":
    unittest.main()
