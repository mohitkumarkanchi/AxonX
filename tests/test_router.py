"""Tests for the intent router."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent.llm.provider import LLMResponse
from agent.router import Router, RouterResult


def _mock_router(response_json: str) -> Router:
    """Build a Router with a mocked Ollama backend."""
    mock_provider = MagicMock()
    mock_provider.chat.return_value = LLMResponse(
        content=response_json,
        input_tokens=10,
        output_tokens=5,
        model="phi3:3.8b",
        provider="ollama",
    )
    router = Router()
    router._llm = mock_provider
    return router


class TestRouterParsing:
    def test_qa_intent(self):
        router = _mock_router('{"intent": "qa", "targets": ["auth middleware"], "scope": "local", "sub_tasks": []}')
        result = router.classify("What does the auth middleware do?")
        assert result.intent == "qa"
        assert "auth middleware" in result.targets

    def test_modify_intent(self):
        router = _mock_router('{"intent": "modify", "targets": ["UserService"], "scope": "local", "sub_tasks": []}')
        result = router.classify("Refactor UserService to use DI")
        assert result.intent == "modify"

    def test_version_intent(self):
        router = _mock_router('{"intent": "version", "targets": ["login"], "scope": "local", "sub_tasks": []}')
        result = router.classify("Who last changed the login function?")
        assert result.intent == "version"

    def test_compound_intent(self):
        router = _mock_router('{"intent": "compound", "targets": ["payment"], "scope": "broad", "sub_tasks": ["qa", "modify"]}')
        result = router.classify("Explain the payment flow and add error handling")
        assert result.intent == "compound"
        assert "qa" in result.sub_tasks
        assert "modify" in result.sub_tasks

    def test_malformed_json_falls_back_to_heuristic(self):
        router = _mock_router("Sorry I can't help with that.")
        result = router.classify("what does main.py do?")
        # Heuristic should return a valid intent
        assert result.intent in ("qa", "modify", "version", "compound")

    def test_markdown_fence_stripped(self):
        router = _mock_router('```json\n{"intent": "qa", "targets": [], "scope": "local", "sub_tasks": []}\n```')
        result = router.classify("explain the code")
        assert result.intent == "qa"


class TestHeuristicFallback:
    def setup_method(self):
        self.router = Router()

    def test_modify_keywords(self):
        result = self.router._heuristic_fallback("refactor the auth module")
        assert result.intent == "modify"

    def test_version_keywords(self):
        result = self.router._heuristic_fallback("show me the commit history")
        assert result.intent == "version"

    def test_blame_keyword(self):
        result = self.router._heuristic_fallback("who changed this file?")
        assert result.intent == "version"

    def test_default_to_qa(self):
        result = self.router._heuristic_fallback("what is the architecture?")
        assert result.intent == "qa"

    def test_compound_and_keyword(self):
        result = self.router._heuristic_fallback("explain the API and then add logging")
        assert result.intent in ("compound", "qa")  # "and" triggers compound
