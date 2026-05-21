"""
File watcher — monitors the workspace and triggers incremental re-index.

Uses watchdog with a debounce to batch rapid saves.
Also watches .git/HEAD to detect branch switches.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

try:
    from watchdog.events import FileSystemEvent, FileSystemEventHandler
    from watchdog.observers import Observer
    _HAS_WATCHDOG = True
except ImportError:
    _HAS_WATCHDOG = False

from .indexer.exclusions import ExclusionSet
from .indexer.incremental import IncrementalIndexer


class _ChangeHandler(FileSystemEventHandler):
    """Debounced watchdog handler that calls back on file changes."""

    def __init__(
        self,
        indexer: IncrementalIndexer,
        exclusions: ExclusionSet,
        workspace: Path,
        debounce_ms: int,
        on_branch_change: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__()
        self._indexer = indexer
        self._exclusions = exclusions
        self._workspace = workspace
        self._debounce_s = debounce_ms / 1000.0
        self._on_branch_change = on_branch_change

        self._pending: dict[str, float] = {}
        self._lock = threading.Lock()
        self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._flush_thread.start()

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        src = event.src_path

        # Detect git HEAD change → branch switch
        if src.endswith(".git/HEAD") or src.endswith(".git\\HEAD"):
            if self._on_branch_change:
                try:
                    branch = Path(src).read_text().strip()
                    if branch.startswith("ref: refs/heads/"):
                        branch = branch.removeprefix("ref: refs/heads/")
                    self._on_branch_change(branch)
                except Exception:
                    pass
            return

        with self._lock:
            self._pending[src] = time.monotonic() + self._debounce_s

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            with self._lock:
                self._pending[event.src_path] = time.monotonic() + self._debounce_s

    def on_deleted(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            src = event.src_path
            p = Path(src)
            if not self._exclusions.is_excluded(p, self._workspace):
                self._indexer.delete_file(p)

    def _flush_loop(self) -> None:
        """Background thread that flushes pending updates after debounce."""
        while True:
            time.sleep(0.05)
            now = time.monotonic()
            ready: list[str] = []
            with self._lock:
                for path, ready_at in list(self._pending.items()):
                    if now >= ready_at:
                        ready.append(path)
                        del self._pending[path]

            for path in ready:
                try:
                    self._indexer.update_file(Path(path))
                except Exception as exc:
                    print(f"[watcher] Error updating {path}: {exc}")


class FileWatcher:
    """Manages the watchdog observer lifecycle."""

    def __init__(
        self,
        workspace: Path,
        indexer: IncrementalIndexer,
        exclusions: ExclusionSet,
        debounce_ms: int = 500,
        on_branch_change: Callable[[str], None] | None = None,
    ) -> None:
        if not _HAS_WATCHDOG:
            raise RuntimeError("watchdog is not installed. Run: pip install watchdog")

        self._workspace = workspace
        self._observer: Observer | None = None
        self._handler = _ChangeHandler(
            indexer=indexer,
            exclusions=exclusions,
            workspace=workspace,
            debounce_ms=debounce_ms,
            on_branch_change=on_branch_change,
        )

    def start(self) -> None:
        self._observer = Observer()
        self._observer.schedule(self._handler, str(self._workspace), recursive=True)
        self._observer.start()
        print(f"[watcher] Watching {self._workspace}")

    def stop(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
            print("[watcher] Stopped")

    def is_running(self) -> bool:
        return self._observer is not None and self._observer.is_alive()
