"""
Incremental re-indexer — called on every file save event.

Per-file update steps:
1. Check if file is excluded → skip
2. Compute sha256(content) — compare to stored manifest hash
3. If unchanged → skip (no-op)
4. Re-parse with tree-sitter → new chunks
5. Delete old FAISS vectors for this file
6. Insert new vectors
7. Delete old graph edges for this file
8. Insert new graph edges
9. Update manifest file hash
10. Mark stale SKILL.md card for async regeneration

Target: < 2 seconds per file on Apple Silicon.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from ..indexer.embedder import embed_chunks
from ..indexer.exclusions import ExclusionSet
from ..indexer.graph import extract_edges
from ..indexer.parser import parse_file
from ..index.faiss_store import FAISSStore
from ..index.graph_store import GraphStore


def _hash_file(filepath: Path) -> str:
    h = hashlib.sha256()
    try:
        h.update(filepath.read_bytes())
    except OSError:
        pass
    return h.hexdigest()


def _load_manifest(index_dir: Path) -> dict:
    mp = index_dir / "manifest.json"
    if mp.exists():
        try:
            return json.loads(mp.read_text())
        except Exception:
            pass
    return {}


def _save_manifest(index_dir: Path, manifest: dict) -> None:
    mp = index_dir / "manifest.json"
    mp.write_text(json.dumps(manifest, indent=2))


class IncrementalIndexer:
    """Handles per-file incremental index updates."""

    def __init__(
        self,
        index_dir: Path,
        workspace_root: Path,
        exclusions: ExclusionSet,
        embed_model: str = "nomic-embed-text",
    ) -> None:
        self._index_dir = index_dir
        self._workspace = workspace_root
        self._exclusions = exclusions
        self._embed_model = embed_model
        self._faiss = FAISSStore(index_dir / "vectors")
        self._graph = GraphStore(index_dir / "graph.db")
        self._manifest = _load_manifest(index_dir)
        self._stale_modules: set[str] = set()

    def update_file(self, filepath: str | Path) -> bool:
        """
        Re-index a single file.
        Returns True if the index was updated, False if skipped.
        """
        filepath = Path(filepath).resolve()

        # 1. Exclusion check
        if self._exclusions.is_excluded(filepath, self._workspace):
            return False

        # 2. Hash check
        new_hash = _hash_file(filepath)
        stored_hashes = self._manifest.get("file_hashes", {})
        if stored_hashes.get(str(filepath)) == new_hash:
            return False  # unchanged

        t0 = time.time()

        # 3. Re-parse
        chunks = parse_file(filepath)

        # 4. Remove old FAISS vectors
        self._faiss.delete_by_filepath(str(filepath))

        # 5. Embed and insert new vectors
        if chunks:
            try:
                chunk_vecs = embed_chunks(chunks, model=self._embed_model)
                for chunk, vec in chunk_vecs:
                    self._faiss.upsert(
                        chunk_id=chunk.id,
                        vector=vec,
                        metadata={
                            "filepath":   chunk.filepath,
                            "symbol":     chunk.symbol,
                            "kind":       chunk.kind,
                            "start_line": chunk.start_line,
                            "end_line":   chunk.end_line,
                            "content":    chunk.content,
                            "language":   chunk.language,
                            "file_hash":  new_hash,
                        },
                    )
            except Exception as exc:
                print(f"[incremental] Embed error for {filepath}: {exc}")

        # 6-7. Remove old graph edges, insert new ones
        self._graph.delete_by_file(str(filepath))
        try:
            edges = extract_edges(filepath)
            if edges:
                self._graph.insert_edges_bulk(edges)
                for chunk in chunks:
                    self._graph.upsert_node(chunk.symbol, str(filepath), chunk.kind)
        except Exception as exc:
            print(f"[incremental] Graph error for {filepath}: {exc}")

        # 8. Update manifest hash
        stored_hashes[str(filepath)] = new_hash
        self._manifest["file_hashes"] = stored_hashes
        _save_manifest(self._index_dir, self._manifest)

        # 9. Mark SKILL.md stale for this module
        try:
            rel = filepath.relative_to(self._workspace)
            top_module = rel.parts[0] if len(rel.parts) > 1 else str(rel)
            self._stale_modules.add(top_module)
        except ValueError:
            pass

        elapsed = time.time() - t0
        print(f"[incremental] Updated {filepath.name} in {elapsed:.2f}s "
              f"({len(chunks)} chunks)")
        return True

    def delete_file(self, filepath: str | Path) -> None:
        """Remove a deleted file from the index."""
        filepath = Path(filepath).resolve()
        self._faiss.delete_by_filepath(str(filepath))
        self._graph.delete_by_file(str(filepath))
        stored_hashes = self._manifest.get("file_hashes", {})
        stored_hashes.pop(str(filepath), None)
        self._manifest["file_hashes"] = stored_hashes
        _save_manifest(self._index_dir, self._manifest)

    @property
    def stale_modules(self) -> set[str]:
        """Modules whose SKILL.md cards need regeneration."""
        return set(self._stale_modules)

    def flush_stale_modules(self) -> set[str]:
        """Return and clear the stale modules set."""
        stale = set(self._stale_modules)
        self._stale_modules.clear()
        return stale

    def close(self) -> None:
        self._faiss.close()
        self._graph.close()
