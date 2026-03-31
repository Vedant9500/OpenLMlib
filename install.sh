#!/usr/bin/env bash
set -euo pipefail

if ! command -v pipx >/dev/null 2>&1; then
  echo "pipx not found. Installing pipx..."
  python3 -m pip install --user pipx
  python3 -m pipx ensurepath
  export PATH="$HOME/.local/bin:$PATH"
fi

if [ ! -f "pyproject.toml" ]; then
  echo "Run this script from the LMlib repository root."
  exit 1
fi

pipx install . --force
lmlib setup
lmlib doctor

echo "LMlib installed and validated. Try: lmlib query --query 'retrieval'"
