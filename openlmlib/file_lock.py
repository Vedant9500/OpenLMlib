from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import time
from typing import Iterator, Optional


def _lock_owner_pid(lock_path: Path) -> Optional[int]:
    try:
        raw = lock_path.read_text(encoding="utf-8").strip()
    except Exception:
        return None

    if not raw:
        return None

    try:
        return int(raw)
    except ValueError:
        return None


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but is not signalable by this user.
        return True
    except OSError:
        return False
    return True


def _lock_is_reclaimable(lock_path: Path, stale_after_sec: float = 2.0) -> bool:
    """True when the lock has no live owner PID (empty, invalid, or dead)."""
    owner_pid = _lock_owner_pid(lock_path)
    if owner_pid is not None:
        return not _pid_is_alive(owner_pid)

    # Empty / unreadable / non-integer contents: reclaim after a short grace period
    # so a crash between O_CREAT|O_EXCL and PID write does not hang forever.
    try:
        age = time.time() - lock_path.stat().st_mtime
    except OSError:
        return True
    return age >= stale_after_sec


@contextmanager
def interprocess_lock(
    lock_path: Path,
    timeout_sec: float = 30.0,
    poll_interval_sec: float = 0.1,
) -> Iterator[None]:
    """Simple cross-process lock using an exclusive lock file.

    This is a best-effort lock for coordinating writes across multiple
    MCP/CLI processes on the same filesystem.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + max(0.1, timeout_sec)
    fd: Optional[int] = None

    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.write(fd, str(os.getpid()).encode("utf-8"))
            break
        except FileExistsError:
            if _lock_is_reclaimable(lock_path):
                try:
                    lock_path.unlink()
                except Exception:
                    pass
                continue

            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timeout waiting for lock: {lock_path}")
            time.sleep(max(0.01, poll_interval_sec))

    try:
        yield
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except Exception:
                pass
        try:
            lock_path.unlink()
        except Exception:
            pass
