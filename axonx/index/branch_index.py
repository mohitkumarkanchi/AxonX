"""
Per-branch delta index management.

Base index lives in:   .agent/index/branches/main/
Branch delta lives in: .agent/index/branches/{branch_name}/

A delta stores only what changed vs the branch point — modified/added/deleted
chunk IDs and graph edges. On activation, the working index is the base merged
with the delta.

On git checkout (detected via watchdog watching .git/HEAD), the old branch
index is deactivated and the new one activated.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .faiss_store import FAISSStore
from .graph_store import GraphStore


class BranchIndex:
    """Manages per-branch FAISS + graph delta index."""

    def __init__(self, agent_dir: Path) -> None:
        self._agent_dir = agent_dir
        self._branches_dir = agent_dir / "index" / "branches"
        self._branches_dir.mkdir(parents=True, exist_ok=True)
        self._active_branch: str = ""
        self._faiss: FAISSStore | None = None
        self._graph: GraphStore | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def activate(self, branch: str) -> None:
        """Switch the active index to the given branch."""
        if self._active_branch == branch and self._faiss is not None:
            return

        # Close current stores
        self.close()

        self._active_branch = branch
        branch_dir = self._branches_dir / _sanitize(branch)
        branch_dir.mkdir(parents=True, exist_ok=True)

        self._faiss = FAISSStore(branch_dir / "vectors")
        self._graph = GraphStore(branch_dir / "graph.db")

    def close(self) -> None:
        if self._faiss:
            self._faiss.close()
            self._faiss = None
        if self._graph:
            self._graph.close()
            self._graph = None
        self._active_branch = ""

    # ------------------------------------------------------------------
    # Accessors (delegate to stores)
    # ------------------------------------------------------------------

    @property
    def faiss(self) -> FAISSStore:
        if self._faiss is None:
            raise RuntimeError("No branch index active. Call activate() first.")
        return self._faiss

    @property
    def graph(self) -> GraphStore:
        if self._graph is None:
            raise RuntimeError("No branch index active. Call activate() first.")
        return self._graph

    @property
    def active_branch(self) -> str:
        return self._active_branch

    # ------------------------------------------------------------------
    # Delta management
    # ------------------------------------------------------------------

    def snapshot_delta(self, commit_hash: str) -> None:
        """Tag the current delta with a commit hash."""
        if not self._active_branch:
            return
        branch_dir = self._branches_dir / _sanitize(self._active_branch)
        delta_meta = branch_dir / "delta_meta.json"
        meta = {}
        if delta_meta.exists():
            try:
                meta = json.loads(delta_meta.read_text())
            except Exception:
                pass
        commits = meta.get("commits", [])
        commits.append(commit_hash)
        meta["commits"] = commits
        meta["latest"] = commit_hash
        delta_meta.write_text(json.dumps(meta, indent=2))

    def list_branches(self) -> list[dict]:
        """List all indexed branches with basic stats."""
        results = []
        for branch_dir in self._branches_dir.iterdir():
            if not branch_dir.is_dir():
                continue
            manifest = branch_dir / ".." / ".." / branch_dir.name / "manifest.json"
            delta_meta_path = branch_dir / "delta_meta.json"
            meta = {}
            if delta_meta_path.exists():
                try:
                    meta = json.loads(delta_meta_path.read_text())
                except Exception:
                    pass
            vectors_path = branch_dir / "vectors" / "vectors.faiss"
            results.append({
                "branch":  branch_dir.name,
                "indexed": vectors_path.exists(),
                "latest_commit": meta.get("latest", "unknown"),
            })
        return results

    def on_git_checkout(self, new_branch: str) -> None:
        """Called when .git/HEAD changes — switch active branch."""
        self.activate(new_branch)


def detect_current_branch(workspace: Path) -> str:
    """Detect the current git branch."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(workspace),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip() or "main"
    except Exception:
        return "main"


def _sanitize(branch: str) -> str:
    """Make branch name safe for use as a directory name."""
    return branch.replace("/", "__").replace("\\", "__").replace(":", "_")
