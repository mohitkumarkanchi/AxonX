"""Safety guardrails — protected branch check, max-files limit, scope check."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ..config import Config


class GuardrailError(Exception):
    """Raised when a safety guardrail blocks an operation."""


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
    except Exception:
        return "main"


def check_operation(
    files: list[str],
    workspace: Path,
    config: Config,
    force: bool = False,
    scope_pin: str = "",
) -> None:
    """
    Run all guardrail checks before a code operation.
    Raises GuardrailError if any check fails.
    """
    branch = current_branch(workspace)

    # 1. Protected branch check
    if branch in config.safety.protected_branches:
        raise GuardrailError(
            f"Cannot modify protected branch '{branch}'. "
            f"Protected branches: {config.safety.protected_branches}. "
            "The agent will create a working branch instead."
        )

    # 2. File count limit
    max_files = config.safety.max_files_per_operation
    if not force and len(files) > max_files:
        raise GuardrailError(
            f"Operation touches {len(files)} files "
            f"(limit: {max_files}). Use --force to override."
        )

    # 3. Scope pin check
    if scope_pin:
        scope_path = Path(scope_pin).resolve()
        for filepath in files:
            fp = Path(workspace / filepath if not Path(filepath).is_absolute() else filepath)
            try:
                fp.resolve().relative_to(scope_path)
            except ValueError:
                raise GuardrailError(
                    f"File {fp.name} is outside the scoped path '{scope_pin}'. "
                    "Use 'agent scope --clear' to remove the scope restriction."
                )


def is_protected_branch(branch: str, config: Config) -> bool:
    return branch in config.safety.protected_branches
