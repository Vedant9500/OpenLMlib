"""Cross-process notification system for CollabSessions.

Provides file-based signaling between MCP server instances running in
different IDE processes (VS Code, Antigravity, Cursor, etc.). This enables
agents to wake up and process new messages without constant polling.

Pattern:
- When an agent sends a message, a notify.json file is written to the session dir.
- Polling agents check this file — if present, they read from the DB immediately.
- If absent, they sleep briefly before re-checking, reducing CPU usage.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)


def _notify_path(sessions_dir: Path, session_id: str) -> Path:
    return sessions_dir / session_id / "notify.json"


def _validate_session_id(session_id: str) -> None:
    """Reject session IDs that could cause path traversal or invalid paths."""
    if not session_id or os.sep in session_id or "/" in session_id:
        raise ValueError(f"Invalid session_id: must not contain path separators: {session_id!r}")


def write_notification(
    sessions_dir: Path,
    session_id: str,
    sender: str,
    msg_type: str,
    seq: int,
    msg_id: str,
    timestamp: str,
) -> bool:
    """Write a notification file for a session.

    This signals to all polling agents that a new message arrived.
    The notification is overwritten on each send — only the latest matters.

    Args:
        sessions_dir: Base sessions directory
        session_id: Session that received the message
        sender: Agent ID that sent the message
        msg_type: Type of message sent
        seq: Sequence number of the message (monotonically increasing)
        msg_id: Unique message ID
        timestamp: ISO timestamp of the message

    Returns:
        True if written successfully, False otherwise.
    """
    try:
        _validate_session_id(session_id)
        notify_file = _notify_path(sessions_dir, session_id)
        notify_file.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "sender": sender,
            "msg_type": msg_type,
            "seq": int(seq),
            "msg_id": msg_id,
            "timestamp": timestamp,
            "_wall_time": time.time(),
        }

        # Atomic write: write to temp then rename.
        # Use .tmp.<uuid> suffix to avoid collision between concurrent writers.
        tmp = notify_file.with_name(notify_file.name + f".tmp.{uuid.uuid4().hex[:8]}")
        with open(tmp, "w") as f:
            json.dump(payload, f)
        os.replace(tmp, notify_file)
        return True
    except Exception as e:
        logger.warning("Failed to write notification for %s: %s", session_id, e)
        # Clean up temp file if rename failed
        if "tmp" in dir() and tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass
        return False


def read_notification(
    sessions_dir: Path, session_id: str
) -> Optional[Dict]:
    """Read the latest notification for a session.

    Returns None if no notification file exists or it is corrupt.
    """
    try:
        _validate_session_id(session_id)
        notify_file = _notify_path(sessions_dir, session_id)
        if not notify_file.exists():
            return None
        with open(notify_file) as f:
            data = json.load(f)
        # Strip internal wall-clock timestamp — not needed by consumers
        data.pop("_wall_time", None)
        return data
    except json.JSONDecodeError:
        logger.warning("Corrupt notification file for %s", session_id)
        return None
    except (FileNotFoundError, PermissionError):
        # File was cleared between exists() and open(), or access denied
        return None
    except Exception as e:
        logger.warning("Failed to read notification for %s: %s", session_id, e)
        return None


def clear_notification(sessions_dir: Path, session_id: str) -> None:
    """DEPRECATED: Notifications are now persistent to prevent race conditions.
    
    This function is kept as a no-op for backward compatibility.
    """
    pass


def wait_for_notification(
    sessions_dir: Path,
    session_id: str,
    timeout: float = 30.0,
    poll_interval: float = 0.5,
    last_seq: int = -1,
) -> Optional[Dict]:
    """Block and wait for a notification to appear.

    This is the core of the autonomous loop — agents call this and it
    sleeps until a message arrives or timeout is reached.

    Args:
        sessions_dir: Base sessions directory
        session_id: Session to monitor
        timeout: Max seconds to wait (0 = no wait, returns immediately;
                 negative = infinite wait)
        poll_interval: Seconds between filesystem checks

    Returns:
        Notification dict if one appears, None on timeout or immediate
        check (when timeout=0).
    """
    _validate_session_id(session_id)

    # timeout=0 means "check once, don't wait"
    if timeout == 0:
        notification = read_notification(sessions_dir, session_id)
        if notification is not None and notification.get("seq", -1) > last_seq:
            return notification
        return None

    # Negative timeout = wait forever (unlikely but supported)
    deadline = None if timeout < 0 else time.monotonic() + timeout

    while True:
        notification = read_notification(sessions_dir, session_id)
        if notification is not None and notification.get("seq", -1) > last_seq:
            return notification

        if deadline is not None and time.monotonic() >= deadline:
            return None

        sleep_for = poll_interval
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            sleep_for = min(sleep_for, max(0.01, remaining))

        time.sleep(sleep_for)
