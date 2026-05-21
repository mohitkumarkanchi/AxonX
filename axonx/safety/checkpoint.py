"""Git stash checkpoint before every code operation."""

from __future__ import annotations

import subprocess
from pathlib import Path


def create_checkpoint(workspace: Path) -> str:
    """
    Create a git stash snapshot of the current working state.
    Returns the stash ref string (e.g. 'stash@{0}') or '' if nothing to stash.
    """
    # First check if there's anything to stash
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(workspace),
        capture_output=True,
        text=True,
    )
    if not status.stdout.strip():
        return ""  # Nothing to checkpoint

    result = subprocess.run(
        ["git", "stash", "push", "-m", "agent-checkpoint"],
        cwd=str(workspace),
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Checkpoint failed: {result.stderr}")

    # Return the stash ref
    stash_list = subprocess.run(
        ["git", "stash", "list", "--max-count=1"],
        cwd=str(workspace),
        capture_output=True,
        text=True,
    )
    if stash_list.stdout:
        ref = stash_list.stdout.split(":")[0].strip()
        return ref

    return "stash@{0}"


def restore_checkpoint(workspace: Path, stash_ref: str = "") -> None:
    """Restore from a git stash checkpoint."""
    cmd = ["git", "stash", "pop"]
    if stash_ref:
        cmd = ["git", "stash", "apply", stash_ref]

    result = subprocess.run(
        cmd,
        cwd=str(workspace),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Checkpoint restore failed: {result.stderr}")


def drop_checkpoint(workspace: Path, stash_ref: str = "") -> None:
    """Drop a stash checkpoint after a successful operation."""
    cmd = ["git", "stash", "drop"]
    if stash_ref:
        cmd = ["git", "stash", "drop", stash_ref]
    subprocess.run(
        cmd,
        cwd=str(workspace),
        capture_output=True,
    )


def list_checkpoints(workspace: Path) -> list[str]:
    """List all agent-checkpoint stashes."""
    result = subprocess.run(
        ["git", "stash", "list"],
        cwd=str(workspace),
        capture_output=True,
        text=True,
    )
    return [
        line for line in result.stdout.splitlines()
        if "agent-checkpoint" in line
    ]
