"""Parse .agentignore and .gitignore files into path exclusion patterns."""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path


DEFAULT_PATTERNS: list[str] = [
    "node_modules/",
    ".git/",
    "dist/",
    "build/",
    ".next/",
    "__pycache__/",
    "*.pyc",
    ".venv/",
    "venv/",
    "*.lock",
    "*.png", "*.jpg", "*.jpeg", "*.gif", "*.svg", "*.ico",
    "*.wasm", "*.bin", "*.exe", "*.so", "*.dylib",
    "*.zip", "*.tar.gz",
    "coverage/",
    ".cache/",
    ".agent/",
    "*.egg-info/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".DS_Store",
]


class ExclusionSet:
    """Compiled set of exclusion patterns from .agentignore and .gitignore."""

    def __init__(self, patterns: list[str]) -> None:
        self._dir_patterns: list[str] = []
        self._file_patterns: list[str] = []
        for p in patterns:
            p = p.strip()
            if not p or p.startswith("#"):
                continue
            if p.endswith("/"):
                self._dir_patterns.append(p.rstrip("/"))
            else:
                self._file_patterns.append(p)

    def is_excluded(self, path: str | Path, workspace_root: str | Path) -> bool:
        path = Path(path)
        workspace_root = Path(workspace_root)
        try:
            rel = path.relative_to(workspace_root)
        except ValueError:
            rel = path

        parts = rel.parts

        # Check each path segment against directory patterns
        for part in parts:
            for dp in self._dir_patterns:
                if fnmatch.fnmatch(part, dp):
                    return True

        # Check the filename against file patterns
        name = path.name
        for fp in self._file_patterns:
            if fnmatch.fnmatch(name, fp):
                return True
            # Also match against relative path string for patterns like "dist/*"
            if fnmatch.fnmatch(str(rel), fp):
                return True

        return False


def load_exclusions(workspace_root: str | Path) -> ExclusionSet:
    """Load exclusion patterns from .agentignore and .gitignore, plus defaults."""
    workspace_root = Path(workspace_root)
    patterns = list(DEFAULT_PATTERNS)

    for filename in (".agentignore", ".gitignore"):
        ignore_file = workspace_root / filename
        if ignore_file.exists():
            try:
                text = ignore_file.read_text(encoding="utf-8", errors="replace")
                for line in text.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        patterns.append(line)
            except OSError:
                pass

    return ExclusionSet(patterns)


def discover_files(
    workspace_root: str | Path,
    exclusions: ExclusionSet | None = None,
) -> list[Path]:
    """Walk workspace and return all non-excluded source files."""
    workspace_root = Path(workspace_root).resolve()
    if exclusions is None:
        exclusions = load_exclusions(workspace_root)

    results: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(workspace_root):
        dirpath_p = Path(dirpath)

        # Prune excluded directories in-place so os.walk skips them
        dirnames[:] = [
            d for d in dirnames
            if not exclusions.is_excluded(dirpath_p / d, workspace_root)
        ]

        for fname in filenames:
            fpath = dirpath_p / fname
            if not exclusions.is_excluded(fpath, workspace_root):
                results.append(fpath)

    return sorted(results)
