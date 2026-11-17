#!/usr/bin/env python3
"""Run the unit-test suite and report a deterministic exit status.

Preferred CI entry point:

    python scripts/run_tests.py

It is a thin wrapper around ``unittest`` discovery that also prints a
one-line summary and treats shutdown failures as diagnostics rather than as
the test verdict. The Windows runner previously reported a passing run and
still exited 1 because ``openlmlib.file_lock._pid_is_alive`` used
``os.kill(pid, 0)``, which CPython maps to ``GenerateConsoleCtrlEvent`` and
therefore delivered CTRL+C to the test process. That bug is fixed; the
explicit exit status here keeps the reported result authoritative.
"""

from __future__ import annotations

import atexit
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    """Discover and run the unit tests, returning a process exit status."""
    # Match `python -m unittest discover -s tests` from the repository root:
    # discovery lives in tests/ while test modules also import `tests.*`.
    os.chdir(REPO_ROOT)
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    suite = unittest.TestLoader().discover("tests")
    result = unittest.TextTestRunner(verbosity=2).run(suite)

    print(
        f"\nsummary: run={result.testsRun} "
        f"failures={len(result.failures)} errors={len(result.errors)} "
        f"skipped={len(result.skipped)}"
    )

    # Run shutdown hooks while stdout/stderr are known good, so a failing
    # atexit callback shows up as a message instead of a silent status change.
    run_exitfuncs = getattr(atexit, "_run_exitfuncs", None)
    if run_exitfuncs is not None:
        try:
            run_exitfuncs()
        except BaseException as exc:  # noqa: BLE001 - diagnostics only
            print(
                f"atexit callback failed: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )

    sys.stdout.flush()
    sys.stderr.flush()
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
