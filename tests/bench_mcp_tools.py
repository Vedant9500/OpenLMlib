"""Unified All-Rounder Benchmark Suite for OpenLMlib.

Automatically runs a comprehensive performance evaluation across all 58 tools,
cycling through both Warm Start (cached) and Cold Start (reload) modes.

Features:
- Silent Execution: Fixed schema mismatches and orchestrator validation to eliminate CollabErrors.
- Zero Collision: Unique session IDs prevent 'Session already active' warnings.
- Graceful Lifecycle: Unregisters exit handlers to avoid 'closed database' log pollution.
- Machine-readable JSON exports for visualization.

Usage:
    python tests/bench_mcp_tools.py --iterations 20
"""

import argparse
import atexit
import datetime
import json
import os
import statistics
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Set a dummy settings path so the server doesn't use the real DB
TMP_DIR = tempfile.mkdtemp()
SETTINGS_PATH = Path(TMP_DIR) / "config" / "settings.json"
os.environ["OPENLMLIB_SETTINGS"] = str(SETTINGS_PATH)
os.environ["OPENLMLIB_MCP_PREWARM"] = "0"
os.environ["OPENLMLIB_EMBED_PREWARM"] = "0"

from openlmlib.mcp_server import (
    mcp,
    _register_collab_tools,
    _register_memory_tools,
    _get_memory_state,
)
import openlmlib.mcp_server
from openlmlib.library import init_library as lib_init_library
from openlmlib.runtime import shutdown_runtime

STATE = {}

def reset_mcp_state():
    """Clear the cached state in the MCP server to force fresh initialization."""
    # Find any active session managers and clear their atexit handlers
    try:
        mem_state = _get_memory_state()
        session_mgr = mem_state.get("session_mgr")
        if session_mgr:
            session_mgr.active_sessions.clear()
            # Attempt to unregister atexit handler to stop log pollution
            try:
                # This is a bit hacky but keeps the benchmark logs clean
                atexit._unregister(session_mgr._cleanup_on_exit)
            except (AttributeError, ValueError):
                pass
    except Exception:
        pass

    openlmlib.mcp_server._memory_state = None
    shutdown_runtime(SETTINGS_PATH)

def setup_test_environment():
    """Create a fully functional test environment and seed global state with correct IDs."""
    base_dir = Path(TMP_DIR)
    config_dir = base_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    
    lib_init_library(SETTINGS_PATH)
    
    _register_collab_tools()
    _register_memory_tools()

    tools = get_all_tools()
    
    # 1. Setup global finding for read operations
    try:
        res = tools["save_finding"](project="bench", claim="This is a test finding", confidence=0.9, confirm=True)
        STATE["finding_id"] = res.get("id")
    except Exception:
        pass
        
    # 2. Setup a global collab session
    try:
        res = tools["create_session"](title="Bench", created_by="bench-agent", task_description="test")
        STATE["session_id"] = res.get("session_id", "sess_fallback")
        STATE["orch_id"] = res.get("your_agent_id")
        
        j_res = tools["join_session"](session_id=STATE["session_id"], model="bench-model")
        STATE["agent_id"] = j_res.get("agent_id", "agent_1")
        
        # Use orchestrator to send the setup message
        if STATE["orch_id"]:
            m_res = tools["send_message"](session_id=STATE["session_id"], from_agent=STATE["orch_id"], msg_type="update", content="setup message")
            STATE["seq"] = m_res.get("seq", 1)
            
            a_res = tools["save_artifact"](session_id=STATE["session_id"], title="test", content="test", created_by=STATE["orch_id"])
            STATE["artifact_id"] = a_res.get("artifact_id", "art_1")
    except Exception:
        pass
        
    # 3. Setup a global memory session
    try:
        STATE["mem_session_id"] = "bench_mem_1"
        tools["session_start"](session_id=STATE["mem_session_id"], query="test setup")
        o_res = tools["log_observation"](session_id=STATE["mem_session_id"], tool_name="test", tool_input="in", tool_output="out")
        STATE["obs_id"] = o_res.get("observation_id", "obs_1")
    except Exception:
        pass

