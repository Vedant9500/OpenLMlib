#!/usr/bin/env bash
set -euo pipefail

if ! command -v pipx >/dev/null 2>&1; then
  echo "pipx not found. Installing pipx..."
  python3 -m pip install --user pipx
  python3 -m pipx ensurepath
  export PATH="$HOME/.local/bin:$PATH"
fi

if [ ! -f "pyproject.toml" ]; then
  echo "Run this script from the OpenLMlib repository root."
  exit 1
fi

pipx install . --force
pipx run --spec . openlmlib setup
pipx run --spec . openlmlib doctor

echo "OpenLMlib installed and validated. Try: openlmlib query --query 'retrieval'"
