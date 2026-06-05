"""External worker runner for Co-Scientist CollabSessions.

Phase 7 keeps process lifecycle outside the MCP server. This module provides a
small supervisor that joins existing sessions, launches explicit local commands,
passes prompts and budgets through files/environment, and reports worker status
back to the session message bus.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, TextIO

import sqlite3

from openlmlib.collab import db as collab_db
from openlmlib.collab.db import connect_collab_db, init_collab_db
from openlmlib.collab.message_bus import MessageBus
from openlmlib.collab.session import join_collab_session
from openlmlib.schema import utc_now_iso
from openlmlib.settings import load_settings, resolve_global_settings_path


WORKER_RUN_PREFIX = "cowork_"
WORKER_STATUS_VALUES = frozenset({
    "starting",
    "running",
    "succeeded",
    "failed",
    "timeout",
    "cancelled",
    "launch_failed",
})


class WorkerRunnerError(Exception):
    """Raised when an external worker cannot be launched or monitored."""


@dataclass(frozen=True)
class WorkerBudget:
    """Budget controls passed to external worker commands."""

    timeout_seconds: int = 900
    max_tokens: Optional[int] = None
    max_cost_usd: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timeout_seconds": self.timeout_seconds,
            "max_tokens": self.max_tokens,
            "max_cost_usd": self.max_cost_usd,
        }


@dataclass(frozen=True)
class WorkerLaunchSpec:
    """One external worker process to launch for an existing session."""

    session_id: str
    agent_role: str
    task_prompt: str
    command: List[str]
    model: str = "external-worker"
    capabilities: List[str] = field(default_factory=list)
    budget: WorkerBudget = field(default_factory=WorkerBudget)
    read_only: bool = True
    env: Dict[str, str] = field(default_factory=dict)
    cwd: Optional[Path] = None
    prompt_to_stdin: bool = True

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "WorkerLaunchSpec":
        if not isinstance(payload, dict):
            raise WorkerRunnerError("Worker spec must be an object")

        budget_payload = payload.get("budget") or {}
        max_tokens = budget_payload.get("max_tokens")
        max_cost_usd = budget_payload.get("max_cost_usd")
        budget = WorkerBudget(
            timeout_seconds=int(budget_payload.get("timeout_seconds", payload.get("timeout_seconds", 900))),
            max_tokens=int(max_tokens) if max_tokens is not None else None,
            max_cost_usd=float(max_cost_usd) if max_cost_usd is not None else None,
        )
        cwd = payload.get("cwd")
        return cls(
            session_id=str(payload.get("session_id", "")).strip(),
            agent_role=str(payload.get("agent_role", "worker")).strip(),
            task_prompt=str(payload.get("task_prompt", "")).strip(),
            command=[str(item) for item in payload.get("command", [])],
            model=str(payload.get("model", "external-worker")).strip(),
            capabilities=[str(item) for item in payload.get("capabilities", [])],
            budget=budget,
            read_only=_coerce_bool(payload.get("read_only", True)),
            env={str(key): str(value) for key, value in (payload.get("env") or {}).items()},
            cwd=Path(cwd) if cwd else None,
            prompt_to_stdin=_coerce_bool(payload.get("prompt_to_stdin", True)),
        )

    def validate(self) -> None:
        issues: List[str] = []
        if not self.session_id:
            issues.append("session_id is required")
        if not self.agent_role:
            issues.append("agent_role is required")
        if not self.task_prompt:
            issues.append("task_prompt is required")
        if not self.command or not all(isinstance(item, str) and item for item in self.command):
            issues.append("command must be a non-empty list of strings")
        if self.budget.timeout_seconds < 1:
            issues.append("budget.timeout_seconds must be >= 1")
        if self.budget.max_tokens is not None and int(self.budget.max_tokens) < 1:
            issues.append("budget.max_tokens must be >= 1 when provided")
        if self.budget.max_cost_usd is not None and float(self.budget.max_cost_usd) < 0:
            issues.append("budget.max_cost_usd must be >= 0 when provided")
        if issues:
            raise WorkerRunnerError("; ".join(issues))


@dataclass
class WorkerProcess:
    worker_run_id: str
    spec: WorkerLaunchSpec
    agent_id: str
    worker_dir: Path
    prompt_path: Path
    log_path: Path
    status_path: Path
    heartbeat_path: Path
    cancel_path: Path
    process: subprocess.Popen
    started_at: str
    started_monotonic: float
    _log_handle: TextIO
    _last_heartbeat: float = 0.0


@dataclass(frozen=True)
class WorkerResult:
    worker_run_id: str
    session_id: str
    agent_id: str
    status: str
    returncode: Optional[int]
    timed_out: bool
    cancelled: bool
    duration_seconds: float
    prompt_path: str
    log_path: str
    status_path: str
    worker_dir: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "worker_run_id": self.worker_run_id,
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "status": self.status,
            "returncode": self.returncode,
            "timed_out": self.timed_out,
            "cancelled": self.cancelled,
            "duration_seconds": self.duration_seconds,
            "prompt_path": self.prompt_path,
            "log_path": self.log_path,
            "status_path": self.status_path,
            "worker_dir": self.worker_dir,
        }


class ExternalWorkerRunner:
    """Launch and monitor external workers for existing CollabSessions."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        sessions_dir: Path,
        workers_dir: Path,
        *,
        settings_path: Optional[Path] = None,
    ):
        self.conn = conn
        self.sessions_dir = sessions_dir
        self.workers_dir = workers_dir
        self.settings_path = settings_path
        self.workers_dir.mkdir(parents=True, exist_ok=True)

    def start_worker(self, spec: WorkerLaunchSpec) -> WorkerProcess:
        spec.validate()
        worker_run_id = WORKER_RUN_PREFIX + uuid.uuid4().hex[:12]
        worker_dir = self.workers_dir / worker_run_id
        worker_dir.mkdir(parents=True, exist_ok=False)

        joined = join_collab_session(
            conn=self.conn,
            sessions_dir=self.sessions_dir,
            session_id=spec.session_id,
            model=spec.model,
            role="worker",
            capabilities=_worker_capabilities(spec),
        )
        agent_id = joined["agent_id"]
        prompt = render_worker_prompt(spec, agent_id=agent_id, worker_run_id=worker_run_id)
        prompt_path = worker_dir / "prompt.txt"
        log_path = worker_dir / "worker.log"
        status_path = worker_dir / "status.json"
        heartbeat_path = worker_dir / "heartbeat.json"
        cancel_path = worker_dir / "cancel.json"
        prompt_path.write_text(prompt, encoding="utf-8")

        env = os.environ.copy()
        env.update(spec.env)
        env.update({
            "OPENLMLIB_WORKER_RUN_ID": worker_run_id,
            "OPENLMLIB_WORKER_SESSION_ID": spec.session_id,
            "OPENLMLIB_WORKER_AGENT_ID": agent_id,
            "OPENLMLIB_WORKER_ROLE": spec.agent_role,
            "OPENLMLIB_WORKER_PROMPT_FILE": str(prompt_path),
            "OPENLMLIB_WORKER_BUDGET_JSON": json.dumps(spec.budget.to_dict(), sort_keys=True),
            "OPENLMLIB_WORKER_READ_ONLY": "1" if spec.read_only else "0",
        })
        if self.settings_path is not None:
            env["OPENLMLIB_SETTINGS"] = str(self.settings_path)

        now = utc_now_iso()
        _write_json(status_path, _status_payload(worker_run_id, spec, agent_id, "starting", now))
        _write_json(heartbeat_path, _heartbeat_payload(worker_run_id, spec, agent_id, "starting", now))

        log_handle = log_path.open("a", encoding="utf-8", buffering=1)
        log_handle.write(f"[{now}] launching {' '.join(spec.command)}\n")
        try:
            process = subprocess.Popen(
                spec.command,
                cwd=str(spec.cwd) if spec.cwd else None,
                env=env,
                stdin=subprocess.PIPE if spec.prompt_to_stdin else subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
            )
            if spec.prompt_to_stdin and process.stdin is not None:
                try:
                    process.stdin.write(prompt)
                    process.stdin.close()
                except (BrokenPipeError, OSError):
                    pass
        except OSError as exc:
            log_handle.write(f"[{utc_now_iso()}] launch failed: {exc}\n")
            log_handle.close()
            collab_db.update_agent_status(self.conn, agent_id, "inactive", utc_now_iso())
            _write_json(
                status_path,
                _status_payload(worker_run_id, spec, agent_id, "launch_failed", utc_now_iso(), error=str(exc)),
            )
            _send_worker_message(
                self.conn,
                self.sessions_dir,
                spec.session_id,
                agent_id,
                "launch_failed",
                worker_run_id,
                log_path,
                error=str(exc),
            )
            raise WorkerRunnerError(f"Failed to launch worker command: {exc}") from exc

        started_monotonic = time.monotonic()
        worker = WorkerProcess(
            worker_run_id=worker_run_id,
            spec=spec,
            agent_id=agent_id,
            worker_dir=worker_dir,
            prompt_path=prompt_path,
            log_path=log_path,
            status_path=status_path,
            heartbeat_path=heartbeat_path,
            cancel_path=cancel_path,
            process=process,
            started_at=now,
            started_monotonic=started_monotonic,
            _log_handle=log_handle,
            _last_heartbeat=started_monotonic,
        )
        _send_worker_message(
            self.conn,
            self.sessions_dir,
            spec.session_id,
            agent_id,
            "running",
            worker_run_id,
            log_path,
        )
        return worker

    def run_workers(
        self,
        specs: Sequence[WorkerLaunchSpec],
        *,
        heartbeat_interval_seconds: float = 5.0,
        terminate_grace_seconds: float = 2.0,
    ) -> List[WorkerResult]:
        if not specs:
            raise WorkerRunnerError("At least one worker spec is required")
        workers: List[WorkerProcess] = []
        try:
            for spec in specs:
                workers.append(self.start_worker(spec))
        except Exception:
            for worker in workers:
                if worker.process.poll() is None:
                    _terminate_process(worker.process, terminate_grace_seconds)
                try:
                    worker._log_handle.write(f"[{utc_now_iso()}] terminated after startup failure\n")
                    worker._log_handle.close()
                except OSError:
                    pass
            raise
        return self.monitor_workers(
            workers,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
            terminate_grace_seconds=terminate_grace_seconds,
        )

    def monitor_workers(
        self,
        workers: Sequence[WorkerProcess],
        *,
        heartbeat_interval_seconds: float = 5.0,
        terminate_grace_seconds: float = 2.0,
    ) -> List[WorkerResult]:
        pending = list(workers)
        results: List[WorkerResult] = []
        heartbeat_interval_seconds = max(0.05, float(heartbeat_interval_seconds))

        while pending:
            now_monotonic = time.monotonic()
            for worker in list(pending):
                returncode = worker.process.poll()
                elapsed = now_monotonic - worker.started_monotonic
                if worker.cancel_path.exists():
                    result = self._finish_worker(
                        worker,
                        status="cancelled",
                        timed_out=False,
                        cancelled=True,
                        terminate_grace_seconds=terminate_grace_seconds,
                    )
                    results.append(result)
                    pending.remove(worker)
                elif elapsed >= worker.spec.budget.timeout_seconds:
                    result = self._finish_worker(
                        worker,
                        status="timeout",
                        timed_out=True,
                        cancelled=False,
                        terminate_grace_seconds=terminate_grace_seconds,
                    )
                    results.append(result)
                    pending.remove(worker)
                elif returncode is not None:
                    result = self._finish_worker(
                        worker,
                        status="succeeded" if returncode == 0 else "failed",
                        timed_out=False,
                        cancelled=False,
                        terminate_grace_seconds=terminate_grace_seconds,
                    )
                    results.append(result)
                    pending.remove(worker)
                elif now_monotonic - worker._last_heartbeat >= heartbeat_interval_seconds:
                    self._heartbeat(worker)

            if pending:
                time.sleep(min(heartbeat_interval_seconds, 0.1))

        return results

    def _heartbeat(self, worker: WorkerProcess) -> None:
        now = utc_now_iso()
        worker._last_heartbeat = time.monotonic()
        collab_db.update_agent_status(self.conn, worker.agent_id, "active", now)
        _write_json(
            worker.heartbeat_path,
            _heartbeat_payload(worker.worker_run_id, worker.spec, worker.agent_id, "running", now),
        )
        _write_json(
            worker.status_path,
            _status_payload(worker.worker_run_id, worker.spec, worker.agent_id, "running", now),
        )

    def _finish_worker(
        self,
        worker: WorkerProcess,
        *,
        status: str,
        timed_out: bool,
        cancelled: bool,
        terminate_grace_seconds: float,
    ) -> WorkerResult:
        if status in {"timeout", "cancelled"} and worker.process.poll() is None:
            _terminate_process(worker.process, terminate_grace_seconds)

        returncode = worker.process.poll()
        finished_at = utc_now_iso()
        duration = round(time.monotonic() - worker.started_monotonic, 3)
        worker._log_handle.write(f"[{finished_at}] status={status} returncode={returncode}\n")
        worker._log_handle.close()
        collab_db.update_agent_status(self.conn, worker.agent_id, "inactive", finished_at)

        _write_json(
            worker.status_path,
            _status_payload(
                worker.worker_run_id,
                worker.spec,
                worker.agent_id,
                status,
                finished_at,
                returncode=returncode,
                duration_seconds=duration,
                timed_out=timed_out,
                cancelled=cancelled,
            ),
        )
        _write_json(
            worker.heartbeat_path,
            _heartbeat_payload(worker.worker_run_id, worker.spec, worker.agent_id, status, finished_at),
        )
        _send_worker_message(
            self.conn,
            self.sessions_dir,
            worker.spec.session_id,
            worker.agent_id,
            status,
            worker.worker_run_id,
            worker.log_path,
            returncode=returncode,
            duration_seconds=duration,
        )
        return WorkerResult(
            worker_run_id=worker.worker_run_id,
            session_id=worker.spec.session_id,
            agent_id=worker.agent_id,
            status=status,
            returncode=returncode,
            timed_out=timed_out,
            cancelled=cancelled,
            duration_seconds=duration,
            prompt_path=str(worker.prompt_path),
            log_path=str(worker.log_path),
            status_path=str(worker.status_path),
            worker_dir=str(worker.worker_dir),
        )


