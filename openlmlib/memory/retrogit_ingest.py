"""
Retroactive session ingestion from git history and file changes.

Instead of requiring the model to manually log observations, this tool
scans the git working tree to reconstruct session activity:
- Modified/created/deleted files (git status + diff)
- Commits made during the session
- Lines added/removed per file

This works with ANY tool/agent (Qwen Code, Claude Code, manual edits)
because it reads the actual codebase state, not tool call logs.
"""

from __future__ import annotations

import logging
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def run_git(args: List[str], cwd: Optional[str] = None) -> str:
    """Run a git command and return stdout."""
    result = subprocess.run(
        ["git"] + args,
        capture_output=True,
        text=True,
        cwd=cwd or Path.cwd()
    )
    return result.stdout.strip()


def get_modified_files(cwd: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get list of modified, staged, and untracked files."""
    status_output = run_git(["status", "--porcelain"], cwd)
    
    files = []
    for line in status_output.split("\n"):
        if not line.strip():
            continue
        # Git porcelain format: XY<space>path (XY = 2 status chars)
        # Use regex to be safe about varying space formats
        match = re.match(r'^([ADMRCU?! ]{2})\s+(.+)$', line)
        if not match:
            continue
            
        status = match.group(1).strip()
        path = match.group(2).strip()
        
        # Handle renamed files (format: old_path -> new_path)
        if status.startswith("R") and " -> " in path:
            path = path.split(" -> ", 1)[1]
        
        # Determine action
        action = "modified"
        if status.startswith("A") or status.startswith("??"):
            action = "created"
        elif status.startswith("D"):
            action = "deleted"
        elif status.startswith("R"):
            action = "renamed"
        
        files.append({
            "path": path,
            "action": action,
            "git_status": status,
        })
    
    return files


def get_file_diff(file_path: str, cwd: Optional[str] = None) -> str:
    """Get the diff for a specific file."""
    diff_output = run_git(["diff", "--", file_path], cwd)
    if not diff_output:
        # Try staged diff
        diff_output = run_git(["diff", "--cached", "--", file_path], cwd)
    if not diff_output:
        logger.debug(f"No diff available for {file_path}")
    return diff_output


def get_recent_commits(
    since: Optional[str] = None,
    limit: int = 20,
    cwd: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Get recent git commits."""
    if since:
        # Get commits since a specific time
        output = run_git([
            "log", f"--since={since}", f"-{limit}",
            "--format=%H|%h|%s|%an|%ai"
        ], cwd)
    else:
        output = run_git([
            "log", f"-{limit}",
            "--format=%H|%h|%s|%an|%ai"
        ], cwd)
    
    commits = []
    for line in output.split("\n"):
        if not line.strip():
            continue
        parts = line.split("|", 4)
        if len(parts) == 5:
            commits.append({
                "hash": parts[0],
                "short_hash": parts[1],
                "message": parts[2],
                "author": parts[3],
                "date": parts[4],
            })
    
    return commits


def get_commit_diff(hash: str, cwd: Optional[str] = None) -> Dict[str, Any]:
    """Get files changed in a specific commit."""
    # Get changed files
    files_output = run_git(["diff-tree", "--no-commit-id", "--name-status", "-r", hash], cwd)
    
    files = []
    for line in files_output.split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 2:
            action = parts[0]
            path = parts[1]
            
            action_map = {
                "A": "created",
                "M": "modified",
                "D": "deleted",
                "R": "renamed",
                "C": "copied",
            }
            
            files.append({
                "path": path,
                "action": action_map.get(action, "modified"),
            })
    
    # Get diff stats
    stats_output = run_git(["diff-tree", "--no-commit-id", "--stat", hash], cwd)
    
    return {
        "files": files,
        "stats": stats_output,
    }


def get_diff_stats(cwd: Optional[str] = None) -> Dict[str, Any]:
    """Get overall diff statistics for unstaged changes."""
    output = run_git(["diff", "--stat"], cwd)
    return {"uncommitted": output}


def count_lines_changed(diff_text: str) -> Dict[str, int]:
    """Count added/removed lines from diff text."""
    added = 0
    removed = 0
    
    for line in diff_text.split("\n"):
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    
    return {"added": added, "removed": removed}


def infer_file_reason(
    file_path: str,
    action: str,
    diff_text: str,
    commit_messages: List[str]
) -> str:
    """Infer why a file was changed based on diff content and commit messages."""
    diff_lower = diff_text.lower() if diff_text else ""
    
    # Check commit messages for context
    for msg in commit_messages:
        msg_lower = msg.lower()
        file_basename = Path(file_path).stem.lower()
        
        # If commit message mentions the file or its directory
        if file_basename in msg_lower or Path(file_path).parent.name.lower() in msg_lower:
            return f"Commit: {msg[:100]}"
    
    # Analyze diff content
    if action == "created":
        return "New file"
    elif action == "deleted":
        return "File removed"
    elif "def " in diff_lower or "class " in diff_lower:
        return "Code structure changes"
    elif "import " in diff_lower:
        return "Import changes"
    elif "test" in diff_lower or "assert" in diff_lower:
        return "Test modifications"
    elif "fix" in diff_lower or "bug" in diff_lower:
        return "Bug fix"
    elif "doc" in diff_lower or "comment" in diff_lower:
        return "Documentation update"
    elif "format" in diff_lower or "style" in diff_lower:
        return "Formatting/style changes"
    elif action == "modified":
        return "Code modification"
    
    return f"{action.capitalize()}"


def retroactive_ingest(
    session_id: str,
    cwd: Optional[str] = None,
    time_window_hours: int = 24,
    include_uncommitted: bool = True,
) -> Dict[str, Any]:
    """
    Retroactively ingest session activity from git history.
    
    Scans the git working tree to reconstruct what happened during a session:
    - Modified/created/deleted files
    - Commits made during the session
    - Changes per file with line counts
    
    Args:
        session_id: Session identifier
        cwd: Working directory (defaults to current)
        time_window_hours: Hours to look back for commits
        include_uncommitted: Whether to include uncommitted changes
    
    Returns:
        Dict with observations created, knowledge synthesized, and stats
    """
    from .storage import MemoryStorage
    
    cwd = cwd or str(Path.cwd())
    results = {
        "session_id": session_id,
        "files_found": [],
        "commits_found": [],
        "observations_created": 0,
        "knowledge_created": False,
    }
    
    # 0. Create session in storage (required for FK constraints)
    # We need to get the storage instance to create the session
    # This is a bit awkward — the caller should pass storage or we use runtime
    try:
        from openlmlib.runtime import get_runtime
        runtime = get_runtime(Path("config/settings.json"))
        storage = MemoryStorage(runtime.conn)
        # Create session (ignore if already exists)
        try:
            storage.create_session(session_id, "retroactive_ingest")
        except Exception:
            pass  # Session may already exist
    except Exception as e:
        logger.warning(f"Could not create session {session_id}: {e}")
        storage = None
    
    # 1. Get modified files
    if include_uncommitted:
        modified_files = get_modified_files(cwd)
        results["files_found"] = modified_files
        logger.info(
            f"Found {len(modified_files)} modified files in working tree"
        )
    
    # 2. Get recent commits
    commits = get_recent_commits(
        since=f"{time_window_hours} hours ago",
        limit=50,
        cwd=cwd
    )
    results["commits_found"] = commits
    logger.info(f"Found {len(commits)} recent commits")
    
    # 3. Build observations from file changes
    observations = []
    commit_messages = [c["message"] for c in commits]
    
    # Process uncommitted changes
    if include_uncommitted and modified_files:
        for file_info in modified_files:
            file_path = file_info["path"]
            diff = get_file_diff(file_path, cwd)
            lines = count_lines_changed(diff)
            reason = infer_file_reason(
                file_path, file_info["action"], diff, commit_messages
            )
            
            obs_id = f"obs_git_{file_path.replace('/', '_').replace('.', '_')}"
            observation = {
                "id": obs_id,
                "session_id": session_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "tool_name": "git_diff",
                "tool_input": f"git diff -- {file_path}",
                "tool_output": f"File: {file_path}\nAction: {file_info['action']}\n"
                               f"Lines added: {lines['added']}\n"
                               f"Lines removed: {lines['removed']}\n"
                               f"Reason: {reason}",
                "compressed_summary": f"{file_info['action'].title()} {file_path}: {reason}",
            }
            observations.append(observation)
            
            # Save to storage if available
            if storage:
                try:
                    storage.add_observation(observation)
                except Exception as e:
                    logger.debug(f"Could not save observation {obs_id}: {e}")
    
    # Process committed changes
    for commit in commits:
        commit_diff = get_commit_diff(commit["hash"], cwd)
        
        for file_info in commit_diff.get("files", []):
            file_path = file_info["path"]
            # Skip if already in uncommitted changes
            if any(f["path"] == file_path for f in modified_files):
                continue
                
            obs_id = f"obs_commit_{commit['short_hash']}_{file_path.replace('/', '_').replace('.', '_')}"
            observation = {
                "id": obs_id,
                "session_id": session_id,
                "timestamp": commit["date"],
                "tool_name": "git_commit",
                "tool_input": f"git commit -m '{commit['message']}'",
                "tool_output": f"Commit: {commit['short_hash']}\n"
                               f"Message: {commit['message']}\n"
                               f"File: {file_path}\n"
                               f"Action: {file_info['action']}",
                "compressed_summary": (
                    f"Committed {file_path}: {commit['message'][:80]}"
                ),
            }
            observations.append(observation)
            
            # Save to storage if available
            if storage:
                try:
                    storage.add_observation(observation)
                except Exception as e:
                    logger.debug(f"Could not save observation {obs_id}: {e}")
    
    results["observations_created"] = len(observations)
    
    # 4. Synthesize knowledge from observations
    if observations:
        from .knowledge_extractor import extract_knowledge
        knowledge = extract_knowledge(session_id, observations)
        
        # Add git-specific knowledge
        if commits:
            knowledge.phases_completed.extend([
                f"Committed: {c['message'][:50]}" for c in commits[:3]
            ])
        
        if modified_files:
            knowledge.next_steps.append("Review and commit remaining changes")
        
        # Save knowledge
        if storage:
            try:
                storage.save_knowledge(session_id, knowledge.to_dict())
                return {
                    **results,
                    "knowledge": knowledge.to_dict(),
                    "knowledge_summary": knowledge.summary,
                    "knowledge_saved": True,
                }
            except Exception as e:
                logger.warning(f"Could not save knowledge: {e}")
        
        return {
            **results,
            "knowledge": knowledge.to_dict(),
            "knowledge_summary": knowledge.summary,
            "knowledge_saved": False,
        }
    
    return {
        **results,
        "message": "No changes found. The session may not have modified any tracked files.",
    }
