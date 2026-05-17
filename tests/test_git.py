"""Tests for git integration modules."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.git.conflict_resolver import ConflictBlock, _parse_conflict_blocks, format_conflicts_for_chat
from agent.safety.guardrails import GuardrailError, check_operation
from agent.safety.scope_pin import ScopePin


# ------------------------------------------------------------------
# Conflict resolver tests
# ------------------------------------------------------------------

class TestConflictResolver:
    def test_parse_conflict_block(self, tmp_path):
        conflict_file = tmp_path / "merged.py"
        conflict_file.write_text(
            "def foo():\n"
            "<<<<<<< HEAD\n"
            "    return 1\n"
            "=======\n"
            "    return 2\n"
            ">>>>>>> feature/new\n"
        )
        blocks = _parse_conflict_blocks(conflict_file)
        assert len(blocks) == 1
        assert "return 1" in blocks[0].ours
        assert "return 2" in blocks[0].theirs

    def test_no_conflicts(self, tmp_path):
        clean_file = tmp_path / "clean.py"
        clean_file.write_text("def foo():\n    return 1\n")
        blocks = _parse_conflict_blocks(clean_file)
        assert len(blocks) == 0

    def test_format_conflicts_empty(self):
        text = format_conflicts_for_chat([])
        assert "No merge conflicts" in text

    def test_format_conflicts_with_blocks(self):
        blocks = [
            ConflictBlock(
                filepath="/ws/auth.py",
                ours="return 1",
                theirs="return 2",
                start_line=5,
            )
        ]
        text = format_conflicts_for_chat(blocks)
        assert "1" in text  # conflict number
        assert "auth.py" in text
        assert "OURS" in text
        assert "THEIRS" in text


# ------------------------------------------------------------------
# Guardrails tests
# ------------------------------------------------------------------

class TestGuardrails:
    def test_protected_branch_raises(self, tmp_path):
        from agent.config import Config
        config = Config()
        config.safety.protected_branches = ["main", "master"]

        with patch("agent.safety.guardrails.current_branch", return_value="main"):
            with pytest.raises(GuardrailError, match="protected branch"):
                check_operation(
                    files=["auth.py"],
                    workspace=tmp_path,
                    config=config,
                )

    def test_max_files_raises(self, tmp_path):
        from agent.config import Config
        config = Config()
        config.safety.max_files_per_operation = 3
        config.safety.protected_branches = []

        with patch("agent.safety.guardrails.current_branch", return_value="feature/test"):
            with pytest.raises(GuardrailError, match="files"):
                check_operation(
                    files=["a.py", "b.py", "c.py", "d.py"],
                    workspace=tmp_path,
                    config=config,
                )

    def test_force_bypasses_file_limit(self, tmp_path):
        from agent.config import Config
        config = Config()
        config.safety.max_files_per_operation = 3
        config.safety.protected_branches = []

        with patch("agent.safety.guardrails.current_branch", return_value="feature/test"):
            # Should not raise with force=True
            check_operation(
                files=["a.py", "b.py", "c.py", "d.py"],
                workspace=tmp_path,
                config=config,
                force=True,
            )

    def test_non_protected_branch_allowed(self, tmp_path):
        from agent.config import Config
        config = Config()
        config.safety.protected_branches = ["main", "master"]
        config.safety.max_files_per_operation = 10

        with patch("agent.safety.guardrails.current_branch", return_value="feature/auth-refactor"):
            # Should not raise
            check_operation(
                files=["auth.py"],
                workspace=tmp_path,
                config=config,
            )


# ------------------------------------------------------------------
# ScopePin tests
# ------------------------------------------------------------------

class TestScopePin:
    def test_no_scope_allows_all(self, tmp_path):
        pin = ScopePin(tmp_path)
        assert pin.is_allowed(tmp_path / "any/file.py")
        assert not pin.active

    def test_scoped_allows_within(self, tmp_path):
        subdir = tmp_path / "src"
        subdir.mkdir()
        pin = ScopePin(tmp_path)
        pin.set("src")
        assert pin.is_allowed(subdir / "main.py")

    def test_scoped_blocks_outside(self, tmp_path):
        subdir = tmp_path / "src"
        subdir.mkdir()
        (tmp_path / "other").mkdir()
        pin = ScopePin(tmp_path)
        pin.set("src")
        assert not pin.is_allowed(tmp_path / "other" / "file.py")

    def test_scope_outside_workspace_raises(self, tmp_path):
        pin = ScopePin(tmp_path)
        with pytest.raises(ValueError):
            pin.set("/completely/outside/path")

    def test_clear_removes_restriction(self, tmp_path):
        subdir = tmp_path / "src"
        subdir.mkdir()
        pin = ScopePin(tmp_path, scope_path="src")
        pin.clear()
        assert not pin.active
        assert pin.is_allowed(tmp_path / "other" / "file.py")

    def test_check_allowed_raises(self, tmp_path):
        subdir = tmp_path / "src"
        subdir.mkdir()
        (tmp_path / "tests").mkdir()
        pin = ScopePin(tmp_path, scope_path="src")
        with pytest.raises(ValueError, match="pinned scope"):
            pin.check_allowed(tmp_path / "tests" / "test_foo.py")