def render_worker_prompt(spec: WorkerLaunchSpec, *, agent_id: str, worker_run_id: str) -> str:
    read_only_text = (
        "Read-only mode is enabled. Do not edit files, run destructive commands, "
        "change remote state, or write to the repository unless a human explicitly "
        "starts an implementation phase."
        if spec.read_only
        else "Write access is permitted by this worker spec; still avoid unrelated changes."
    )
    return "\n".join([
        "Co-Scientist external worker task",
        "",
        f"worker_run_id: {worker_run_id}",
        f"session_id: {spec.session_id}",
        f"agent_id: {agent_id}",
        f"agent_role: {spec.agent_role}",
        f"model: {spec.model}",
        f"read_only: {spec.read_only}",
        f"budget: {json.dumps(spec.budget.to_dict(), sort_keys=True)}",
        "",
        read_only_text,
        "",
        "Task prompt:",
        spec.task_prompt,
        "",
        "Report progress and failures through the CollabSession identified above.",
    ])


def request_worker_cancel(worker_dir: Path, *, reason: str = "cancelled", requested_by: str = "user") -> Path:
    """Request cancellation for a running worker by writing its cancel token."""
    worker_dir = Path(worker_dir)
    worker_dir.mkdir(parents=True, exist_ok=True)
    cancel_path = worker_dir / "cancel.json"
    _write_json(cancel_path, {
        "requested_at": utc_now_iso(),
        "requested_by": requested_by,
        "reason": reason,
    })
    return cancel_path


