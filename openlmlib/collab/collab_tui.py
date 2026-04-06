#!/usr/bin/env python
"""OpenRouter Multi-Agent TUI - Real LLM Communication.

A terminal UI to:
1. Enter OpenRouter API key
2. Browse and select models
3. Choose orchestrator and worker agents
4. Have models actually communicate via OpenRouter API

Usage:
    python -m openlmlib.collab.collab_tui
"""

import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

# Change to project root and add to path
os.chdir(Path(__file__).parent.parent.parent)
sys.path.insert(0, ".")

try:
    from openlmlib.collab.db import connect_collab_db, init_collab_db, list_sessions
    from openlmlib.collab.session import create_collab_session, join_collab_session
    from openlmlib.collab.message_bus import MessageBus
    from openlmlib.collab.artifact_store import ArtifactStore
    from openlmlib.collab.context_compiler import ContextCompiler
    from openlmlib.settings import resolve_global_settings_path
except ImportError as e:
    print(f"Import error: {e}")
    print("Make sure you're running from the OpenLMlib directory")
    sys.exit(1)


OPENROUTER_API = "https://openrouter.ai/api/v1"
DEFAULT_HEADERS = {
    "Content-Type": "application/json",
    "HTTP-Referer": "https://openlmlib.local",
}


def get_api_key() -> str:
    """Get or prompt for OpenRouter API key."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        print(f"Using API key from environment")
        return key
    return input("Enter your OpenRouter API key: ").strip()


def fetch_models(api_key: str) -> list:
    """Fetch available models from OpenRouter."""
    req = urllib.request.Request(
        f"{OPENROUTER_API}/models",
        headers={**DEFAULT_HEADERS, "Authorization": f"Bearer {api_key}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
            return data.get("data", [])
    except Exception as e:
        print(f"Error fetching models: {e}")
        return []


def filter_models(models: list, search: str = "") -> list:
    """Filter models by name search."""
    if not search:
        return models[:30]
    return [m for m in models if search.lower() in m.get("name", "").lower()][:30]


def select_model(models: list, prompt: str) -> str:
    """Interactive model selection."""
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
            print("Invalid selection. Try again.")
        except ValueError:
            print("Please enter a number.")


def call_llm(api_key: str, model: str, system_prompt: str, user_prompt: str, max_tokens: int = 500) -> str:
    """Call OpenRouter API to get LLM response."""
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
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.load(resp)
            return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        return f"Error: {e.code} - {e.reason}"
    except Exception as e:
        return f"Error: {str(e)}"


def init_collab_data():
    """Initialize collab data directory."""
    settings = global_settings_path()
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


def run_real_session(api_key: str, orchestrator_model: dict, worker_model: dict, task: str):
    """Run a real multi-agent session with actual LLM calls."""
    print("\n" + "=" * 60)
    print("Running Real Multi-Agent Collaboration")
    print("=" * 60)
    
    conn, sessions_dir = init_collab_data()
    bus = MessageBus(conn, sessions_dir)
    store = ArtifactStore(conn, sessions_dir)
    compiler = ContextCompiler(conn, bus, store)
    
    # Create session as orchestrator
    print(f"\n[1] Creating session...")
    result = create_collab_session(
        conn=conn,
        sessions_dir=sessions_dir,
        title=f"Collab Session - {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        created_by=orchestrator_model["id"],
        description=task,
        plan=[
            {"step": 1, "task": "Analyze the task and respond", "assigned_to": "any"},
            {"step": 2, "task": "Summarize results", "assigned_to": "orchestrator"},
        ],
    )
    session_id = result["session_id"]
    orchestrator_id = result["agent_id"]
    print(f"    Session: {session_id}")
    
    # Join as worker
    print(f"\n[2] Worker joining...")
    result = join_collab_session(
        conn=conn,
        sessions_dir=sessions_dir,
        session_id=session_id,
        model=worker_model["id"],
        capabilities=["responding"],
    )
    worker_id = result["agent_id"]
    
    # Get worker context
    context = compiler.compile_context(session_id, worker_id)
    
    # Send task message from orchestrator
    print(f"\n[3] Orchestrator sending task to worker...")
    task_msg = bus.send(
        session_id=session_id,
        from_agent=orchestrator_id,
        msg_type="task",
        content=task,
        to_agent=worker_id,
        metadata={"step": 1},
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    
    # Get worker's context and call the LLM
    print(f"\n[4] Calling worker LLM ({worker_model['id']})...")
    worker_system = """You are a helpful assistant participating in a multi-agent collaboration.
