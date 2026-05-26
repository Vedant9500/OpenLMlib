"""Unified benchmark suite for OpenLMlib MCP tools.

Warm mode measures steady-state latency in a single process after warmup.
Cold mode measures end-to-end latency in a fresh subprocess per sample,
restoring the same seeded fixture each time to keep samples comparable.
"""

from __future__ import annotations

import argparse
import atexit
import datetime
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Workspace-local temp root avoids OS temp permission surprises in sandboxed envs.
BENCH_TMP_ROOT = PROJECT_ROOT / ".bench_tmp"
BENCH_TMP_ROOT.mkdir(parents=True, exist_ok=True)

TMP_DIR = str(BENCH_TMP_ROOT / f"run_{uuid.uuid4().hex[:8]}")
SETTINGS_PATH = Path(TMP_DIR) / "config" / "settings.json"
os.environ["OPENLMLIB_SETTINGS"] = str(SETTINGS_PATH)
os.environ["OPENLMLIB_MCP_PREWARM"] = "0"
os.environ["OPENLMLIB_EMBED_PREWARM"] = "0"

SNAPSHOT_DIR: str | None = None
STATE: Dict[str, Any] = {}

from openlmlib.mcp_server import (  # noqa: E402
    mcp,
    _get_memory_state,
    _register_collab_tools,
    _register_memory_tools,
)
import openlmlib.mcp_server  # noqa: E402
from openlmlib.library import init_library as lib_init_library  # noqa: E402
from openlmlib.runtime import shutdown_runtime  # noqa: E402

MODEL_TRIGGER_TOOLS = {
    "save_finding",
    "retrieve_findings",
    "search_knowledge",
    "retrieve_context",
    "save_finding_auto",
    "query_memory",
    "session_start",
    "start_research",
}


def reset_mcp_state() -> None:
    """Clear process-local cached state to force fresh initialization."""
    try:
        mem_state = _get_memory_state()
        session_mgr = mem_state.get("session_mgr")
        if session_mgr:
            session_mgr.active_sessions.clear()
            try:
                atexit._unregister(session_mgr._cleanup_on_exit)
            except (AttributeError, ValueError):
                pass
    except Exception:
        pass

    openlmlib.mcp_server._memory_state = None
    shutdown_runtime(SETTINGS_PATH)


def get_all_tools() -> Dict[str, Callable]:
    return {name: tool.fn for name, tool in mcp._tool_manager._tools.items()}


def setup_test_environment() -> None:
    """Create a deterministic seeded fixture on disk and in STATE."""
    base_dir = Path(TMP_DIR)
    config_dir = base_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    lib_init_library(SETTINGS_PATH)
    _register_collab_tools()
    _register_memory_tools()
    tools = get_all_tools()

    # 1. Seed a finding for read operations.
    try:
        res = tools["save_finding"](
            project="bench",
            claim="This is a test finding",
            confidence=0.9,
            confirm=True,
        )
        STATE["finding_id"] = res.get("id")
    except Exception:
        pass

    # 2. Seed a collaboration session and artifact.
    try:
        res = tools["create_session"](
            title="Bench",
            created_by="bench-agent",
            task_description="test",
        )
        STATE["session_id"] = res.get("session_id", "sess_fallback")
        STATE["orch_id"] = res.get("your_agent_id")

        j_res = tools["join_session"](
            session_id=STATE["session_id"],
            model="bench-model",
        )
        STATE["agent_id"] = j_res.get("agent_id", "agent_1")

        if STATE["orch_id"]:
            m_res = tools["send_message"](
                session_id=STATE["session_id"],
                from_agent=STATE["orch_id"],
                msg_type="update",
                content="setup message",
            )
            STATE["seq"] = m_res.get("seq", 1)

            a_res = tools["save_artifact"](
                session_id=STATE["session_id"],
                title="test",
                content="test",
                created_by=STATE["orch_id"],
            )
            STATE["artifact_id"] = a_res.get("artifact_id", "art_1")
    except Exception:
        pass

    # 3. Seed a memory session and one observation.
    try:
        STATE["mem_session_id"] = "bench_mem_1"
        tools["session_start"](session_id=STATE["mem_session_id"], query="test setup")
        o_res = tools["log_observation"](
            session_id=STATE["mem_session_id"],
            tool_name="test",
            tool_input="in",
            tool_output="out",
        )
        STATE["obs_id"] = o_res.get("observation_id", "obs_1")
    except Exception:
        pass


