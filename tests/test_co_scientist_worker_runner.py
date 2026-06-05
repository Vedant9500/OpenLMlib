import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from openlmlib.co_scientist.worker_runner import (
    ExternalWorkerRunner,
    WorkerBudget,
    WorkerLaunchSpec,
    request_worker_cancel,
    run_worker_specs_from_settings,
    worker_paths_from_settings,
)
from openlmlib.collab import db as collab_db
from openlmlib.collab.db import connect_collab_db, init_collab_db
from openlmlib.collab.session import create_collab_session


def python_command(source):
    return [sys.executable, "-c", source]


class TestCoScientistWorkerRunner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.settings_path = self.root / "config" / "settings.json"
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.data_root = self.root / "data"
        self.settings_path.write_text(
            json.dumps({"data_root": str(self.data_root)}),
            encoding="utf-8",
        )
        paths = worker_paths_from_settings(self.settings_path)
        self.sessions_dir = paths["sessions_dir"]
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.conn = connect_collab_db(paths["db_path"])
        init_collab_db(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def create_session(self, title="Worker session"):
        return create_collab_session(
            self.conn,
            self.sessions_dir,
            title=title,
            created_by="test-orchestrator",
            description="External worker runner test session.",
        )

    def runner(self):
        return ExternalWorkerRunner(
            self.conn,
            self.sessions_dir,
            self.data_root / "co_scientist_workers",
            settings_path=self.settings_path,
        )

    def test_successful_worker_joins_session_and_writes_log(self):
        session = self.create_session()
        spec = WorkerLaunchSpec(
            session_id=session["session_id"],
            agent_role="generation_worker",
            task_prompt="Inspect the prompt file and exit.",
            command=python_command(
                "import os, pathlib; "
                "print(os.environ['OPENLMLIB_WORKER_SESSION_ID']); "
                "print(os.environ['OPENLMLIB_WORKER_READ_ONLY']); "
                "print(pathlib.Path(os.environ['OPENLMLIB_WORKER_PROMPT_FILE']).read_text()[:40])"
            ),
            model="python-worker",
            budget=WorkerBudget(timeout_seconds=5, max_tokens=100),
            read_only=True,
        )

        results = self.runner().run_workers([spec], heartbeat_interval_seconds=0.1)
        messages = collab_db.get_messages(self.conn, session["session_id"], limit=50)
        agents = collab_db.get_session_agents(self.conn, session["session_id"])
        log_text = Path(results[0].log_path).read_text(encoding="utf-8")

        self.assertEqual(results[0].status, "succeeded")
        self.assertIn(session["session_id"], log_text)
        self.assertIn("Co-Scientist external worker task", Path(results[0].prompt_path).read_text(encoding="utf-8"))
        self.assertTrue(any(agent["model"] == "python-worker" for agent in agents))
        self.assertTrue(any(msg["msg_type"] == "complete" for msg in messages))

    def test_failed_worker_reports_failure_message_without_corrupting_session(self):
        session = self.create_session()
        spec = WorkerLaunchSpec(
            session_id=session["session_id"],
            agent_role="verification_worker",
            task_prompt="Fail on purpose.",
            command=python_command("import sys; print('failing'); sys.exit(3)"),
            model="python-worker",
            budget=WorkerBudget(timeout_seconds=5),
        )

        result = self.runner().run_workers([spec], heartbeat_interval_seconds=0.1)[0]
        messages = collab_db.get_messages(self.conn, session["session_id"], limit=50)
        session_row = collab_db.get_session(self.conn, session["session_id"])

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.returncode, 3)
        self.assertEqual(session_row["status"], "active")
        self.assertTrue(
            any(
                msg["msg_type"] == "update"
                and msg["metadata"].get("status") == "failed"
                for msg in messages
            )
        )

    def test_timeout_terminates_worker(self):
        session = self.create_session()
        spec = WorkerLaunchSpec(
            session_id=session["session_id"],
            agent_role="slow_worker",
            task_prompt="Sleep longer than budget.",
            command=python_command("import time; time.sleep(5)"),
            model="python-worker",
            budget=WorkerBudget(timeout_seconds=1),
        )

        result = self.runner().run_workers([spec], heartbeat_interval_seconds=0.1)[0]
        status = json.loads(Path(result.status_path).read_text(encoding="utf-8"))

        self.assertEqual(result.status, "timeout")
        self.assertTrue(result.timed_out)
        self.assertEqual(status["status"], "timeout")

    def test_cancel_file_stops_running_worker(self):
        session = self.create_session()
        runner = self.runner()
        worker = runner.start_worker(
            WorkerLaunchSpec(
                session_id=session["session_id"],
                agent_role="cancel_worker",
                task_prompt="Run until cancelled.",
                command=python_command("import time; time.sleep(5)"),
                model="python-worker",
                budget=WorkerBudget(timeout_seconds=10),
            )
        )

        def cancel_later():
            time.sleep(0.2)
            request_worker_cancel(worker.worker_dir, reason="test cancellation")

        thread = threading.Thread(target=cancel_later)
        thread.start()
        result = runner.monitor_workers([worker], heartbeat_interval_seconds=0.1)[0]
        thread.join(timeout=1)

        self.assertEqual(result.status, "cancelled")
        self.assertTrue(result.cancelled)
        self.assertTrue((worker.worker_dir / "cancel.json").exists())

    def test_multiple_workers_can_join_different_sessions(self):
        first = self.create_session("Generation linked session")
        second = self.create_session("Verification linked session")
        specs = [
            WorkerLaunchSpec(
                session_id=first["session_id"],
                agent_role="generation_worker",
                task_prompt="Generation worker.",
                command=python_command("print('generation')"),
                model="python-worker",
                budget=WorkerBudget(timeout_seconds=5),
            ),
            WorkerLaunchSpec(
                session_id=second["session_id"],
                agent_role="verification_worker",
                task_prompt="Verification worker.",
                command=python_command("print('verification')"),
                model="python-worker",
                budget=WorkerBudget(timeout_seconds=5),
            ),
        ]

        results = self.runner().run_workers(specs, heartbeat_interval_seconds=0.1)
        first_agents = collab_db.get_session_agents(self.conn, first["session_id"])
        second_agents = collab_db.get_session_agents(self.conn, second["session_id"])

        self.assertEqual([item.status for item in results], ["succeeded", "succeeded"])
        self.assertTrue(any("generation_worker" in agent["capabilities"] for agent in first_agents))
        self.assertTrue(any("verification_worker" in agent["capabilities"] for agent in second_agents))

    def test_run_worker_specs_from_settings_uses_configured_data_root(self):
        session = self.create_session()
        self.conn.close()
        spec = WorkerLaunchSpec(
            session_id=session["session_id"],
            agent_role="settings_worker",
            task_prompt="Use configured data root.",
            command=python_command("print('settings ok')"),
            model="python-worker",
            budget=WorkerBudget(timeout_seconds=5),
        )

        results = run_worker_specs_from_settings(
            [spec],
            settings_path=self.settings_path,
            heartbeat_interval_seconds=0.1,
        )
        self.conn = connect_collab_db(worker_paths_from_settings(self.settings_path)["db_path"])

        self.assertEqual(results[0].status, "succeeded")
        self.assertTrue(Path(results[0].worker_dir).is_relative_to(self.data_root))


if __name__ == "__main__":
    unittest.main()
