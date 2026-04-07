#!/usr/bin/env python
"""OpenRouter Multi-Agent TUI - Real LLM Communication."""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

try:
    from openlmlib.collab.db import connect_collab_db, init_collab_db
    from openlmlib.collab.session import create_collab_session, join_collab_session
    from openlmlib.collab.message_bus import MessageBus
    from openlmlib.collab.artifact_store import ArtifactStore
    from openlmlib.collab.context_compiler import ContextCompiler
    from openlmlib.settings import resolve_global_settings_path
except ImportError as e:
    print(f"Import error: {e}")
    sys.exit(1)


OPENROUTER_API = "https://openrouter.ai/api/v1"
DEFAULT_HEADERS = {
    "Content-Type": "application/json",
    "HTTP-Referer": "https://openlmlib.local",
}


def get_api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        print(f"Using API key from environment")
        return key
    return input("Enter your OpenRouter API key: ").strip()


def request_json_with_retry(req, timeout: int, operation: str, max_attempts: int = 5, base_delay: float = 1.0):
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            last_error = e
            if e.code in {429, 500, 502, 503, 504} and attempt < max_attempts:
                retry_after = None
                if getattr(e, "headers", None):
                    retry_after = e.headers.get("Retry-After")
                delay = base_delay * (2 ** (attempt - 1))
                if retry_after:
                    try:
                        delay = max(delay, float(retry_after))
                    except ValueError:
                        pass
                print(f"{operation} failed with HTTP {e.code}; retrying in {delay:.1f}s...")
                time.sleep(delay)
                continue
            raise
        except urllib.error.URLError:
            raise

    if last_error is not None:
        raise last_error
    raise RuntimeError(f"{operation} failed")


def fetch_models(api_key: str) -> list:
    req = urllib.request.Request(
        f"{OPENROUTER_API}/models",
        headers={**DEFAULT_HEADERS, "Authorization": f"Bearer {api_key}"}
    )
    try:
        data = request_json_with_retry(req, timeout=30, operation="Fetching models")
        return data.get("data", [])
    except Exception as e:
        print(f"Error fetching models: {e}")
        return []


def filter_free_models(models: list) -> list:
    return [m for m in models if "(free)" in m.get("name", "").lower()][:30]


def select_model(models: list, prompt: str) -> str:
    print(f"\n{prompt}")
    print("-" * 50)
    for i, m in enumerate(models):
        print(f"  {i+1:2}. {m.get('name', 'Unknown')[:55]}")
    
    while True:
        try:
            choice = input("\nSelect model number (or 'q' to quit): ").strip().lower()
            if choice == 'q':
                return None
            idx = int(choice) - 1
            if 0 <= idx < len(models):
                return models[idx]
            print("Invalid selection.")
        except ValueError:
            print("Please enter a number.")


def select_workers(models: list, prompt: str) -> list:
    print(f"\n{prompt}")
    print("-" * 50)
    for i, m in enumerate(models):
        print(f"  {i+1:2}. {m.get('name', 'Unknown')[:55]}")
    
    print("\nEnter numbers separated by commas (e.g., 1,3,5)")
    print("Or a single number, or 'q' to quit")
    
    while True:
        try:
            choice = input("\nSelect workers: ").strip().lower()
            if choice == 'q':
                return []
            
            indices = []
            for part in choice.split(','):
                part = part.strip()
                if part.isdigit():
                    idx = int(part) - 1
                    if 0 <= idx < len(models):
                        indices.append(idx)
            
            if indices:
                return [models[i] for i in indices]
            print("Invalid selection.")
        except Exception:
            print("Please enter numbers.")