def snapshot_test_environment() -> None:
    global SNAPSHOT_DIR
    if SNAPSHOT_DIR:
        shutil.rmtree(SNAPSHOT_DIR, ignore_errors=True)
    SNAPSHOT_DIR = str(BENCH_TMP_ROOT / f"snapshot_{uuid.uuid4().hex[:8]}")
    shutil.copytree(TMP_DIR, SNAPSHOT_DIR, dirs_exist_ok=True)


def restore_test_environment() -> None:
    if not SNAPSHOT_DIR:
        return
    reset_mcp_state()
    shutil.rmtree(TMP_DIR, ignore_errors=True)
    shutil.copytree(SNAPSHOT_DIR, TMP_DIR, dirs_exist_ok=True)


def get_custom_setup(tool_name: str, tools: Dict[str, Callable]) -> Callable | None:
    def _create_finding():
        res = tools["save_finding"](
            project="bench",
            claim=f"Temp finding {uuid.uuid4().hex}",
            confirm=True,
        )
        return {"finding_id": res.get("id"), "confirm": True}

    def _create_mem_session():
        sid = f"mem_{uuid.uuid4().hex[:8]}"
        tools["session_start"](session_id=sid)
        return {"session_id": sid}

    def _create_collab_session():
        res = tools["create_session"](
            title="Bench",
            created_by="bench-agent",
            task_description="test",
        )
        sid = res.get("session_id")
        oid = res.get("your_agent_id")
        j_res = tools["join_session"](session_id=sid, model="bench-model")
        aid = j_res.get("agent_id")
        return {"session_id": sid, "agent_id": aid, "orchestrator_id": oid}

    if tool_name == "delete_finding":
        return _create_finding

    if tool_name in ["end_session", "session_end"]:
        return _create_mem_session

    if tool_name in [
        "leave_session",
        "terminate_session",
        "export_to_library",
        "join_session",
        "update_session_state",
        "get_artifact",
    ]:
        def _teardown_wrapper():
            kwargs = _create_collab_session()
            if tool_name == "terminate_session":
                return {
                    "session_id": kwargs["session_id"],
                    "orchestrator_id": kwargs["orchestrator_id"],
                }
            if tool_name == "export_to_library":
                tools["terminate_session"](
                    session_id=kwargs["session_id"],
                    orchestrator_id=kwargs["orchestrator_id"],
                )
                return {"session_id": kwargs["session_id"]}
            if tool_name == "join_session":
                res = tools["create_session"](
                    title="JoinBench",
                    created_by="bench",
                    task_description="test",
                )
                return {
                    "session_id": res.get("session_id"),
                    "model": "bench-model",
                }
            if tool_name == "update_session_state":
                return {
                    "session_id": kwargs["session_id"],
                    "orchestrator_id": kwargs["orchestrator_id"],
                    "state": {"key": "val"},
                }
            if tool_name == "get_artifact":
                a_res = tools["save_artifact"](
                    session_id=kwargs["session_id"],
                    title="test",
                    content="test",
                    created_by=kwargs["agent_id"],
                )
                return {
                    "session_id": kwargs["session_id"],
                    "agent_id": kwargs["agent_id"],
                    "artifact_id": a_res.get("artifact_id"),
                }
            return {
                "session_id": kwargs["session_id"],
                "agent_id": kwargs["agent_id"],
            }

        return _teardown_wrapper

    return None