def load_worker_specs(spec_path: Path) -> List[WorkerLaunchSpec]:
    payload = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    items = payload if isinstance(payload, list) else [payload]
    return [WorkerLaunchSpec.from_dict(item) for item in items]


def worker_paths_from_settings(settings_path: Path) -> Dict[str, Path]:
    settings = load_settings(settings_path)
    data_root = settings.data_root
    return {
        "db_path": data_root / "collab_sessions.db",
        "sessions_dir": data_root / "sessions",
        "workers_dir": data_root / "co_scientist_workers",
    }


def run_worker_specs_from_settings(
    specs: Sequence[WorkerLaunchSpec],
    *,
    settings_path: Optional[Path] = None,
    heartbeat_interval_seconds: float = 5.0,
) -> List[WorkerResult]:
    settings_path = settings_path or resolve_global_settings_path()
    paths = worker_paths_from_settings(settings_path)
    paths["sessions_dir"].mkdir(parents=True, exist_ok=True)
    conn = connect_collab_db(paths["db_path"])
    try:
        existing = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'"
        ).fetchone()
        if existing is None:
            init_collab_db(conn)
        runner = ExternalWorkerRunner(
            conn,
            paths["sessions_dir"],
            paths["workers_dir"],
            settings_path=settings_path,
        )
        return runner.run_workers(specs, heartbeat_interval_seconds=heartbeat_interval_seconds)
    finally:
        conn.close()


