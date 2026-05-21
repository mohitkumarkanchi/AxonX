"""Render git diffs as coloured hunks in the terminal."""

from __future__ import annotations

import subprocess
from pathlib import Path

try:
    from rich.console import Console
    from rich.syntax import Syntax
    from rich.text import Text
    _HAS_RICH = True
except ImportError:
    _HAS_RICH = False


def render_diff(diff_text: str, console=None) -> None:
    """Render a unified diff with colour."""
    if not diff_text.strip():
        return

    if not _HAS_RICH:
        print(diff_text)
        return

    if console is None:
        from rich.console import Console
        console = Console()

    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            console.print(Text(line, style="bold white"))
        elif line.startswith("@@"):
            console.print(Text(line, style="bold cyan"))
        elif line.startswith("+"):
            console.print(Text(line, style="green"))
        elif line.startswith("-"):
            console.print(Text(line, style="red"))
        else:
            console.print(line)


def get_workspace_diff(workspace: Path, staged: bool = False) -> str:
    """Get the current diff in the workspace."""
    cmd = ["git", "diff"]
    if staged:
        cmd.append("--cached")
    result = subprocess.run(
        cmd,
        cwd=str(workspace),
        capture_output=True,
        text=True,
    )
    return result.stdout


def render_workspace_diff(workspace: Path, staged: bool = False, console=None) -> None:
    """Fetch and render the current workspace diff."""
    diff = get_workspace_diff(workspace, staged=staged)
    if diff:
        render_diff(diff, console=console)
    else:
        msg = "No staged changes." if staged else "No unstaged changes."
        if _HAS_RICH and console:
            console.print(f"[dim]{msg}[/dim]")
        else:
            print(msg)
