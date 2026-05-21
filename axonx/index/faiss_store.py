"""
FAISS-backed vector store with SQLite metadata sidecar.

FAISS stores the raw float32 vectors; SQLite stores chunk metadata
(filepath, symbol, kind, lines, content) keyed by the same integer index.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


try:
    import faiss
    _HAS_FAISS = True
except ImportError:
    _HAS_FAISS = False

EMBED_DIM = 768  # nomic-embed-text


class FAISSStore:
    """Persistent FAISS flat-L2 index + SQLite metadata."""

    def __init__(self, index_dir: str | Path) -> None:
        self._dir = Path(index_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._dir / "vectors.faiss"
        self._db_path = self._dir / "metadata.db"
        self._index = self._load_or_create_index()
        self._db = self._open_db()

    # ------------------------------------------------------------------
    # Index lifecycle
    # ------------------------------------------------------------------

    def _load_or_create_index(self):
        if not _HAS_FAISS:
            raise RuntimeError("faiss-cpu is not installed. Run: pip install faiss-cpu")
        if self._index_path.exists():
            return faiss.read_index(str(self._index_path))
        return faiss.IndexIDMap(faiss.IndexFlatL2(EMBED_DIM))

    def _open_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                faiss_id    INTEGER PRIMARY KEY,
                chunk_id    TEXT NOT NULL UNIQUE,
                filepath    TEXT NOT NULL,
                symbol      TEXT NOT NULL,
                kind        TEXT NOT NULL,
                start_line  INTEGER,
                end_line    INTEGER,
                content     TEXT,
                language    TEXT,
                file_hash   TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_filepath ON chunks(filepath)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chunk_id ON chunks(chunk_id)")
        conn.commit()
        return conn

    def _save_index(self) -> None:
        if _HAS_FAISS:
            faiss.write_index(self._index, str(self._index_path))

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def upsert(
        self,
        chunk_id: str,
        vector: list[float],
        metadata: dict[str, Any],
    ) -> None:
        """Insert or replace a chunk vector + metadata."""
        import numpy as np

        # Assign a stable int ID derived from chunk_id (FAISS requires int64 IDs)
        faiss_id = _str_to_int64(chunk_id)

        # Remove old vector if present
        existing = self._db.execute(
            "SELECT faiss_id FROM chunks WHERE chunk_id = ?", (chunk_id,)
        ).fetchone()
        if existing:
            self._index.remove_ids(np.array([existing["faiss_id"]], dtype=np.int64))
            self._db.execute("DELETE FROM chunks WHERE chunk_id = ?", (chunk_id,))

        vec = np.array([vector], dtype=np.float32)
        self._index.add_with_ids(vec, np.array([faiss_id], dtype=np.int64))

        self._db.execute(
            """INSERT INTO chunks
               (faiss_id, chunk_id, filepath, symbol, kind, start_line, end_line,
                content, language, file_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                faiss_id,
                chunk_id,
                metadata.get("filepath", ""),
                metadata.get("symbol", ""),
                metadata.get("kind", ""),
                metadata.get("start_line"),
                metadata.get("end_line"),
                metadata.get("content", ""),
                metadata.get("language", ""),
                metadata.get("file_hash", ""),
            ),
        )
        self._db.commit()
        self._save_index()

    def delete_by_filepath(self, filepath: str) -> int:
        """Remove all chunks for a given file. Returns count deleted."""
        import numpy as np

        rows = self._db.execute(
            "SELECT faiss_id FROM chunks WHERE filepath = ?", (filepath,)
        ).fetchall()
        if not rows:
            return 0
        ids = np.array([r["faiss_id"] for r in rows], dtype=np.int64)
        self._index.remove_ids(ids)
        self._db.execute("DELETE FROM chunks WHERE filepath = ?", (filepath,))
        self._db.commit()
        self._save_index()
        return len(rows)

    # ------------------------------------------------------------------
    # Query operations
    # ------------------------------------------------------------------

    def query(
        self,
        vector: list[float],
        top_k: int = 8,
        filepath_filter: str | None = None,
    ) -> list[dict]:
        """Semantic nearest-neighbour search. Returns top_k chunks with metadata."""
        import numpy as np

        if self._index.ntotal == 0:
            return []

        k = min(top_k * 3, self._index.ntotal)  # over-fetch for post-filter
        vec = np.array([vector], dtype=np.float32)
        distances, faiss_ids = self._index.search(vec, k)

        results = []
        for dist, fid in zip(distances[0], faiss_ids[0]):
            if fid == -1:
                continue
            row = self._db.execute(
                "SELECT * FROM chunks WHERE faiss_id = ?", (int(fid),)
            ).fetchone()
            if row is None:
                continue
            if filepath_filter and row["filepath"] != filepath_filter:
                continue
            results.append({
                "chunk_id":   row["chunk_id"],
                "filepath":   row["filepath"],
                "symbol":     row["symbol"],
                "kind":       row["kind"],
                "start_line": row["start_line"],
                "end_line":   row["end_line"],
                "content":    row["content"],
                "language":   row["language"],
                "score":      float(dist),
            })
            if len(results) >= top_k:
                break

        return results

    def get_by_filepath(self, filepath: str) -> list[dict]:
        """Retrieve all chunks for a file."""
        rows = self._db.execute(
            "SELECT * FROM chunks WHERE filepath = ?", (filepath,)
        ).fetchall()
        return [dict(r) for r in rows]

    def count(self) -> int:
        return self._index.ntotal

    def close(self) -> None:
        self._save_index()
        self._db.close()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _str_to_int64(s: str) -> int:
    """Convert any string chunk_id to a stable positive int64 via SHA-256."""
    import hashlib
    digest = hashlib.sha256(s.encode()).digest()
    val = int.from_bytes(digest[:8], "big")
    return val & 0x7FFFFFFFFFFFFFFF
