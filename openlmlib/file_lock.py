from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def _lock_owner_pid(lock_path: Path) -> int | None:
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


_STILL_ACTIVE = 259
_ERROR_ACCESS_DENIED = 5
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _windows_pid_is_alive(pid: int) -> bool:
    """Liveness probe using the Win32 process handle.

    ``os.kill(pid, 0)`` cannot be used here: CPython maps signal 0 to
    ``CTRL_C_EVENT`` and calls ``GenerateConsoleCtrlEvent``, which sends a
    CTRL+C event to every process sharing the console instead of checking
    whether ``pid`` exists.
    """
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        # Access denied still proves the process exists.
        return ctypes.get_last_error() == _ERROR_ACCESS_DENIED

    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return True
        return exit_code.value == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _pid_is_alive(pid: int) -> bool:
    # Reject non-positive PIDs: on Windows pid 0 means "every process in the
    # console group", so probing it would interrupt the whole console.
    if pid <= 0 or pid > 0xFFFFFFFF:
        return False

    if os.name == "nt":
        return _windows_pid_is_alive(pid)

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
    fd: int | None = None

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