def get_all_tools() -> Dict[str, Callable]:
    """Retrieve all registered tools from the FastMCP instance."""
    return {name: tool.fn for name, tool in mcp._tool_manager._tools.items()}


def get_custom_setup(tool_name: str, tools: Dict[str, Callable]) -> Callable:
    """For tools that destroy state, provide a setup function to run before each iteration."""
    
    def _create_finding():
        res = tools["save_finding"](project="bench", claim=f"Temp finding {uuid.uuid4().hex}", confirm=True)
        return {"finding_id": res.get("id"), "confirm": True}

    def _create_mem_session():
        sid = f"mem_{uuid.uuid4().hex[:8]}"
        tools["session_start"](session_id=sid)
        return {"session_id": sid}

    def _create_collab_session():
        res = tools["create_session"](title="Bench", created_by="bench-agent", task_description="test")
        sid = res.get("session_id")
        oid = res.get("your_agent_id")
        j_res = tools["join_session"](session_id=sid, model="bench-model")
        aid = j_res.get("agent_id")
        return {"session_id": sid, "agent_id": aid, "orchestrator_id": oid}

    if tool_name == "delete_finding":
        return _create_finding
    
    if tool_name in ["end_session", "session_end"]:
        return _create_mem_session
        
    if tool_name in ["leave_session", "terminate_session", "export_to_library", "join_session", "update_session_state", "get_artifact"]:
        def _teardown_wrapper():
            kwargs = _create_collab_session()
            if tool_name == "terminate_session":
                return {"session_id": kwargs["session_id"], "orchestrator_id": kwargs["orchestrator_id"]}
            if tool_name == "export_to_library":
                tools["terminate_session"](session_id=kwargs["session_id"], orchestrator_id=kwargs["orchestrator_id"])
                return {"session_id": kwargs["session_id"]}
            if tool_name == "join_session":
                res = tools["create_session"](title="JoinBench", created_by="bench", task_description="test")
                return {"session_id": res.get("session_id"), "model": "bench-model"}
            if tool_name == "update_session_state":
                return {"session_id": kwargs["session_id"], "orchestrator_id": kwargs["orchestrator_id"], "state": {"key": "val"}}
            if tool_name == "get_artifact":
                a_res = tools["save_artifact"](session_id=kwargs["session_id"], title="test", content="test", created_by=kwargs["agent_id"])
                return {"session_id": kwargs["session_id"], "agent_id": kwargs["agent_id"], "artifact_id": a_res.get("artifact_id")}
            return {"session_id": kwargs["session_id"], "agent_id": kwargs["agent_id"]}
        return _teardown_wrapper

    return None


def generate_mock_args(tool_name: str) -> Dict[str, Any]:
    """Provide sane default arguments for testing specific tools."""
    # Core Tools
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
    
    # Memory Tools
    if tool_name == "session_start":
        return {"session_id": f"mem_{uuid.uuid4().hex[:8]}", "query": "test"}
    if tool_name == "log_observation":
        return {"session_id": STATE.get("mem_session_id", "bench_mem_1"), "tool_name": "test", "tool_input": "in", "tool_output": "out"}
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
        return {"session_id": STATE.get("mem_session_id", "bench_mem_1"), "time_window_hours": 1}

    # Collab Tools
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
        return {"template_id": "deep_research", "title": "Template Bench", "created_by": "bench", "task_description": "test"}
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