def generate_mock_args(tool_name: str) -> Dict[str, Any]:
    if tool_name == "save_finding":
        return {"project": "bench", "claim": "Benchmarking is important.", "confirm": True}
    if tool_name in ["list_findings", "health", "init_library", "evaluate_retrieval", "get_usage_analytics", "help_library"]:
        return {}
    if tool_name in ["search_findings", "search_knowledge", "retrieve_findings", "retrieve_context", "check_context"]:
        return {"query": "benchmark"}
    if tool_name == "get_finding":
        return {"finding_id": STATE.get("finding_id", "invalid")}
    if tool_name == "save_finding_auto":
        return {"project": "bench", "claim": "Auto save test.", "confirm": True}
    if tool_name == "start_research":
        return {"session_id": f"res_{uuid.uuid4().hex[:8]}", "topic": "benchmarking"}
    if tool_name in ["end_session", "session_end"]:
        return {"session_id": f"sess_{uuid.uuid4().hex[:8]}"}

    if tool_name == "session_start":
        return {"session_id": f"mem_{uuid.uuid4().hex[:8]}", "query": "test"}
    if tool_name == "log_observation":
        return {
            "session_id": STATE.get("mem_session_id", "bench_mem_1"),
            "tool_name": "test",
            "tool_input": "in",
            "tool_output": "out",
        }
    if tool_name == "query_memory":
        return {"query": "test"}
    if tool_name in ["session_recap", "inject_context"]:
        return {"session_id": STATE.get("mem_session_id", "bench_mem_1")}
    if tool_name == "topic_context":
        return {"topic": "test", "session_id": STATE.get("mem_session_id", "bench_mem_1")}
    if tool_name == "search_memory":
        return {"query": "test"}
    if tool_name == "memory_timeline":
        return {"ids": [STATE.get("obs_id", "obs_1")]}
    if tool_name == "get_observations":
        return {"ids": [STATE.get("obs_id", "obs_1")]}
    if tool_name == "ingest_git_history":
        return {
            "session_id": STATE.get("mem_session_id", "bench_mem_1"),
            "time_window_hours": 1,
        }

    sid = STATE.get("session_id", "sess_1")
    aid = STATE.get("agent_id", "agent_1")
    oid = STATE.get("orch_id", aid)

    if tool_name == "create_session":
        return {"title": "Bench", "created_by": "bench-agent", "task_description": "test"}
    if tool_name == "join_session":
        return {"session_id": sid, "model": "bench-model"}
    if tool_name == "send_message":
        return {"session_id": sid, "from_agent": aid, "msg_type": "update", "content": "hello"}
    if tool_name in ["list_sessions", "list_templates", "list_models", "help_collab"]:
        return {}
    if tool_name == "get_session_state":
        return {"session_id": sid, "agent_id": aid}
    if tool_name == "update_session_state":
        return {"session_id": sid, "orchestrator_id": oid, "state": {"test": "val"}}
    if tool_name == "read_messages":
        return {"session_id": sid, "agent_id": aid}
    if tool_name == "poll_messages":
        return {"session_id": sid, "agent_id": aid, "timeout": 0.01}
    if tool_name == "tail_messages":
        return {"session_id": sid, "agent_id": aid}
    if tool_name == "read_message_range":
        return {"session_id": sid, "agent_id": aid, "start_seq": 0, "end_seq": 10}
    if tool_name == "grep_messages":
        return {"session_id": sid, "agent_id": aid, "pattern": "hello"}
    if tool_name == "session_context":
        return {"session_id": sid, "agent_id": aid}
    if tool_name == "save_artifact":
        return {"session_id": sid, "title": "bench", "content": "bench content", "created_by": aid}
    if tool_name == "list_artifacts":
        return {"session_id": sid, "agent_id": aid}
    if tool_name == "get_artifact":
        return {"session_id": sid, "agent_id": aid, "artifact_id": STATE.get("artifact_id", "art_1")}
    if tool_name == "grep_artifacts":
        return {"session_id": sid, "agent_id": aid, "pattern": "bench"}
    if tool_name == "get_template":
        return {"template_id": "deep_research"}
    if tool_name == "create_from_template":
        return {
            "template_id": "deep_research",
            "title": "Template Bench",
            "created_by": "bench",
            "task_description": "test",
        }
    if tool_name == "get_agent_sessions":
        return {"agent_id": aid, "requesting_agent_id": aid}
    if tool_name == "sessions_summary":
        return {"agent_id": aid}
    if tool_name == "search_sessions":
        return {"query": "hello", "agent_id": aid}
    if tool_name == "session_relationships":
        return {"session_id": sid, "agent_id": aid}
    if tool_name == "session_statistics":
        return {"session_id": sid, "agent_id": aid}
    if tool_name == "get_model_details":
        return {"model_id": "anthropic/claude-3-haiku-20240307"}
    if tool_name == "recommended_models":
        return {"task_type": "coding"}

    return {}


def summarize_times(name: str, mode: str, times: List[float], successes: int, errors: int) -> Dict[str, Any]:
    if not times:
        return {"error": "No iterations completed"}

    ordered = sorted(times)
    return {
        "tool": name,
        "mode": mode,
        "iterations": len(times),
        "success_rate": f"{(successes / len(times)) * 100:.1f}%",
        "errors": errors,
        "min_ms": round(min(ordered), 3),
        "max_ms": round(max(ordered), 3),
        "mean_ms": round(statistics.mean(ordered), 3),
        "median_ms": round(statistics.median(ordered), 3),
        "p95_ms": round(ordered[int(len(ordered) * 0.95)] if len(ordered) > 1 else ordered[0], 3),
        "p99_ms": round(ordered[int(len(ordered) * 0.99)] if len(ordered) > 1 else ordered[0], 3),
    }


