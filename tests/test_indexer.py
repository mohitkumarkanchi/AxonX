"""Tests for the indexer pipeline: exclusions, parser, FAISS store, graph store."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from axonx.indexer.exclusions import ExclusionSet, discover_files, load_exclusions
from axonx.indexer.parser import parse_file, Chunk
from axonx.index.faiss_store import FAISSStore
from axonx.index.graph_store import GraphStore
from axonx.indexer.graph import extract_edges


# ------------------------------------------------------------------
# ExclusionSet tests
# ------------------------------------------------------------------

class TestExclusionSet:
    def test_excludes_directory(self):
        es = ExclusionSet(["node_modules/"])
        assert es.is_excluded(Path("/ws/node_modules/foo.js"), Path("/ws"))

    def test_excludes_extension(self):
        es = ExclusionSet(["*.pyc"])
        assert es.is_excluded(Path("/ws/src/__pycache__/foo.pyc"), Path("/ws"))
        assert not es.is_excluded(Path("/ws/src/foo.py"), Path("/ws"))

    def test_allows_normal_file(self):
        es = ExclusionSet(["node_modules/", "*.pyc"])
        assert not es.is_excluded(Path("/ws/src/main.py"), Path("/ws"))

    def test_nested_excluded_dir(self):
        es = ExclusionSet(["dist/"])
        assert es.is_excluded(Path("/ws/packages/dist/bundle.js"), Path("/ws"))


class TestDiscoverFiles:
    def test_discovers_python_files(self, tmp_path):
        (tmp_path / "a.py").write_text("print('hello')")
        (tmp_path / "b.py").write_text("x = 1")
        excluded = tmp_path / "__pycache__"
        excluded.mkdir()
        (excluded / "a.cpython-39.pyc").write_bytes(b"")

        exclusions = ExclusionSet(["__pycache__/", "*.pyc"])
        files = discover_files(tmp_path, exclusions)

        file_names = [f.name for f in files]
        assert "a.py" in file_names
        assert "b.py" in file_names
        assert "a.cpython-39.pyc" not in file_names

    def test_load_exclusions_from_file(self, tmp_path):
        (tmp_path / ".agentignore").write_text("*.log\nbuild/\n")
        (tmp_path / "app.py").write_text("pass")
        (tmp_path / "debug.log").write_text("log")
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        (build_dir / "output.js").write_text("// output")

        exclusions = load_exclusions(tmp_path)
        files = discover_files(tmp_path, exclusions)
        names = [f.name for f in files]
        assert "app.py" in names
        assert "debug.log" not in names
        assert "output.js" not in names


# ------------------------------------------------------------------
# Parser tests
# ------------------------------------------------------------------

class TestParser:
    def test_parse_python_functions(self, tmp_path):
        code = '''
def foo(x):
    return x + 1

def bar(y):
    return y * 2

class MyClass:
    def method(self):
        pass
'''
        f = tmp_path / "test_module.py"
        f.write_text(code)
        chunks = parse_file(f)

        symbols = [c.symbol for c in chunks]
        assert "foo" in symbols or any("foo" in s for s in symbols)
        assert len(chunks) > 0

    def test_parse_unsupported_extension(self, tmp_path):
        f = tmp_path / "readme.md"
        f.write_text("# Hello World\nThis is a test.")
        chunks = parse_file(f)
        assert len(chunks) == 1
        assert chunks[0].kind == "module"

    def test_chunk_has_required_fields(self, tmp_path):
        f = tmp_path / "sample.py"
        f.write_text("def my_func():\n    pass\n")
        chunks = parse_file(f)
        for chunk in chunks:
            assert isinstance(chunk.id, str)
            assert len(chunk.id) > 0
            assert isinstance(chunk.content, str)
            assert isinstance(chunk.start_line, int)

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.py"
        f.write_text("")
        chunks = parse_file(f)
        # Should handle gracefully
        assert isinstance(chunks, list)


# ------------------------------------------------------------------
# FAISS store tests
# ------------------------------------------------------------------

class TestFAISSStore:
    def test_upsert_and_query(self, tmp_path):
        store = FAISSStore(tmp_path / "vectors")
        vec = [0.1] * 768

        store.upsert(
            chunk_id="abc123def456789",
            vector=vec,
            metadata={
                "filepath":   "/ws/foo.py",
                "symbol":     "my_func",
                "kind":       "function",
                "start_line": 1,
                "end_line":   5,
                "content":    "def my_func(): pass",
                "language":   "python",
                "file_hash":  "deadbeef",
            },
        )

        results = store.query(vec, top_k=1)
        assert len(results) == 1
        assert results[0]["symbol"] == "my_func"
        store.close()

    def test_delete_by_filepath(self, tmp_path):
        store = FAISSStore(tmp_path / "vectors")
        vec = [0.2] * 768

        store.upsert("id0000000000000", vec, {"filepath": "/ws/a.py", "symbol": "f", "kind": "function", "start_line": 1, "end_line": 3, "content": "...", "language": "python", "file_hash": ""})
        assert store.count() == 1

        store.delete_by_filepath("/ws/a.py")
        assert store.count() == 0
        store.close()

    def test_upsert_overwrites(self, tmp_path):
        store = FAISSStore(tmp_path / "vectors")
        vec = [0.5] * 768
        meta = {"filepath": "/x.py", "symbol": "f", "kind": "function", "start_line": 1, "end_line": 2, "content": "old", "language": "python", "file_hash": "v1"}

        store.upsert("aaaaaaaaaaaaaaa", vec, meta)
        meta2 = dict(meta)
        meta2["content"] = "new"
        meta2["file_hash"] = "v2"
        store.upsert("aaaaaaaaaaaaaaa", vec, meta2)

        results = store.get_by_filepath("/x.py")
        assert len(results) == 1
        assert results[0]["content"] == "new"
        store.close()


# ------------------------------------------------------------------
# Graph store tests
# ------------------------------------------------------------------

class TestGraphStore:
    def test_insert_and_query_edges(self, tmp_path):
        db = GraphStore(tmp_path / "graph.db")
        db.insert_edge("foo", "/a.py", "CALLS", "bar", "/b.py")
        db.insert_edge("baz", "/c.py", "IMPORTS", "utils", "")

        callers = db.get_callers("bar")
        assert len(callers) == 1
        assert callers[0]["src_symbol"] == "foo"

        imports = db.get_imports("/c.py")
        assert len(imports) == 1
        assert imports[0]["tgt_symbol"] == "utils"
        db.close()

    def test_delete_by_file(self, tmp_path):
        db = GraphStore(tmp_path / "graph.db")
        db.insert_edge("f1", "/a.py", "CALLS", "f2", "/b.py")
        db.insert_edge("f3", "/a.py", "CALLS", "f4", "/c.py")
        db.delete_by_file("/a.py")

        callees = db.get_callees("f1", "/a.py")
        assert len(callees) == 0
        db.close()

    def test_neighbourhood(self, tmp_path):
        db = GraphStore(tmp_path / "graph.db")
        db.insert_edge("A", "/a.py", "CALLS", "B", "/b.py")
        db.insert_edge("B", "/b.py", "CALLS", "C", "/c.py")

        edges = db.symbol_neighbourhood("A", depth=2)
        symbols = {e["src_symbol"] for e in edges} | {e["tgt_symbol"] for e in edges}
        assert "A" in symbols
        assert "B" in symbols
        db.close()
