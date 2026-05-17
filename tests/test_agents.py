"""Tests for agent modules (RAG, CodeAct, Version, Orchestrator)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.llm.provider import Message, LLMResponse
from agent.agents.base import AgentResult


def _make_llm_response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        input_tokens=10,
        output_tokens=5,
        model="qwen2.5:14b",
        provider="ollama",
    )


def _make_mock_faiss(results=None):
    mock = MagicMock()
    mock.query.return_value = results or [
        {
            "chunk_id":   "abc123",
            "filepath":   "/ws/auth.py",
            "symbol":     "authenticate",
            "kind":       "function",
            "start_line": 10,
            "end_line":   25,
            "content":    "def authenticate(user): ...",
            "score":      0.05,
        }
    ]
    return mock


def _make_mock_graph():
    mock = MagicMock()
    mock.symbol_neighbourhood.return_value = []
    return mock


def _make_config(tmp_path):
    from agent.config import Config
    config = Config()
    config.workspace_path = tmp_path
    config.agent_dir = tmp_path / ".agent"
    config.provider.default = "ollama"
    config.models.embedding = "nomic-embed-text"
    return config


class TestRagAgent:
    def test_run_returns_result(self, tmp_path):
        from agent.agents.rag_agent import RagAgent

        config = _make_config(tmp_path)
        faiss = _make_mock_faiss()
        graph = _make_mock_graph()

        mock_provider = MagicMock()
        mock_provider.chat.return_value = _make_llm_response("The authenticate function verifies user credentials.")

        agent = RagAgent(config, faiss, graph)
        agent._provider = mock_provider

        with patch("agent.agents.rag_agent.embed_text", return_value=[0.1] * 768):
            result = agent.run("What does authenticate do?")

        assert isinstance(result, AgentResult)
        assert result.agent_type == "rag"
        assert "authenticate" in result.content or len(result.content) > 0

    def test_run_handles_embed_failure(self, tmp_path):
        from agent.agents.rag_agent import RagAgent

        config = _make_config(tmp_path)
        faiss = _make_mock_faiss()
        graph = _make_mock_graph()

        agent = RagAgent(config, faiss, graph)

        with patch("agent.agents.rag_agent.embed_text", side_effect=Exception("Ollama down")):
            result = agent.run("test query")

        assert "Error" in result.content

    def test_rrf_merge(self):
        from agent.agents.rag_agent import _rrf_merge

        semantic = [
            {"chunk_id": "s1", "content": "a"},
            {"chunk_id": "s2", "content": "b"},
        ]
        graph = [
            {"symbol": "g1", "content": "c"},
        ]
        merged = _rrf_merge(semantic, graph, top_k=5)
        assert len(merged) <= 5
        assert any(r.get("chunk_id") == "s1" for r in merged)


class TestVersionAgent:
    def test_run_git_log(self, tmp_path):
        from agent.agents.version_agent import VersionAgent

        config = _make_config(tmp_path)
        mock_provider = MagicMock()
        mock_provider.chat.return_value = _make_llm_response("Recent commits show auth changes.")

        agent = VersionAgent(config)
        agent._provider = mock_provider

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="abc1234 fix auth bug\ndef5678 add tests\n",
                stderr="",
            )
            result = agent.run("show commit history")

        assert isinstance(result, AgentResult)
        assert result.agent_type == "version"

    def test_blocks_non_readonly_commands(self, tmp_path):
        from agent.agents.version_agent import VersionAgent

        config = _make_config(tmp_path)
        agent = VersionAgent(config)

        # Internal method should block non-read-only subcommands
        result = agent._run_git(["git", "commit", "-m", "bad"])
        assert "Blocked" in result.error

    def test_extract_file_from_query(self, tmp_path):
        from agent.agents.version_agent import VersionAgent

        config = _make_config(tmp_path)
        agent = VersionAgent(config)

        filepath = agent._extract_file("show blame for 'src/auth/middleware.py'")
        assert "middleware.py" in filepath or "src/auth/middleware.py" in filepath


class TestCodeActAgent:
    def test_dry_run_returns_plan(self, tmp_path):
        from agent.agents.codeact_agent import CodeActAgent

        config = _make_config(tmp_path)
        faiss = _make_mock_faiss()
        graph = _make_mock_graph()

        plan_json = '{"summary": "Add logging", "files": ["app.py"], "steps": [{"step": 1, "file": "app.py", "description": "Add import logging", "edit": {"old": "import os", "new": "import os\\nimport logging"}}]}'
        mock_provider = MagicMock()
        mock_provider.chat.return_value = _make_llm_response(plan_json)

        agent = CodeActAgent(config, faiss, graph)
        agent._provider = mock_provider

        with patch("agent.agents.codeact_agent.embed_text", return_value=[0.1] * 768):
            result = agent.run("Add logging to app", dry_run=True)

        assert "DRY RUN" in result.content
        assert "plan" in result.content.lower() or "Add logging" in result.content

    def test_parse_plan(self, tmp_path):
        from agent.agents.codeact_agent import CodeActAgent

        config = _make_config(tmp_path)
        faiss = _make_mock_faiss()
        graph = _make_mock_graph()
        agent = CodeActAgent(config, faiss, graph)

        raw = '{"summary": "test", "files": ["a.py"], "steps": [{"step": 1, "file": "a.py", "description": "do thing", "edit": {"old": "x", "new": "y"}}]}'
        plan = agent._parse_plan(raw)

        assert plan is not None
        assert plan.summary == "test"
        assert len(plan.steps) == 1
        assert plan.steps[0].old == "x"
        assert plan.steps[0].new == "y"

    def test_parse_plan_with_markdown_fence(self, tmp_path):
        from agent.agents.codeact_agent import CodeActAgent

        config = _make_config(tmp_path)
        faiss = _make_mock_faiss()
        graph = _make_mock_graph()
        agent = CodeActAgent(config, faiss, graph)

        raw = '```json\n{"summary": "test", "files": [], "steps": []}\n```'
        plan = agent._parse_plan(raw)
        assert plan is not None
        assert plan.summary == "test"


class TestOrchestrator:
    def test_compound_qa_then_modify(self, tmp_path):
        from agent.agents.orchestrator import Orchestrator

        config = _make_config(tmp_path)
        faiss = _make_mock_faiss()
        graph = _make_mock_graph()

        mock_response = _make_llm_response("Here is the explanation and the plan.")
        orchestrator = Orchestrator(config, faiss, graph)
        orchestrator._rag._provider = MagicMock()
        orchestrator._rag._provider.chat.return_value = mock_response

        with patch("agent.agents.rag_agent.embed_text", return_value=[0.1] * 768):
            result = orchestrator.run(
                "explain auth then add logging",
                sub_tasks=["qa"],
            )

        assert isinstance(result, AgentResult)
        assert result.agent_type == "orchestrator"
