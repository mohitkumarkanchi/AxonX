#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR=".venv"

# Activate venv
if [[ ! -d "$VENV_DIR" ]]; then
  echo "No .venv found — run: python3 -m venv .venv && .venv/bin/pip install -e .[dev]"
  exit 1
fi
source "$VENV_DIR/bin/activate"

# Ensure build is available
pip install --quiet build

# Clean previous dist artifacts
rm -rf dist/

# Build wheel (no sdist)
python -m build --wheel

WHEEL=$(ls dist/*.whl)
echo ""
echo "Wheel: $WHEEL"
echo "Install: pip install $WHEEL"