def call_llm(api_key: str, model: str, system_prompt: str, user_prompt: str, max_tokens: int = 500) -> str:
    req = urllib.request.Request(
        f"{OPENROUTER_API}/chat/completions",
        headers={**DEFAULT_HEADERS, "Authorization": f"Bearer {api_key}"},
        data=json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": max_tokens,
        }).encode("utf-8"),
    )
    
    try:
        data = request_json_with_retry(req, timeout=60, operation=f"Calling model {model}")

        choices = data.get("choices") or []
        if not choices:
            return "Error: Empty response (no choices)"

        message = (choices[0] or {}).get("message") or {}
        content = message.get("content")

        if isinstance(content, str):
            normalized = content.strip()
            if normalized:
                return normalized
            return "Error: Empty text response"

        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    text_part = item.get("text")
                    if isinstance(text_part, str) and text_part.strip():
                        parts.append(text_part.strip())
                elif isinstance(item, str) and item.strip():
                    parts.append(item.strip())
            if parts:
                return "\n".join(parts)
            return "Error: Empty structured response"

        if content is None:
            return "Error: Model returned no text content"

        return str(content)
    except urllib.error.HTTPError as e:
        return f"Error: {e.code} - {e.reason}"
    except Exception as e:
        return f"Error: {str(e)}"


def _extract_json_object(text: str) -> dict:
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else ""
        if raw.endswith("```"):
            raw = raw[:-3]
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found")
    return json.loads(raw[start:end + 1])


def ask_orchestrator_for_next_step(
    api_key: str,
    orchestrator_model: dict,
    compiled_context: str,
    round_num: int,
    max_rounds: int,
) -> dict:
    system_prompt = (
        "You are the orchestrator in a multi-agent collaboration. "
        "Review the current session state and decide whether the work is complete. "
        "Respond with strict JSON only, no markdown, no code fences."
    )
    user_prompt = (
        f"Round {round_num} of {max_rounds}.\n\n"
        f"Current session context:\n{compiled_context}\n\n"
        "Return a JSON object with these keys:\n"
        "status: 'done' or 'continue'\n"
        "summary: concise summary of current findings\n"
        "reason: why you chose the status\n"
        "next_task: if continuing, a precise task for the workers; otherwise an empty string\n"
        "worker_prompt: if continuing, a short prompt each worker should answer; otherwise an empty string\n"
    )
    response = call_llm(api_key, orchestrator_model["id"], system_prompt, user_prompt, max_tokens=500)
    try:
        decision = _extract_json_object(response)
    except Exception:
        lowered = response.lower()
        decision = {
            "status": "done" if any(word in lowered for word in ("done", "complete", "final")) else "continue",
            "summary": response,
            "reason": "Fallback parsing from free-form response.",
            "next_task": "",
            "worker_prompt": "",
        }

    decision.setdefault("status", "done")
    decision.setdefault("summary", "")
    decision.setdefault("reason", "")
    decision.setdefault("next_task", "")
    decision.setdefault("worker_prompt", "")
    return decision


def init_collab_data():
    settings = resolve_global_settings_path()
    if settings.exists():
        with open(settings) as f:
            cfg = json.load(f)
            data_root = Path(cfg.get("data_root", "data"))
    else:
        data_root = Path("data")
    
    db_path = data_root / "collab_sessions.db"
    sessions_dir = data_root / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    
    conn = connect_collab_db(db_path)
    if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'").fetchone() is None:
        init_collab_db(conn)
    
    return conn, sessions_dir


