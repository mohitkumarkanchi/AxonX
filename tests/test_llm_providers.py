"""Tests for LLM provider abstraction layer."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from axonx.llm.provider import Message, LLMResponse
from axonx.llm.token_counter import count_tokens_tiktoken, trim_to_budget


# ------------------------------------------------------------------
# Token counter tests (no network needed)
# ------------------------------------------------------------------

class TestTokenCounter:
    def test_count_tiktoken_basic(self):
        msgs = [
            Message(role="user", content="Hello world"),
            Message(role="assistant", content="Hi there!"),
        ]
        count = count_tokens_tiktoken(msgs)
        assert count > 0
        assert isinstance(count, int)

    def test_count_tiktoken_empty(self):
        count = count_tokens_tiktoken([])
        assert count == 0

    def test_trim_to_budget_no_trim_needed(self):
        msgs = [Message(role="user", content="short")]
        result = trim_to_budget(msgs, budget=10_000)
        assert result == msgs

    def test_trim_to_budget_trims(self):
        msgs = [
            Message(role="user", content="a" * 1000),
            Message(role="assistant", content="b" * 1000),
            Message(role="user", content="c" * 1000),
            Message(role="assistant", content="d" * 1000),
            Message(role="user", content="latest question"),
        ]
        result = trim_to_budget(msgs, budget=200, keep_first=0)
        # The result should be shorter
        assert len(result) < len(msgs)
        # Last message should be preserved
        assert result[-1].content == "latest question"


# ------------------------------------------------------------------
# OllamaProvider tests (mocked HTTP)
# ------------------------------------------------------------------

class TestOllamaProvider:
    def test_chat_success(self):
        from axonx.llm.ollama_provider import OllamaProvider

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {"content": "Hello from Ollama!"},
            "prompt_eval_count": 10,
            "eval_count": 5,
        }

        with patch("requests.post", return_value=mock_response) as mock_post:
            provider = OllamaProvider(model="phi3:3.8b")
            result = provider.chat([Message(role="user", content="Hi")])

        assert result.content == "Hello from Ollama!"
        assert result.provider == "ollama"
        assert result.model == "phi3:3.8b"
        assert result.input_tokens == 10
        assert result.output_tokens == 5

    def test_embed(self):
        from axonx.llm.ollama_provider import OllamaProvider

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"embedding": [0.1] * 768}

        with patch("requests.post", return_value=mock_response):
            provider = OllamaProvider()
            vec = provider.embed("test text")

        assert len(vec) == 768
        assert all(isinstance(v, float) for v in vec)

    def test_stream_yields_tokens(self):
        import json
        from axonx.llm.ollama_provider import OllamaProvider

        tokens = [
            json.dumps({"message": {"content": "tok1"}}).encode(),
            json.dumps({"message": {"content": " tok2"}}).encode(),
            json.dumps({"message": {"content": ""}}).encode(),
        ]

        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.raise_for_status = MagicMock()
        mock_resp.iter_lines = MagicMock(return_value=iter(tokens))

        with patch("requests.post", return_value=mock_resp):
            provider = OllamaProvider()
            results = list(provider.stream([Message(role="user", content="hi")]))

        assert results == ["tok1", " tok2"]

    def test_fallback_resolver(self):
        from axonx.llm.ollama_provider import OllamaProvider

        # Mock /api/tags returning nomic-embed-text and phi3:3.8b
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "models": [
                {"name": "nomic-embed-text:latest"},
                {"name": "phi3:3.8b"},
            ]
        }

        with patch("requests.get", return_value=mock_response):
            # When requesting qwen2.5-coder:14b, it should resolve and fallback to phi3:3.8b
            provider = OllamaProvider(model="qwen2.5-coder:14b")
            assert provider.model == "phi3:3.8b"

            # When requesting a direct match, it should remain that match
            provider2 = OllamaProvider(model="nomic-embed-text:latest")
            assert provider2.model == "nomic-embed-text:latest"

            # Normalized match
            provider3 = OllamaProvider(model="phi3")
            assert provider3.model == "phi3:3.8b"


# ------------------------------------------------------------------
# ClaudeProvider tests (mocked SDK)
# ------------------------------------------------------------------

class TestClaudeProvider:
    def test_chat_success(self):
        import os
        from axonx.llm.claude_provider import ClaudeProvider

        mock_client = MagicMock()
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text="Claude response")]
        mock_msg.usage.input_tokens = 20
        mock_msg.usage.output_tokens = 10
        mock_client.messages.create.return_value = mock_msg

        with patch("anthropic.Anthropic", return_value=mock_client):
            os.environ["ANTHROPIC_API_KEY"] = "test-key"
            provider = ClaudeProvider(model="claude-sonnet-4-5")
            result = provider.chat([Message(role="user", content="Hi Claude")])

        assert result.content == "Claude response"
        assert result.provider == "claude"
        assert result.input_tokens == 20
        assert result.output_tokens == 10

    def test_is_available_no_key(self, monkeypatch):
        import os
        from axonx.llm.claude_provider import ClaudeProvider
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert not ClaudeProvider.is_available()


# ------------------------------------------------------------------
# Factory tests
# ------------------------------------------------------------------

class TestFactory:
    def test_routing_always_ollama(self):
        from axonx.config import Config
        from axonx.llm.factory import build_provider
        from axonx.llm.ollama_provider import OllamaProvider

        config = Config()
        config.provider.default = "claude"  # even if claude is default
        provider = build_provider("routing", config)
        assert isinstance(provider, OllamaProvider)

    def test_embedding_always_ollama(self):
        from axonx.config import Config
        from axonx.llm.factory import build_provider
        from axonx.llm.ollama_provider import OllamaProvider

        config = Config()
        config.provider.default = "claude"
        provider = build_provider("embedding", config)
        assert isinstance(provider, OllamaProvider)

    def test_reasoning_ollama(self):
        from axonx.config import Config
        from axonx.llm.factory import build_provider
        from axonx.llm.ollama_provider import OllamaProvider

        config = Config()
        config.provider.default = "ollama"
        provider = build_provider("reasoning", config)
        assert isinstance(provider, OllamaProvider)

    def test_claude_fallback_without_key(self, monkeypatch):
        import os
        from axonx.config import Config
        from axonx.llm.factory import build_provider
        from axonx.llm.ollama_provider import OllamaProvider

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        config = Config()
        config.provider.default = "claude"
        provider = build_provider("reasoning", config)
        assert isinstance(provider, OllamaProvider)