def benchmark_tool(
    name: str,
    func: Callable,
    iterations: int = 20,
    warmup: int = 3,
    tools_dict: Dict[str, Callable] | None = None,
) -> Dict[str, Any]:
    """Run steady-state warm benchmark in the current process."""
    setup_fn = get_custom_setup(name, tools_dict or {})
    base_kwargs = generate_mock_args(name)

    for _ in range(warmup):
        kwargs = setup_fn() if setup_fn else base_kwargs
        try:
            func(**kwargs)
        except Exception:
            pass

    times: List[float] = []
    successes = 0
    errors = 0

    for _ in range(iterations):
        kwargs = setup_fn() if setup_fn else generate_mock_args(name)
        start = time.perf_counter()
        try:
            res = func(**kwargs)
            if isinstance(res, dict) and (res.get("status") == "error" or res.get("success") is False):
                errors += 1
            else:
                successes += 1
        except Exception:
            errors += 1
        times.append((time.perf_counter() - start) * 1000)

    return summarize_times(name, "warm", times, successes, errors)


def run_cold_sample_subprocess(tool_name: str) -> Dict[str, Any]:
    if not SNAPSHOT_DIR:
        raise RuntimeError("Cold benchmark snapshot not initialized.")

    sample_id = uuid.uuid4().hex[:8]
    sample_root = BENCH_TMP_ROOT / f"cold_{tool_name}_{sample_id}"
    shutil.copytree(SNAPSHOT_DIR, sample_root, dirs_exist_ok=True)
    sample_settings = sample_root / "config" / "settings.json"

    env = os.environ.copy()
    env["OPENLMLIB_SETTINGS"] = str(sample_settings)
    env["OPENLMLIB_MCP_PREWARM"] = "0"
    env["OPENLMLIB_EMBED_PREWARM"] = "0"

    proc = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--cold-sample",
            tool_name,
            "--sample-root",
            str(sample_root),
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
        check=False,
    )

    try:
        shutil.rmtree(sample_root, ignore_errors=True)
    except Exception:
        pass

    if proc.returncode != 0:
        return {
            "success": False,
            "error": proc.stderr.strip() or proc.stdout.strip() or f"exit code {proc.returncode}",
        }

    try:
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception as exc:
        return {
            "success": False,
            "error": f"failed to parse cold sample output: {exc}",
        }
    return payload


def benchmark_tool_cold(name: str, iterations: int = 10) -> Dict[str, Any]:
    """Run true cold-start benchmark using one fresh subprocess per sample."""
    if name not in MODEL_TRIGGER_TOOLS:
        return {"error": f"{name} is not configured as a cold-start tool"}

    times: List[float] = []
    successes = 0
    errors = 0
    failure_messages: List[str] = []

    for _ in range(iterations):
        payload = run_cold_sample_subprocess(name)
        if payload.get("success"):
            successes += 1
            times.append(float(payload["elapsed_ms"]))
        else:
            errors += 1
            failure_messages.append(str(payload.get("error", "unknown cold-sample failure")))

    result = summarize_times(name, "cold", times, successes, errors)
    if failure_messages:
        result["sample_errors"] = failure_messages[:3]
    return result


def run_single_cold_sample(tool_name: str, sample_root: Path) -> int:
    """Entry point for subprocess-isolated cold sample execution."""
    os.environ["OPENLMLIB_SETTINGS"] = str((sample_root / "config" / "settings.json").resolve())
    os.environ["OPENLMLIB_MCP_PREWARM"] = "0"
    os.environ["OPENLMLIB_EMBED_PREWARM"] = "0"

    from openlmlib.mcp_server import (  # local import for subprocess isolation
        mcp as sample_mcp,
        _register_collab_tools as register_collab,
        _register_memory_tools as register_memory,
    )

    register_collab()
    register_memory()
    tools = {name: tool.fn for name, tool in sample_mcp._tool_manager._tools.items()}
    func = tools[tool_name]
    kwargs = generate_mock_args(tool_name)

    start = time.perf_counter()
    success = True
    error = None
    try:
        res = func(**kwargs)
        if isinstance(res, dict) and (res.get("status") == "error" or res.get("success") is False):
            success = False
            error = res
    except Exception as exc:
        success = False
        error = str(exc)
    elapsed_ms = (time.perf_counter() - start) * 1000

    print(json.dumps({
        "tool": tool_name,
        "elapsed_ms": round(elapsed_ms, 3),
        "success": success,
        "error": error,
    }))
    return 0 if success else 1


