"""
SQLite-backed directed graph store for symbol relationships.

Schema mirrors a property graph:
  nodes  — one row per (symbol, file) pair
  edges  — directed (source) → (target) with a relation label

This replaces LadybugDB/GitNexus with a portable embedded implementation.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


class GraphStore:
    """Persistent SQLite graph for call/import/inheritance relationships."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._bootstrap()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _bootstrap(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS nodes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol      TEXT NOT NULL,
                file_path   TEXT NOT NULL,
                kind        TEXT,
                UNIQUE(symbol, file_path)
            );

            CREATE TABLE IF NOT EXISTS edges (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                src_symbol  TEXT NOT NULL,
                src_file    TEXT NOT NULL,
                relation    TEXT NOT NULL,
                tgt_symbol  TEXT NOT NULL,
                tgt_file    TEXT NOT NULL DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_edge_src  ON edges(src_file);
            CREATE INDEX IF NOT EXISTS idx_edge_tgt  ON edges(tgt_symbol);
            CREATE INDEX IF NOT EXISTS idx_node_file ON nodes(file_path);
            CREATE INDEX IF NOT EXISTS idx_node_sym  ON nodes(symbol);
        """)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def upsert_node(self, symbol: str, file_path: str, kind: str = "") -> None:
        self._conn.execute(
            """INSERT INTO nodes(symbol, file_path, kind)
               VALUES (?, ?, ?)
               ON CONFLICT(symbol, file_path) DO UPDATE SET kind=excluded.kind""",
            (symbol, file_path, kind),
        )
        self._conn.commit()

    def insert_edge(
        self,
        src_symbol: str,
        src_file: str,
        relation: str,
        tgt_symbol: str,
        tgt_file: str = "",
    ) -> None:
        self._conn.execute(
            """INSERT INTO edges(src_symbol, src_file, relation, tgt_symbol, tgt_file)
               VALUES (?, ?, ?, ?, ?)""",
            (src_symbol, src_file, relation, tgt_symbol, tgt_file),
        )
        self._conn.commit()

    def insert_edges_bulk(self, edges: list) -> None:
        """Bulk insert GraphEdge objects."""
        rows = [
            (e.source_symbol, e.source_file, e.relation, e.target_symbol, e.target_file)
            for e in edges
        ]
        self._conn.executemany(
            """INSERT INTO edges(src_symbol, src_file, relation, tgt_symbol, tgt_file)
               VALUES (?, ?, ?, ?, ?)""",
            rows,
        )
        self._conn.commit()

    def delete_by_file(self, file_path: str) -> None:
        """Remove all nodes and edges for a given source file."""
        self._conn.execute("DELETE FROM nodes WHERE file_path = ?", (file_path,))
        self._conn.execute("DELETE FROM edges WHERE src_file = ?", (file_path,))
        self._conn.commit()

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_callers(self, symbol: str) -> list[dict]:
        """Who calls this symbol?"""
        rows = self._conn.execute(
            "SELECT * FROM edges WHERE tgt_symbol = ? AND relation = 'CALLS'",
            (symbol,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_callees(self, symbol: str, file_path: str = "") -> list[dict]:
        """What does this symbol call?"""
        if file_path:
            rows = self._conn.execute(
                "SELECT * FROM edges WHERE src_symbol = ? AND src_file = ? AND relation = 'CALLS'",
                (symbol, file_path),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM edges WHERE src_symbol = ? AND relation = 'CALLS'",
                (symbol,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_imports(self, file_path: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM edges WHERE src_file = ? AND relation = 'IMPORTS'",
            (file_path,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_subclasses(self, class_name: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM edges WHERE tgt_symbol = ? AND relation = 'INHERITS'",
            (class_name,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_symbols_in_file(self, file_path: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM nodes WHERE file_path = ?", (file_path,)
        ).fetchall()
        return [dict(r) for r in rows]

    def symbol_neighbourhood(self, symbol: str, depth: int = 1) -> list[dict]:
        """
        BFS up to `depth` hops from symbol.
        Returns all edges encountered.
        """
        visited: set[str] = set()
        frontier = {symbol}
        all_edges: list[dict] = []

        for _ in range(depth):
            next_frontier: set[str] = set()
            for sym in frontier:
                if sym in visited:
                    continue
                visited.add(sym)
                rows = self._conn.execute(
                    "SELECT * FROM edges WHERE src_symbol = ? OR tgt_symbol = ?",
                    (sym, sym),
                ).fetchall()
                for r in rows:
                    d = dict(r)
                    if d not in all_edges:
                        all_edges.append(d)
                    next_frontier.add(r["src_symbol"])
                    next_frontier.add(r["tgt_symbol"])
            frontier = next_frontier - visited

        return all_edges

    def stats(self) -> dict:
        node_count = self._conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        edge_count = self._conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        return {"nodes": node_count, "edges": edge_count}

    def close(self) -> None:
        self._conn.close()
