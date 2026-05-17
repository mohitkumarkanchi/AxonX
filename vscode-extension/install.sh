#!/bin/bash
# Re-packaging and manually updating the Antigravity extension directory

set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
TARGET_DIR="$HOME/.antigravity/extensions/local-agent.local-agent-0.3.0"
TARGET_DIR_VSCODE="$HOME/.vscode/extensions/local-agent.local-agent-0.3.0"

echo "Building extension resources..."
npm install
npm run build

echo "Clearing out older extension conflict folders..."
rm -rf "$HOME/.antigravity/extensions/local-agent.local-agent-*"
rm -rf "$HOME/.vscode/extensions/local-agent.local-agent-*"

echo "Installing v0.3.0 directly to Antigravity and VS Code extensions paths..."
mkdir -p "$TARGET_DIR"
cp -r "$DIR/package.json" "$TARGET_DIR/"
cp -r "$DIR/out" "$TARGET_DIR/"
cp -r "$DIR/media" "$TARGET_DIR/"

mkdir -p "$TARGET_DIR_VSCODE"
cp -r "$DIR/package.json" "$TARGET_DIR_VSCODE/"
cp -r "$DIR/out" "$TARGET_DIR_VSCODE/"
cp -r "$DIR/media" "$TARGET_DIR_VSCODE/"

echo "Successfully completed! Please completely restart your editor (VS Code or Antigravity) to reload."