def _worker_capabilities(spec: WorkerLaunchSpec) -> List[str]:
    capabilities = list(dict.fromkeys([
        *spec.capabilities,
        "co_scientist_external_worker",
        spec.agent_role,
    ]))
    if spec.read_only and "read_only" not in capabilities:
        capabilities.append("read_only")
    return capabilities


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def _status_payload(
    worker_run_id: str,
    spec: WorkerLaunchSpec,
    agent_id: str,
    status: str,
    timestamp: str,
    **extra: Any,
) -> Dict[str, Any]:
    if status not in WORKER_STATUS_VALUES:
        raise WorkerRunnerError(f"Invalid worker status: {status}")
    payload = {
        "worker_run_id": worker_run_id,
        "session_id": spec.session_id,
        "agent_id": agent_id,
        "agent_role": spec.agent_role,
        "model": spec.model,
        "status": status,
        "read_only": spec.read_only,
        "budget": spec.budget.to_dict(),
        "updated_at": timestamp,
    }
    payload.update(extra)
    return payload


def _heartbeat_payload(
    worker_run_id: str,
    spec: WorkerLaunchSpec,
    agent_id: str,
    status: str,
    timestamp: str,
) -> Dict[str, Any]:
    return {
        "worker_run_id": worker_run_id,
        "session_id": spec.session_id,
        "agent_id": agent_id,
        "status": status,
        "heartbeat_at": timestamp,
    }


