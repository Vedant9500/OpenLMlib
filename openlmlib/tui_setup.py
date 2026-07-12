from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict

from .mcp_setup import global_settings_path


def run_interactive_setup(settings_path: Path | None = None) -> Dict[str, object]:
    settings_path = settings_path or global_settings_path()
    node = shutil.which("node")
    if node is None:
        return {
            "status": "error",
            "message": "Node.js is required for the interactive setup wizard. Install it from https://nodejs.org/",
        }

    installer_dir = Path(__file__).resolve().parent.parent / "installer"
    run_setup = installer_dir / "src" / "run-setup.mjs"

    if not run_setup.exists():
        return {
            "status": "error",
            "message": "Setup wizard not found. Reinstall with: npm install -g openlmlib",
        }

    env = os.environ.copy()
    env["OPENLMLIB_SETTINGS"] = str(Path(settings_path).expanduser().resolve(strict=False))

    result = subprocess.run(
        [node, str(run_setup)],
        stdout=sys.stdout,
        stderr=sys.stderr,
        env=env,
    )

    if result.returncode == 0:
        return {"status": "ok", "settings_path": str(settings_path)}
    return {"status": "error", "message": "Setup wizard exited with errors."}


if __name__ == "__main__":
    run_interactive_setup(global_settings_path())