def print_results(results: List[Dict[str, Any]]) -> None:
    if not results:
        print("No results to display.")
        return

    print(f"\n{'-'*125}")
    print(f"{'Tool Name':<28} | {'Mode':<5} | {'Success':<8} | {'Mean (ms)':<10} | {'Median':<10} | {'P95 (ms)':<10}")
    print(f"{'-'*125}")

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for result in results:
        grouped.setdefault(result["tool"], []).append(result)

    for tool in sorted(grouped.keys()):
        for result in grouped[tool]:
            if "error" in result and "mean_ms" not in result:
                print(f"{result['tool']:<28} | {'-':<5} | Error: {result['error']}")
                continue
            print(
                f"{result['tool']:<28} | {result['mode']:<5} | {result['success_rate']:<8} | "
                f"{result['mean_ms']:<10.2f} | {result['median_ms']:<10.2f} | {result['p95_ms']:<10.2f}"
            )

    print(f"{'-'*125}\n")


def collect_environment_metadata() -> Dict[str, Any]:
    import platform

    return {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "commit": os.environ.get("GIT_COMMIT_SHA", ""),
        "embedding_model_prewarm": os.environ.get("OPENLMLIB_EMBED_PREWARM", "0"),
        "settings_path": str(SETTINGS_PATH),
    }


def cleanup() -> None:
    reset_mcp_state()
    shutil.rmtree(TMP_DIR, ignore_errors=True)
    if SNAPSHOT_DIR:
        shutil.rmtree(SNAPSHOT_DIR, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Unified All-Rounder Benchmark")
    parser.add_argument("--iterations", type=int, default=20, help="Warm iterations per tool")
    parser.add_argument("--cold-iterations", type=int, default=10, help="Cold samples per model-dependent tool")
    parser.add_argument("--warmup", type=int, default=3, help="Warmup iterations before warm timing")
    parser.add_argument("--skip-cold", action="store_true", help="Skip cold-start subprocess benchmarks")
    parser.add_argument("--only-tools", nargs="*", default=None, help="Only benchmark the listed tools")
    parser.add_argument("--cold-sample", type=str, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--sample-root", type=str, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.cold_sample:
        sample_root = Path(args.sample_root) if args.sample_root else None
        if sample_root is None:
            raise SystemExit("--sample-root is required with --cold-sample")
        return run_single_cold_sample(args.cold_sample, sample_root)

    results_dir = PROJECT_ROOT / "results"
    results_dir.mkdir(exist_ok=True)

    print("Initializing benchmark fixture...")
    setup_test_environment()
    snapshot_test_environment()

    try:
        tools = get_all_tools()
        selected_tools = sorted(tools.keys())
        if args.only_tools:
            selected = set(args.only_tools)
            selected_tools = [name for name in selected_tools if name in selected]

        print(f"Loaded {len(selected_tools)} tools.")
        final_results: List[Dict[str, Any]] = []

        print("\n>>> Phase 1: WARM START PASS")
        for name in selected_tools:
            if name == "init_library":
                continue
            final_results.append(
                benchmark_tool(
                    name,
                    tools[name],
                    iterations=args.iterations,
                    warmup=args.warmup,
                    tools_dict=tools,
                )
            )

        if not args.skip_cold:
            print("\n>>> Phase 2: COLD START PASS")
            cold_tools = [name for name in selected_tools if name in MODEL_TRIGGER_TOOLS]
            for name in cold_tools:
                final_results.append(benchmark_tool_cold(name, iterations=args.cold_iterations))

        print_results(final_results)

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        json_path = results_dir / f"benchmark_{timestamp}.json"
        export_data = {
            "timestamp": datetime.datetime.now().isoformat(),
            "config": {
                "iterations": args.iterations,
                "cold_iterations": args.cold_iterations,
                "warmup": args.warmup,
                "skip_cold": args.skip_cold,
                "only_tools": args.only_tools or [],
            },
            "environment": collect_environment_metadata(),
            "results": final_results,
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(export_data, f, indent=2)

        print(f"Full benchmark data exported to {json_path}")
        return 0
    finally:
        print("Performing cleanup...")
        cleanup()
        print("Benchmark cleanup complete.")


if __name__ == "__main__":
    raise SystemExit(main())
