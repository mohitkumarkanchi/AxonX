"""Generate conventional commit messages from staged diffs via LLM."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ..llm.provider import LLMProvider, Message

COMMIT_SYSTEM = """\
You are a git commit message writer following the Conventional Commits specification.
Given a diff, write a commit message in the format:
  type(scope): description

  - bullet point explaining key change
  - another bullet if needed

Types: feat, fix, refactor, docs, test, chore, style, perf
Output ONLY the commit message. No explanation. No markdown.
Keep the subject line under 72 characters.
"""


def generate_commit_message(workspace: Path, provider: LLMProvider) -> str:
    """Generate a commit message for staged changes."""
    diff = _get_staged_diff(workspace)
    if not diff:
        diff = _get_unstaged_diff(workspace)
    if not diff:
        return "chore: update files"

    prompt = f"Diff:\n{diff[:4000]}"

    try:
        response = provider.chat(
            messages=[Message(role="user", content=prompt)],
            system=COMMIT_SYSTEM,
            max_tokens=256,
        )
        return response.content.strip()
    except Exception as exc:
        return f"chore: update code\n\n(auto-generation failed: {exc})"


def stage_and_commit(
    workspace: Path,
    files: list[str],
    message: str,
) -> str:
    """Stage specific files and commit. Returns the new commit hash."""
    if files:
        subprocess.run(
            ["git", "add", "--"] + files,
            cwd=str(workspace),
            check=True,
            capture_output=True,
        )

    result = subprocess.run(
        ["git", "commit", "-m", message],
        cwd=str(workspace),
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Commit failed: {result.stderr}")

    # Return new commit hash
    hash_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(workspace),
        capture_output=True,
        text=True,
    )
    return hash_result.stdout.strip()


def _get_staged_diff(workspace: Path) -> str:
    result = subprocess.run(
        ["git", "diff", "--cached"],
        cwd=str(workspace),
        capture_output=True,
        text=True,
    )
    return result.stdout


def _get_unstaged_diff(workspace: Path) -> str:
    result = subprocess.run(
        ["git", "diff"],
        cwd=str(workspace),
        capture_output=True,
        text=True,
    )
    return result.stdout