def _send_worker_message(
    conn: sqlite3.Connection,
    sessions_dir: Path,
    session_id: str,
    agent_id: str,
    status: str,
    worker_run_id: str,
    log_path: Path,
    **metadata: Any,
) -> None:
    if status == "running":
        msg_type = "system"
        content = f"External Co-Scientist worker started: {worker_run_id}"
    elif status == "succeeded":
        msg_type = "complete"
        content = f"External Co-Scientist worker completed: {worker_run_id}. Log: {log_path}"
    else:
        msg_type = "update"
        content = f"External Co-Scientist worker {worker_run_id} ended with status={status}. Log: {log_path}"

    MessageBus(conn, sessions_dir).send(
        session_id=session_id,
        from_agent=agent_id,
        msg_type=msg_type,
        content=content,
        created_at=utc_now_iso(),
        metadata={
            "worker_run_id": worker_run_id,
            "status": status,
            "log_path": str(log_path),
            **metadata,
        },
    )


def _terminate_process(process: subprocess.Popen, grace_seconds: float) -> None:
    process.terminate()
    try:
        process.wait(timeout=max(0.1, grace_seconds))
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=max(0.1, grace_seconds))


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _single_spec_from_args(args: argparse.Namespace) -> WorkerLaunchSpec:
    prompt = args.prompt or ""
    if args.prompt_file:
        prompt = Path(args.prompt_file).read_text(encoding="utf-8")
    budget = WorkerBudget(
        timeout_seconds=args.timeout_seconds,
        max_tokens=args.max_tokens,
        max_cost_usd=args.max_cost_usd,
    )
    return WorkerLaunchSpec(
        session_id=args.session_id,
        agent_role=args.agent_role,
        task_prompt=prompt,
        command=list(args.command or []),
        model=args.model,
        capabilities=args.capabilities or [],
        budget=budget,
        read_only=not args.allow_writes,
        cwd=Path(args.cwd) if args.cwd else None,
        prompt_to_stdin=not args.no_prompt_stdin,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run external Co-Scientist workers")
    parser.add_argument("--settings", default=str(resolve_global_settings_path()))
    subparsers = parser.add_subparsers(dest="command_name", required=True)

    run_parser = subparsers.add_parser("run", help="Launch one or more external workers")
    run_parser.add_argument("--spec", help="JSON worker spec file; may contain one object or a list")
    run_parser.add_argument("--session-id", help="Session ID for single-worker mode")
    run_parser.add_argument("--agent-role", default="research_worker", help="Worker role label")
    run_parser.add_argument("--model", default="external-worker", help="Model or CLI identifier")
    run_parser.add_argument("--prompt", help="Task prompt for single-worker mode")
    run_parser.add_argument("--prompt-file", help="Read task prompt from file")
    run_parser.add_argument("--capabilities", action="append", help="Worker capability; repeatable")
    run_parser.add_argument("--timeout-seconds", type=int, default=900)
    run_parser.add_argument("--max-tokens", type=int)
    run_parser.add_argument("--max-cost-usd", type=float)
    run_parser.add_argument("--allow-writes", action="store_true", help="Disable read-only prompt/env guard")
    run_parser.add_argument("--cwd", help="Working directory for the worker command")
    run_parser.add_argument("--no-prompt-stdin", action="store_true", help="Only pass prompt by file/env")
    run_parser.add_argument("--heartbeat-interval", type=float, default=5.0)
    run_parser.add_argument("command", nargs="*", help="Command argv for single-worker mode")

    cancel_parser = subparsers.add_parser("cancel", help="Request cancellation for a worker directory")
    cancel_parser.add_argument("--worker-dir", required=True)
    cancel_parser.add_argument("--reason", default="cancelled")
    cancel_parser.add_argument("--requested-by", default="user")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command_name == "cancel":
        cancel_path = request_worker_cancel(
            Path(args.worker_dir),
            reason=args.reason,
            requested_by=args.requested_by,
        )
        print(json.dumps({"cancel_path": str(cancel_path)}, indent=2))
        return 0

    if args.spec:
        specs = load_worker_specs(Path(args.spec))
    else:
        specs = [_single_spec_from_args(args)]
    results = run_worker_specs_from_settings(
        specs,
        settings_path=Path(args.settings),
        heartbeat_interval_seconds=args.heartbeat_interval,
    )
    print(json.dumps({"results": [item.to_dict() for item in results], "count": len(results)}, indent=2))
    return 0 if all(item.status == "succeeded" for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
