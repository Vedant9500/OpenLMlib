"""Performance benchmarks for CollabSessions.

Measures operation latencies against the targets defined in the plan:
- Message append: < 3ms
- Message read (50): < 5ms
- Context compilation: < 50ms
- Session creation: < 20ms
- FTS5 search: < 10ms
- Concurrent writers: up to 10

Usage:
    python tests/bench_collab.py
    python tests/bench_collab.py --iterations 1000
    python tests/bench_collab.py --benchmark session_creation
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openlmlib.collab.db import (
    connect_collab_db,
    init_collab_db,
    insert_message,
    get_messages_since,
    grep_messages,
    get_messages_tail,
    create_session,
    insert_agent,
    insert_artifact,
    get_session_state,
    update_session_state,
)
from openlmlib.collab.message_bus import MessageBus
from openlmlib.collab.artifact_store import ArtifactStore
from openlmlib.collab.context_compiler import ContextCompiler
from openlmlib.collab.state_manager import StateManager


PERFORMANCE_TARGETS = {
    "message_append_ms": 3.0,
    "message_read_50_ms": 5.0,
    "context_compilation_ms": 50.0,
    "session_creation_ms": 20.0,
    "fts5_search_ms": 10.0,
    "state_update_ms": 5.0,
    "artifact_save_ms": 10.0,
    "message_tail_ms": 5.0,
}


def benchmark(func: Callable, iterations: int = 100, warmup: int = 10) -> Dict[str, float]:
    """Run a function multiple times and return timing statistics.

    Args:
        func: Function to benchmark (should perform one operation)
        iterations: Number of timed iterations
        warmup: Number of untimed warmup runs

    Returns:
        Dict with min, max, mean, median, p95, p99 in milliseconds
    """
    for _ in range(warmup):
        func()

    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        func()
        end = time.perf_counter()
        times.append((end - start) * 1000)

    times.sort()
    return {
        "min_ms": round(min(times), 3),
        "max_ms": round(max(times), 3),
        "mean_ms": round(statistics.mean(times), 3),
        "median_ms": round(statistics.median(times), 3),
        "p95_ms": round(times[int(len(times) * 0.95)], 3),
        "p99_ms": round(times[int(len(times) * 0.99)], 3),
        "stddev_ms": round(statistics.stdev(times), 3) if len(times) > 1 else 0,
    }


def setup_test_db() -> tuple:
    """Create a temporary database for benchmarking."""
    tmpdir = tempfile.mkdtemp()
    db_path = Path(tmpdir) / "bench_collab.db"
    sessions_dir = Path(tmpdir) / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    conn = connect_collab_db(db_path)
    init_collab_db(conn)
    return conn, sessions_dir, tmpdir


def bench_session_creation(iterations: int) -> Dict[str, Any]:
    """Benchmark session creation."""
    conn, sessions_dir, tmpdir = setup_test_db()
    try:
        def create():
            import uuid
            from datetime import datetime, timezone
            sid = f"sess_{uuid.uuid4().hex[:16]}"
            now = datetime.now(timezone.utc).isoformat()
            create_session(conn, sid, "Benchmark Session", "bench", now)
            conn.execute("DELETE FROM session_state WHERE session_id = ?", (sid,))
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (sid,))
            conn.commit()

        result = benchmark(create, iterations)
        return {"operation": "session_creation", "stats": result, "target_ms": PERFORMANCE_TARGETS["session_creation_ms"]}
    finally:
        conn.close()
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def bench_message_append(iterations: int) -> Dict[str, Any]:
    """Benchmark single message append."""
    conn, sessions_dir, tmpdir = setup_test_db()
    try:
        now = "2026-04-06T10:00:00Z"
        create_session(conn, "sess_bench", "Benchmark", "bench", now)
        insert_agent(conn, "agent_bench", "sess_bench", "bench-model", "worker", now)

        seq = 0

        def append():
            nonlocal seq
            seq += 1
            insert_message(
                conn, f"msg_{seq}", "sess_bench", seq, "agent_bench",
                "update", f"Message {seq}", now,
            )
            conn.execute("DELETE FROM messages WHERE msg_id = ?", (f"msg_{seq}",))
            conn.commit()

        result = benchmark(append, iterations)
        return {"operation": "message_append", "stats": result, "target_ms": PERFORMANCE_TARGETS["message_append_ms"]}
    finally:
        conn.close()
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def bench_message_read_50(iterations: int) -> Dict[str, Any]:
    """Benchmark reading 50 messages."""
    conn, sessions_dir, tmpdir = setup_test_db()
    try:
        now = "2026-04-06T10:00:00Z"
        create_session(conn, "sess_bench", "Benchmark", "bench", now)

        for i in range(100):
            insert_message(
                conn, f"msg_{i:04d}", "sess_bench", i, "agent_bench",
                "update", f"Message {i}", now,
            )
        conn.commit()

        def read_50():
            get_messages_since(conn, "sess_bench", 0, limit=50)

        result = benchmark(read_50, iterations)
        return {"operation": "message_read_50", "stats": result, "target_ms": PERFORMANCE_TARGETS["message_read_50_ms"]}
    finally:
        conn.close()
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def bench_fts5_search(iterations: int) -> Dict[str, Any]:
    """Benchmark FTS5 keyword search."""
    conn, sessions_dir, tmpdir = setup_test_db()
    try:
        now = "2026-04-06T10:00:00Z"
        create_session(conn, "sess_bench", "Benchmark", "bench", now)

        topics = ["quantum computing", "machine learning", "neural networks", "error correction", "decoherence"]
        for i in range(200):
            topic = topics[i % len(topics)]
            insert_message(
                conn, f"msg_{i:04d}", "sess_bench", i, "agent_bench",
                "result", f"Research findings on {topic}: detailed analysis of {topic} approaches",
                now,
            )
        conn.commit()

        def search():
            grep_messages(conn, "sess_bench", "quantum", limit=10)

        result = benchmark(search, iterations)
        return {"operation": "fts5_search", "stats": result, "target_ms": PERFORMANCE_TARGETS["fts5_search_ms"]}
    finally:
        conn.close()
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def bench_context_compilation(iterations: int) -> Dict[str, Any]:
    """Benchmark context compilation."""
    conn, sessions_dir, tmpdir = setup_test_db()
    try:
        now = "2026-04-06T10:00:00Z"
        create_session(conn, "sess_bench", "Benchmark", "bench", now)
        insert_agent(conn, "agent_001", "sess_bench", "opus-4.6", "orchestrator", now)
        insert_agent(conn, "agent_002", "sess_bench", "codex", "worker", now)

        for i in range(30):
            insert_message(
                conn, f"msg_{i:04d}", "sess_bench", i,
                "agent_001" if i % 2 == 0 else "agent_002",
                "update", f"Progress update {i}: completed analysis and documented findings",
                now,
            )
        conn.commit()

        bus = MessageBus(conn, sessions_dir)
        store = ArtifactStore(conn, sessions_dir)
        compiler = ContextCompiler(conn, bus, store)

        def compile_ctx():
            compiler.compile_context("sess_bench", "agent_002", max_messages=20)

        result = benchmark(compile_ctx, iterations)
        return {"operation": "context_compilation", "stats": result, "target_ms": PERFORMANCE_TARGETS["context_compilation_ms"]}
    finally:
        conn.close()
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def bench_state_update(iterations: int) -> Dict[str, Any]:
    """Benchmark state update with version check."""
    conn, sessions_dir, tmpdir = setup_test_db()
    try:
        now = "2026-04-06T10:00:00Z"
        create_session(conn, "sess_bench", "Benchmark", "bench", now)
        sm = StateManager(conn)

        version = 1

        def update():
            nonlocal version
            state = {"phase": "testing", "iteration": version}
            sm.update_state("sess_bench", state, "bench", now, version)
            version += 1

        result = benchmark(update, iterations)
        return {"operation": "state_update", "stats": result, "target_ms": PERFORMANCE_TARGETS["state_update_ms"]}
    finally:
        conn.close()
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def bench_artifact_save(iterations: int) -> Dict[str, Any]:
    """Benchmark artifact save to disk + DB."""
    conn, sessions_dir, tmpdir = setup_test_db()
    try:
        now = "2026-04-06T10:00:00Z"
        create_session(conn, "sess_bench", "Benchmark", "bench", now)
        insert_agent(conn, "agent_001", "sess_bench", "opus-4.6", "orchestrator", now)
        store = ArtifactStore(conn, sessions_dir)

        content = "# Research Finding\n\n" + "Lorem ipsum. " * 100
        counter = 0

        def save_artifact():
            nonlocal counter
            counter += 1
            store.save(
                "sess_bench", "agent_001", f"Finding {counter}",
                content, now, artifact_type="research_summary",
            )

        result = benchmark(save_artifact, iterations)
        return {"operation": "artifact_save", "stats": result, "target_ms": PERFORMANCE_TARGETS["artifact_save_ms"]}
    finally:
        conn.close()
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def bench_message_tail(iterations: int) -> Dict[str, Any]:
    """Benchmark tailing last N messages."""
    conn, sessions_dir, tmpdir = setup_test_db()
    try:
        now = "2026-04-06T10:00:00Z"
        create_session(conn, "sess_bench", "Benchmark", "bench", now)

        for i in range(100):
            insert_message(
                conn, f"msg_{i:04d}", "sess_bench", i, "agent_bench",
                "update", f"Message {i}", now,
            )
        conn.commit()

        def tail():
            get_messages_tail(conn, "sess_bench", 20)

        result = benchmark(tail, iterations)
        return {"operation": "message_tail", "stats": result, "target_ms": PERFORMANCE_TARGETS["message_tail_ms"]}
    finally:
        conn.close()
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def bench_concurrent_writes(num_writers: int = 10, messages_per_writer: int = 50) -> Dict[str, Any]:
    """Benchmark concurrent writers using threads."""
    import threading
    import uuid
    from datetime import datetime, timezone

    conn, sessions_dir, tmpdir = setup_test_db()
    try:
        now = "2026-04-06T10:00:00Z"
        create_session(conn, "sess_bench", "Benchmark", "bench", now)

        errors = []
        barrier = threading.Barrier(num_writers)

        def writer(worker_id: int):
            try:
                worker_conn = connect_collab_db(Path(tmpdir) / "bench_collab.db")
                barrier.wait()
                for i in range(messages_per_writer):
                    seq = worker_id * messages_per_writer + i
                    msg_id = f"msg_w{worker_id}_{i}"
                    insert_message(
                        worker_conn, msg_id, "sess_bench", seq,
                        f"agent_worker_{worker_id}", "update",
                        f"Worker {worker_id} message {i}", now,
                    )
                worker_conn.close()
            except Exception as e:
                errors.append(str(e))

        threads = []
        start = time.perf_counter()
        for w in range(num_writers):
            t = threading.Thread(target=writer, args=(w,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()
        elapsed = (time.perf_counter() - start) * 1000

        total_messages = num_writers * messages_per_writer
        actual = conn.execute(
            "SELECT COUNT(*) as cnt FROM messages WHERE session_id = 'sess_bench'"
        ).fetchone()["cnt"]

        return {
            "operation": "concurrent_writes",
            "writers": num_writers,
            "messages_per_writer": messages_per_writer,
            "total_messages": total_messages,
            "actual_messages": actual,
            "total_time_ms": round(elapsed, 3),
            "errors": len(errors),
            "error_details": errors[:5],
            "throughput_msg_per_sec": round(total_messages / (elapsed / 1000), 1) if elapsed > 0 else 0,
        }
    finally:
        conn.close()
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


BENCHMARKS = {
    "session_creation": bench_session_creation,
    "message_append": bench_message_append,
    "message_read_50": bench_message_read_50,
    "fts5_search": bench_fts5_search,
    "context_compilation": bench_context_compilation,
    "state_update": bench_state_update,
    "artifact_save": bench_artifact_save,
    "message_tail": bench_message_tail,
    "concurrent_writes": bench_concurrent_writes,
}


def run_all(iterations: int = 100) -> List[Dict[str, Any]]:
    """Run all benchmarks and return results."""
    results = []
    for name, func in BENCHMARKS.items():
        print(f"  Running {name}...")
        try:
            result = func(iterations)
            results.append(result)
        except Exception as e:
            results.append({"operation": name, "error": str(e)})
            print(f"    ERROR: {e}")
    return results


def print_results(results: List[Dict[str, Any]]) -> None:
    """Print benchmark results in a readable format."""
    print("\n" + "=" * 80)
    print("COLLAB SESSIONS PERFORMANCE BENCHMARK RESULTS")
    print("=" * 80)

    all_pass = True
    for r in results:
        if "error" in r:
            print(f"\n  {r['operation']}: ERROR - {r['error']}")
            all_pass = False
            continue

        stats = r["stats"]
        target = r.get("target_ms")
        op = r["operation"]

        passed = "PASS" if target is None or stats["median_ms"] <= target else "FAIL"
        if passed == "FAIL":
            all_pass = False

        print(f"\n  {op} ({passed})")
        print(f"    Median: {stats['median_ms']:.3f}ms  "
              f"Mean: {stats['mean_ms']:.3f}ms  "
              f"P95: {stats['p95_ms']:.3f}ms  "
              f"P99: {stats['p99_ms']:.3f}ms")
        if target is not None:
            print(f"    Target: <{target}ms  "
                  f"Margin: {'+' if stats['median_ms'] > target else ''}"
                  f"{stats['median_ms'] - target:.3f}ms")

    if "concurrent_writes" in [r.get("operation") for r in results]:
        cw = next(r for r in results if r.get("operation") == "concurrent_writes")
        if "error" not in cw:
            print(f"\n  concurrent_writes")
            print(f"    Writers: {cw['writers']}  "
                  f"Messages: {cw['actual_messages']}/{cw['total_messages']}  "
                  f"Time: {cw['total_time_ms']:.1f}ms  "
                  f"Throughput: {cw['throughput_msg_per_sec']:.0f} msg/s  "
                  f"Errors: {cw['errors']}")

    print("\n" + "=" * 80)
    print(f"  OVERALL: {'ALL TESTS PASSED' if all_pass else 'SOME TESTS FAILED'}")
    print("=" * 80 + "\n")


def main():
    parser = argparse.ArgumentParser(description="CollabSessions performance benchmarks")
    parser.add_argument("--iterations", type=int, default=100, help="Number of iterations per benchmark")
    parser.add_argument("--benchmark", type=str, help="Run only one benchmark")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    parser.add_argument("--writers", type=int, default=10, help="Number of concurrent writers")
    args = parser.parse_args()

    print(f"Running CollabSessions benchmarks (iterations={args.iterations})...")

    if args.benchmark:
        if args.benchmark not in BENCHMARKS:
            print(f"Unknown benchmark: {args.benchmark}")
            print(f"Available: {list(BENCHMARKS.keys())}")
            sys.exit(1)
        results = [BENCHMARKS[args.benchmark](args.iterations)]
    else:
        results = run_all(args.iterations)
        if "concurrent_writes" not in [r.get("operation") for r in results]:
            print(f"  Running concurrent_writes...")
            results.append(bench_concurrent_writes(num_writers=args.writers))

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print_results(results)

    sys.exit(0 if all("error" not in r for r in results) else 1)


if __name__ == "__main__":
    main()