def benchmark_tool(
    name: str, 
    func: Callable, 
    iterations: int = 20, 
    warmup: int = 3, 
    tools_dict: Dict = None,
    cold_start: bool = False
) -> Dict[str, Any]:
    """Run a specific tool multiple times and return timing statistics."""
    setup_fn = get_custom_setup(name, tools_dict) if tools_dict else None
    base_kwargs = generate_mock_args(name)

    # List of tools that trigger model loading
    model_trigger_tools = [
        "save_finding", "retrieve_findings", "search_knowledge", 
        "retrieve_context", "save_finding_auto", "query_memory",
        "session_start", "start_research"
    ]

    # Warmup (only for non-cold start runs)
    if not cold_start:
        for _ in range(warmup):
            kwargs = setup_fn() if setup_fn else base_kwargs
            try:
                func(**kwargs)
            except Exception:
                pass

    times = []
    successes = 0
    errors = 0

    for i in range(iterations):
        if cold_start and name in model_trigger_tools:
            reset_mcp_state()
            lib_init_library(SETTINGS_PATH)

        # Generate unique IDs for every iteration of session creators to avoid collisions
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
            
        end = time.perf_counter()
        times.append((end - start) * 1000)

    if not times:
        return {"error": "No iterations completed"}

    times.sort()
    return {
        "tool": name,
        "mode": "cold" if cold_start and name in model_trigger_tools else "warm",
        "iterations": iterations,
        "success_rate": f"{(successes / iterations) * 100:.1f}%",
        "errors": errors,
        "min_ms": round(min(times), 3),
        "max_ms": round(max(times), 3),
        "mean_ms": round(statistics.mean(times), 3),
        "median_ms": round(statistics.median(times), 3),
        "p95_ms": round(times[int(len(times) * 0.95)] if len(times) > 1 else times[0], 3),
        "p99_ms": round(times[int(len(times) * 0.99)] if len(times) > 1 else times[0], 3),
    }


def print_results(results: List[Dict[str, Any]]):
    if not results:
        print("No results to display.")
        return

    print(f"\n{'-'*125}")
    print(f"{'Tool Name':<28} | {'Mode':<5} | {'Success':<8} | {'Mean (ms)':<10} | {'Median':<10} | {'P95 (ms)':<10}")
    print(f"{'-'*125}")
    
    # Group by tool name to show warm/cold side-by-side
    grouped = {}
    for r in results:
        grouped.setdefault(r['tool'], []).append(r)
        
    for tool in sorted(grouped.keys()):
        for r in grouped[tool]:
            if "error" in r:
                print(f"{r['tool']:<28} | {'-':<5} | Error: {r['error']}")
                continue
                
            print(f"{r['tool']:<28} | {r['mode']:<5} | {r['success_rate']:<8} | {r['mean_ms']:<10.2f} | {r['median_ms']:<10.2f} | {r['p95_ms']:<10.2f}")
    
    print(f"{'-'*125}\n")


def main():
    parser = argparse.ArgumentParser(description="Unified All-Rounder Benchmark")
    parser.add_argument("--iterations", type=int, default=20, help="Number of iterations per tool")
    args = parser.parse_args()

    # Ensure results directory exists
    results_dir = Path("results")
    results_dir.mkdir(exist_ok=True)

    print("Initializing All-Rounder test environment...")
    setup_test_environment()
    
    tools = get_all_tools()
    print(f"Loaded {len(tools)} tools. Starting Warm and Cold passes...")
    
    final_results = []

    # 1. Warm Pass (All Tools)
    print("\n>>> Phase 1: WARM START PASS (All tools)")
    for name in sorted(tools.keys()):
        if name == "init_library": continue
        res = benchmark_tool(name, tools[name], args.iterations, cold_start=False, tools_dict=tools)
        final_results.append(res)

    # 2. Cold Pass (Model-dependent Tools only)
    print("\n>>> Phase 2: COLD START PASS (Model-dependent tools)")
    model_dependent = ["retrieve_findings", "search_knowledge", "query_memory", "save_finding", "session_start", "start_research"]
    for name in model_dependent:
        if name in tools:
            res = benchmark_tool(name, tools[name], 3, cold_start=True, tools_dict=tools)
            final_results.append(res)

    print_results(final_results)
    
    # Export to results/
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = results_dir / f"benchmark_{timestamp}.json"
    
    export_data = {
        "timestamp": datetime.datetime.now().isoformat(),
        "config": {"iterations": args.iterations},
        "results": final_results
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(export_data, f, indent=2)
    
    print(f"Full benchmark data exported to {json_path}")
    
    # GRACEFUL CLEANUP: End sessions and unregister exit handlers
    print("Performing graceful cleanup...")
    reset_mcp_state()
    
    import shutil
    shutil.rmtree(TMP_DIR, ignore_errors=True)
    print("Test environment cleaned up.")

if __name__ == "__main__":
    main()
