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

echo ""
echo "OpenLMlib installed successfully!"
echo ""
echo "Next steps:"
echo "  1. Run 'openlmlib setup' to initialize your library and download the embedding model"
echo "  2. Run 'openlmlib doctor' to validate the installation"
echo "  3. Run 'openlmlib query --query \"retrieval\"' to test retrieval"
echo ""
echo "Note: The embedding model will be downloaded during the setup step (not during install)."
echo ""
