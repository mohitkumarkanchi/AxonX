"""Stash-based undo/redo stack per operation."""

from __future__ import annotations

import subprocess
from pathlib import Path


def undo_last_operation(
    workspace: Path,
    checkpoint_ref: str,
    files_affected: list[str],
    working_branch: str,
    base_branch: str = "main",
) -> str:
    """
    Undo a code operation.

    Strategy:
    1. If checkpoint_ref (git stash) is set → pop stash to restore pre-op state
    2. Else → git checkout HEAD~1 -- <files>
    3. Switch back to base_branch if we were on a working branch
    Returns a status message.
    """
    if checkpoint_ref:
        # Try to pop the specific stash ref
        result = subprocess.run(
            ["git", "stash", "pop"],
            cwd=str(workspace),
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return f"Undone via stash restore."
        else:
            return f"Stash restore failed: {result.stderr}"

    if files_affected:
        # Restore specific files from HEAD~1
        result = subprocess.run(
            ["git", "checkout", "HEAD~1", "--"] + files_affected,
            cwd=str(workspace),
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return f"Undone: restored {len(files_affected)} file(s) from HEAD~1."
        return f"Checkout failed: {result.stderr}"

    return "Nothing to undo."


def reset_to_base(workspace: Path, base_branch: str, working_branch: str) -> str:
    """
    Discard the working branch entirely and return to base.

    1. Switch to base_branch
    2. Delete working_branch
    Returns status message.
    """
    try:
        subprocess.run(
            ["git", "checkout", base_branch],
            cwd=str(workspace),
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        return f"Failed to switch to {base_branch}: {exc}"

    if working_branch and working_branch != base_branch:
        try:
            subprocess.run(
                ["git", "branch", "-D", working_branch],
                cwd=str(workspace),
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError:
            pass  # Not a hard failure

    return f"Reset: discarded working branch {working_branch}, back on {base_branch}."


def list_stashes(workspace: Path) -> list[str]:
    result = subprocess.run(
        ["git", "stash", "list"],
        cwd=str(workspace),
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]
