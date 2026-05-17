#!/usr/bin/env bash
# Install the Local Agent VS Code extension from source.
# Run from the vscode-extension/ directory.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "==> Installing npm dependencies…"
npm install

echo "==> Building extension…"
node esbuild.js

echo "==> Packaging extension…"
if ! command -v vsce &>/dev/null; then
  echo "    vsce not found — installing globally"
  npm install -g @vscode/vsce
fi
vsce package --no-dependencies -o local-agent.vsix

echo "==> Installing into VS Code…"
code --install-extension local-agent.vsix

echo ""
echo "Done! Open VS Code and look for 'Local Agent' in the Activity Bar (robot icon)."
echo "Make sure the agent-workspace .venv is set up:"
echo "  cd $(dirname "$SCRIPT_DIR")"
echo "  .venv/bin/pip install -e ."
