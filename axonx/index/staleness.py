"""Detect staleness between the index manifest and the current HEAD."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


def load_manifest(index_dir: Path) -> dict:
    manifest_path = index_dir / "manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        return json.loads(manifest_path.read_text())
    except Exception:
        return {}


def current_commit(workspace: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(workspace),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return ""


def changed_files_since(workspace: Path, since_commit: str) -> list[str]:
    """Return list of files changed since the given commit."""
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", since_commit, "HEAD"],
            cwd=str(workspace),
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return [str(workspace / f) for f in out.strip().splitlines() if f]
    except Exception:
        return []


def hash_file(filepath: Path) -> str:
    h = hashlib.sha256()
    try:
        h.update(filepath.read_bytes())
    except OSError:
        pass
    return h.hexdigest()


class StalenessChecker:
    """Check and report index staleness."""

    def __init__(self, workspace: Path, index_dir: Path) -> None:
        self._workspace = workspace
        self._index_dir = index_dir
        self._manifest = load_manifest(index_dir)

    def is_stale(self) -> bool:
        """True if the index is missing or behind HEAD."""
        if not self._manifest:
            return True
        indexed_commit = self._manifest.get("commit_hash", "")
        head = current_commit(self._workspace)
        return indexed_commit != head

    def stale_files(self) -> list[str]:
        """Return files that have changed since the index was built."""
        if not self._manifest:
            return []
        indexed_commit = self._manifest.get("commit_hash", "")
        if not indexed_commit or indexed_commit == "unknown":
            return []

        changed = changed_files_since(self._workspace, indexed_commit)

        # Also check file hashes for uncommitted changes
        stored_hashes = self._manifest.get("file_hashes", {})
        for filepath_str, stored_hash in stored_hashes.items():
            fp = Path(filepath_str)
            if fp.exists() and hash_file(fp) != stored_hash:
                if filepath_str not in changed:
                    changed.append(filepath_str)

        return changed

    def status(self) -> dict:
        if not self._manifest:
            return {"status": "missing", "message": "Index not built. Run: agent init"}

        head = current_commit(self._workspace)
        indexed = self._manifest.get("commit_hash", "unknown")
        stale = self.stale_files()

        if not stale and indexed == head:
            return {
                "status": "fresh",
                "message": f"Index is up to date (commit {head[:7]})",
                "file_count": self._manifest.get("file_count", 0),
                "chunk_count": self._manifest.get("chunk_count", 0),
            }
        else:
            return {
                "status": "stale",
                "message": f"{len(stale)} file(s) changed since index (commit {indexed[:7]})",
                "stale_files": stale,
                "indexed_commit": indexed[:7],
                "head_commit": head[:7],
            }
