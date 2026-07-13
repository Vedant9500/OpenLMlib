import tempfile
import unittest
from pathlib import Path

from openlmlib.collab.db import connect_collab_db, init_collab_db
from openlmlib.co_scientist.evaluation import (
    compare_workflows,
    evaluate_run,
    evaluate_workflow_result,
    get_benchmark_tasks,
)
from openlmlib.co_scientist.orchestrator import (
    create_co_scientist_run,
    start_hypothesis_verification,
    submit_hypothesis,
    submit_verification,
)
from openlmlib.co_scientist.reporting import create_final_report
from tests.test_co_scientist_reporting import packet, report


class TestCoScientistEvaluation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.sessions_dir = self.root / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.conn = connect_collab_db(self.root / "collab_sessions.db")
        init_collab_db(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_benchmark_tasks_are_fixed_and_actionable(self):
        tasks = get_benchmark_tasks()

        self.assertEqual(tasks["count"], 3)
        self.assertIn("two_session_co_scientist", tasks["workflow_types"])
        self.assertTrue(all(item["success_criteria"] for item in tasks["tasks"]))

    def test_evaluate_run_returns_phase_9_metrics(self):
        run = create_co_scientist_run(
            self.conn,
            self.sessions_dir,
            topic="Research evaluation metrics",
            top_k=1,
        )
        item = packet(run["run_id"], "Evaluation packet")
        gen = run["generation_agent_id"]
        ver = run["verification_agent_id"]
        submit_hypothesis(self.conn, self.sessions_dir, run["run_id"], item, created_by=gen)
        start_hypothesis_verification(
            self.conn,
            self.sessions_dir,
            run["run_id"],
            hypothesis_ids=[item["hypothesis_id"]],
            created_by=gen,
        )
        submit_verification(
            self.conn,
            self.sessions_dir,
            run["run_id"],
            item["hypothesis_id"],
            report(item["hypothesis_id"], "supported", 0.88),
            created_by=ver,
        )
        create_final_report(self.conn, self.sessions_dir, run["run_id"], created_by=ver)

        result = evaluate_run(
            self.conn,
            run["run_id"],
            token_count=1200,
            cost_usd=0.6,
            human_edits_needed=1,
            expert_accepted=True,
        )

        self.assertEqual(result["workflow_type"], "two_session_co_scientist")
        self.assertEqual(result["metrics"]["verified_hypothesis_count"], 1)
        self.assertEqual(result["metrics"]["token_cost_per_verified_hypothesis"], 1200.0)
        self.assertEqual(result["metrics"]["usd_cost_per_verified_hypothesis"], 0.6)
        self.assertGreater(result["traceability_score"], 0.0)
        self.assertGreater(result["quality_score"], 0.0)

    def test_evaluate_workflow_result_normalizes_manual_benchmark_row(self):
        result = evaluate_workflow_result(
            {
                "task_id": "fixture",
                "workflow_type": "single_agent",
                "total_hypotheses": 4,
                "valid_hypotheses": 3,
                "verified_hypotheses": 1,
                "rejected_hallucinations": 1,
                "citations": 6,
                "citation_slots": 8,
                "contradictions_found": 1,
                "selected_hypotheses": 2,
                "artifact_quality": 0.5,
                "citation_quality": 0.7,
                "expert_accepted": False,
            }
        )

        self.assertEqual(result["metrics"]["valid_hypothesis_rate"], 0.75)
        self.assertEqual(result["metrics"]["citation_coverage"], 0.75)
        self.assertEqual(result["workflow_type"], "single_agent")

    def test_compare_workflows_recommends_simpler_default_without_clear_gain(self):
        comparison = compare_workflows(
            [
                {
                    "task_id": "fixture",
                    "workflow_type": "single_agent",
                    "total_hypotheses": 4,
                    "valid_hypotheses": 3,
                    "verified_hypotheses": 1,
                    "citations": 6,
                    "citation_slots": 8,
                    "contradictions_found": 1,
                    "selected_hypotheses": 2,
                    "artifact_quality": 0.7,
                    "citation_quality": 0.75,
                    "expert_accepted": True,
                },
                {
                    "task_id": "fixture",
                    "workflow_type": "two_session_co_scientist",
                    "total_hypotheses": 4,
                    "valid_hypotheses": 3,
                    "verified_hypotheses": 1,
                    "citations": 6,
                    "citation_slots": 8,
                    "contradictions_found": 1,
                    "selected_hypotheses": 2,
                    "artifact_quality": 0.7,
                    "citation_quality": 0.75,
                    "expert_accepted": True,
                },
            ]
        )

        self.assertEqual(comparison["recommendation"]["default_workflow"], "simpler_workflow")


if __name__ == "__main__":
    unittest.main()