You have been given a task by the orchestrator. Respond to the task clearly and concisely."""
    
    worker_user = f"""You are working in session {session_id}.

Your task: {task}

Session context:
- Orchestrator: {orchestrator_id}
- This is a test of multi-agent communication

Please complete your task in 2-3 sentences."""

    worker_response = call_llm(api_key, worker_model["id"], worker_system, worker_user, max_tokens=200)
    print(f"    Worker response: {worker_response[:100]}...")
    
    # Send result message
    print(f"\n[5] Worker sending results back...")
    result_msg = bus.send(
        session_id=session_id,
        from_agent=worker_id,
        msg_type="result",
        content=worker_response,
        to_agent=orchestrator_id,
        metadata={"step": 1},
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    
    # Save artifact
    print(f"\n[6] Saving worker response as artifact...")
    store.save(
        session_id=session_id,
        created_by=worker_id,
        title="Worker Response",
        content=worker_response,
        created_at=datetime.now(timezone.utc).isoformat(),
        artifact_type="test_response",
    )
    
    # Show final state
    print(f"\n[7] Final session state:")
    messages = bus.tail(session_id, 5)
    for msg in messages:
        to = msg.get("to_agent") or "all"
        content = msg['content'][:60].replace('\n', ' ')
        print(f"    [{msg['seq']}] {msg['from_agent']} -> {to} [{msg['msg_type']}]: {content}...")
    
    artifacts = store.list_artifacts(session_id)
    print(f"\n    Artifacts: {len(artifacts)}")
    
    conn.close()
    
    print("\n" + "=" * 60)
    print("SUCCESS! Multi-agent communication completed!")
    print(f"Session ID: {session_id}")
    print("=" * 60)


def main():
    print("=" * 60)
    print("OpenLMlib CollabSessions - Real Multi-Agent TUI")
    print("=" * 60)
    
    # Get API key
    print("\n[Step 1] API Key")
    api_key = get_api_key()
    if not api_key:
        print("No API key. Exiting.")
        return
    
    # Fetch models
    print("\n[Step 2] Fetching models...")
    models = fetch_models(api_key)
    if not models:
        print("No models found.")
        return
    print(f"    Found {len(models)} models")
    
    # Select orchestrator
    print("\n[Step 3] Select ORCHESTRATOR model")
    filtered = filter_models(models)
    orchestrator = select_model(filtered, "Select orchestrator (the one assigning tasks):")
    if not orchestrator:
        return
    
    # Select worker
    print("\n[Step 4] Select WORKER model")
    worker = select_model(filtered, "Select worker (the one responding to tasks):")
    if not worker:
        return
    
    # Enter task
    print("\n[Step 5] Enter task")
    task = input("Enter task for the worker: ").strip()
    if not task:
        task = "Say 'Hello world' and describe what you are doing."
    
    print(f"\nSelected:")
    print(f"  Orchestrator: {orchestrator['id']}")
    print(f"  Worker: {worker['id']}")
    print(f"  Task: {task[:50]}...")
    
    # Confirm
    confirm = input("\nProceed with real LLM calls? (y/n): ").strip().lower()
    if confirm != 'y':
        print("Cancelled.")
        return
    
    run_real_session(api_key, orchestrator, worker, task)


if __name__ == "__main__":
    main()