def run_real_session(
    api_key: str,
    orchestrator_model: dict,
    worker_models: list,
    task: str,
    max_rounds: int = 5,
    inter_call_delay: float = 1.5,
    round_delay: float = 2.0,
):
    print("\n" + "=" * 60)
    print("Running Real Multi-Agent Collaboration")
    print("=" * 60)
    
    conn, sessions_dir = init_collab_data()
    bus = MessageBus(conn, sessions_dir)
    store = ArtifactStore(conn, sessions_dir)
    compiler = ContextCompiler(conn, bus, store)
    
    # Create session
    print(f"\n[1] Creating session...")
    result = create_collab_session(
        conn=conn,
        sessions_dir=sessions_dir,
        title=f"Collab Session - {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        created_by=orchestrator_model["id"],
        description=task,
        plan=[
            {"step": 1, "task": "Each worker responds to the task", "assigned_to": "any"},
            {"step": 2, "task": "Summarize results", "assigned_to": "orchestrator"},
        ],
    )
    session_id = result["session_id"]
    orchestrator_id = result["agent_id"]
    print(f"    Session: {session_id}")
    
    # Join workers
    worker_ids = []
    for i, worker_model in enumerate(worker_models):
        print(f"\n[2.{i+1}] Worker {i+1} joining: {worker_model['id']}")
        result = join_collab_session(
            conn=conn,
            sessions_dir=sessions_dir,
            session_id=session_id,
            model=worker_model["id"],
            capabilities=["responding"],
        )
        worker_ids.append(result["agent_id"])
    
    # Send task to all workers
    current_task = task
    final_summary = None
    round_num = 1

    while round_num <= max_rounds:
        print(f"\n[3.{round_num}] Orchestrator sending task to all workers...")
        bus.send(
            session_id=session_id,
            from_agent=orchestrator_id,
            msg_type="task",
            content=current_task,
            to_agent=None,
            metadata={"round": round_num, "worker_count": len(worker_models)},
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        # Call each worker with session context and differentiated roles
        for i, (worker_model, worker_id) in enumerate(zip(worker_models, worker_ids)):
            print(f"\n[4.{round_num}.{i+1}] Worker {i+1}: {worker_model['id']}")

            # Compile context so the worker can see session history
            worker_context = compiler.format_context_for_prompt(
                compiler.compile_context(session_id, worker_id, max_messages=20)
            )

            # Differentiate worker roles to avoid duplicate responses
            focus_areas = [
                "methodology, approach design, and technical implementation",
                "literature review, comparative analysis, and validation",
                "benchmarking, experiments, and results interpretation",
                "integration, documentation, and code quality",
            ]
            worker_focus = focus_areas[i % len(focus_areas)]

            worker_system = (
                f"You are Worker {i+1} of {len(worker_models)} in a multi-agent research collaboration.\n"
                f"Your designated focus: {worker_focus}.\n"
                f"DO NOT repeat what other workers have already contributed. "
                f"Build on their work and add your unique expertise.\n"
                f"Be concrete and specific. Provide actual code, data, or analysis — not plans.\n\n"
                f"=== SESSION CONTEXT ===\n{worker_context}"
            )
            worker_user = (
                f"Round {round_num} of {max_rounds}.\n"
                f"Current task: {current_task}\n\n"
                f"Provide your contribution focusing on: {worker_focus}."
            )

            try:
                worker_response = call_llm(api_key, worker_model["id"], worker_system, worker_user, max_tokens=800)
            except Exception as net_err:
                worker_response = f"Error: Network failure - {net_err}"

            worker_response = worker_response if worker_response else "Error: Empty model response"
            if not worker_response or worker_response.startswith("Error:"):
                print(f"    Response: {worker_response}")
            else:
                print(f"    Response: {worker_response[:80]}...")

            bus.send(
                session_id=session_id,
                from_agent=worker_id,
                msg_type="result",
                content=worker_response,
                to_agent=orchestrator_id,
                metadata={"round": round_num, "worker_num": i+1, "focus": worker_focus},
                created_at=datetime.now(timezone.utc).isoformat(),
            )

            store.save(
                session_id=session_id,
                created_by=worker_id,
                title=f"Round {round_num} Worker {i+1} Response",
                content=worker_response,
                created_at=datetime.now(timezone.utc).isoformat(),
                artifact_type="research_contribution",
                tags=[f"round-{round_num}", f"worker-{i+1}"],
                shared=True,
            )

            if inter_call_delay > 0 and i < len(worker_models) - 1:
                time.sleep(inter_call_delay)

        if inter_call_delay > 0:
            time.sleep(inter_call_delay)

        compiled_context = compiler.format_context_for_prompt(
            compiler.compile_context(session_id, orchestrator_id, max_messages=40)
        )
        try:
            decision = ask_orchestrator_for_next_step(
                api_key=api_key,
                orchestrator_model=orchestrator_model,
                compiled_context=compiled_context,
                round_num=round_num,
                max_rounds=max_rounds,
            )
        except Exception as net_err:
            print(f"\n    Orchestrator call failed: {net_err}. Retrying next round...")
            round_num += 1
            if round_delay > 0:
                time.sleep(round_delay)
            continue

        print(f"\n[5.{round_num}] Orchestrator decision: {decision['status']}")
        if decision.get("reason"):
            print(f"    Reason: {decision['reason']}")

        if decision.get("summary"):
            final_summary = decision["summary"]
            store.save_summary(
                session_id=session_id,
                summary=final_summary,
                created_at=datetime.now(timezone.utc).isoformat(),
                summary_id=f"round_{round_num}_summary",
            )

        if decision.get("status") == "done" or round_num >= max_rounds:
            bus.send(
                session_id=session_id,
                from_agent=orchestrator_id,
                msg_type="complete",
                content=final_summary or f"Completed after round {round_num}",
                to_agent=None,
                metadata={"round": round_num, "reason": decision.get("reason", "")},
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            break

        next_task = (decision.get("next_task") or current_task).strip()
        if next_task:
            current_task = next_task
        round_num += 1
        if round_delay > 0:
            time.sleep(round_delay)
    
    # Show messages
    print(f"\n[6] Session messages:")
    messages = bus.tail(session_id, 10)
    for msg in messages:
        to = msg.get("to_agent") or "all"
        content = msg['content'][:50].replace('\n', ' ')
        print(f"    [{msg['seq']}] {msg['from_agent']} -> {to}: {content}...")
    
    conn.close()
    
    print("\n" + "=" * 60)
    print(f"SUCCESS! Session: {session_id}, Workers: {len(worker_models)}, Rounds: {round_num}")
    print("=" * 60)


def main():
    print("=" * 60)
    print("OpenLMlib CollabSessions - Multi-Agent TUI")
    print("=" * 60)
    
    # API key
    print("\n[Step 1] API Key")
    api_key = get_api_key()
    if not api_key:
        return
    
    # Fetch models
    print("\n[Step 2] Fetching models...")
    models = fetch_models(api_key)
    if not models:
        return
    print(f"    Found {len(models)} models")
    
    # Filter free
    print("\n[Step 3] Filtering for free models...")
    free_models = filter_free_models(models)
    print(f"    Found {len(free_models)} free models")
    
    print("\n    Show: (1) Free only  (2) All models")
    show_choice = input("    Choice (1/2): ").strip()
    
    if show_choice == "1":
        filtered = free_models
        if not filtered:
            filtered = models[:30]
    else:
        filtered = models[:30]
    
    # Select orchestrator
    print("\n[Step 4] Select ORCHESTRATOR")
    orchestrator = select_model(filtered, "Select orchestrator:")
    if not orchestrator:
        return
    
    # Select workers
    print("\n[Step 5] Select WORKERS")
    workers = select_workers(filtered, "Select workers:")
    if not workers:
        return
    
    # Enter task
    print("\n[Step 6] Enter task")
    task = input("Task: ").strip()
    if not task:
        task = "Say hello and describe what you're doing."
    
    print(f"\n  Orchestrator: {orchestrator['id']}")
    print(f"  Workers: {', '.join([w['id'] for w in workers])}")
    print(f"  Task: {task[:50]}...")
    
    confirm = input("\nProceed? (y/n): ").strip().lower()
    if confirm != 'y':
        print("Cancelled.")
        return
    
    max_rounds_input = input("Max rounds to run (default 5): ").strip()
    max_rounds = int(max_rounds_input) if max_rounds_input.isdigit() and int(max_rounds_input) > 0 else 5

    inter_call_delay_input = input("Delay between model calls in seconds (default 1.5): ").strip()
    try:
        inter_call_delay = float(inter_call_delay_input) if inter_call_delay_input else 1.5
    except ValueError:
        inter_call_delay = 1.5

    round_delay_input = input("Delay between rounds in seconds (default 2.0): ").strip()
    try:
        round_delay = float(round_delay_input) if round_delay_input else 2.0
    except ValueError:
        round_delay = 2.0

    run_real_session(
        api_key,
        orchestrator,
        workers,
        task,
        max_rounds=max_rounds,
        inter_call_delay=max(0.0, inter_call_delay),
        round_delay=max(0.0, round_delay),
    )


if __name__ == "__main__":
    # Only change CWD when running as a standalone script
    os.chdir(Path(__file__).parent.parent.parent)
    sys.path.insert(0, ".")
    main()