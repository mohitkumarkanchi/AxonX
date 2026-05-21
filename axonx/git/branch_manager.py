"""Create and manage agent working branches."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path


def create_working_branch(workspace: Path) -> str:
    """
    Create a new working branch: agent/change-{timestamp}.
    Returns the branch name.
    """
    branch_name = f"agent/change-{int(time.time())}"
    subprocess.run(
        ["git", "checkout", "-b", branch_name],
        cwd=str(workspace),
        check=True,
        capture_output=True,
    )
    return branch_name


def current_branch(workspace: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return "main"


def switch_to_branch(workspace: Path, branch: str) -> None:
    subprocess.run(
        ["git", "checkout", branch],
        cwd=str(workspace),
        check=True,
        capture_output=True,
    )


def delete_branch(workspace: Path, branch: str, force: bool = False) -> None:
    flag = "-D" if force else "-d"
    subprocess.run(
        ["git", "branch", flag, branch],
        cwd=str(workspace),
        check=True,
        capture_output=True,
    )


def list_agent_branches(workspace: Path) -> list[str]:
    """List all agent/change-* branches."""
    result = subprocess.run(
        ["git", "branch", "--list", "agent/change-*"],
        cwd=str(workspace),
        capture_output=True,
        text=True,
    )
    return [b.strip().lstrip("* ") for b in result.stdout.splitlines() if b.strip()]
