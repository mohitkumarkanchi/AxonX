"""Restrict agent operations to a subfolder for the session."""

from __future__ import annotations

from pathlib import Path


class ScopePin:
    """Session-level scope restriction to a workspace subfolder."""

    def __init__(self, workspace: Path, scope_path: str = "") -> None:
        self._workspace = workspace
        self._scope: Path | None = None
        if scope_path:
            self.set(scope_path)

    def set(self, scope_path: str) -> None:
        """Pin the scope to a subfolder relative to workspace root."""
        candidate = Path(scope_path)
        if not candidate.is_absolute():
            candidate = self._workspace / candidate
        candidate = candidate.resolve()

        if not candidate.exists():
            raise ValueError(f"Scope path does not exist: {candidate}")
        if not str(candidate).startswith(str(self._workspace)):
            raise ValueError(
                f"Scope path {candidate} is outside workspace {self._workspace}"
            )
        self._scope = candidate

    def clear(self) -> None:
        self._scope = None

    def is_allowed(self, filepath: str | Path) -> bool:
        """Return True if the filepath is within the current scope."""
        if self._scope is None:
            return True  # No restriction
        fp = Path(filepath)
        if not fp.is_absolute():
            fp = self._workspace / fp
        try:
            fp.resolve().relative_to(self._scope)
            return True
        except ValueError:
            return False

    def check_allowed(self, filepath: str | Path) -> None:
        """Raise ValueError if filepath is outside scope."""
        if not self.is_allowed(filepath):
            raise ValueError(
                f"{filepath} is outside the pinned scope {self._scope}. "
                "Use 'agent scope --clear' to remove the restriction."
            )

    @property
    def active(self) -> bool:
        return self._scope is not None

    @property
    def path(self) -> str:
        return str(self._scope) if self._scope else ""

    def __str__(self) -> str:
        if self._scope:
            try:
                return str(self._scope.relative_to(self._workspace))
            except ValueError:
                return str(self._scope)
        return "(none)"
