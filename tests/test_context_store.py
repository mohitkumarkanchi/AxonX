"""Tests for session persistence and context store."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from axonx.session import SessionStore
from axonx.llm.provider import Message, LLMResponse


@pytest.fixture
def store(tmp_path):
    return SessionStore(db_path=tmp_path / "test_sessions.db")


class TestSessionStore:
    def test_create_new_session(self, store):
        session = store.get_or_create("/ws/myproject", "main")
        assert session.id
        assert session.workspace_path == "/ws/myproject"
        assert session.current_branch == "main"
        assert not session.is_resumed

    def test_resume_existing_session(self, store):
        s1 = store.get_or_create("/ws/myproject", "main")
        s2 = store.get_or_create("/ws/myproject", "main")
        assert s1.id == s2.id
        assert s2.is_resumed

    def test_different_branch_different_session(self, store):
        s_main = store.get_or_create("/ws/proj", "main")
        s_feat = store.get_or_create("/ws/proj", "feature/new-auth")
        assert s_main.id != s_feat.id

    def test_save_and_retrieve_message(self, store):
        session = store.get_or_create("/ws/proj", "main")
        msg_id = store.save_message(
            session_id=session.id,
            role="user",
            content="What does auth do?",
            agent_type="rag",
        )
        assert msg_id > 0

        last = store.get_last_message(session.id)
        assert last.content == "What does auth do?"
        assert last.role == "user"

    def test_load_conversation_returns_messages(self, store):
        session = store.get_or_create("/ws/proj", "main")
        store.save_message(session.id, "user", "hello")
        store.save_message(session.id, "assistant", "hi there")
        store.save_message(session.id, "user", "how are you?")

        msgs = store.load_conversation_messages(session.id)
        assert len(msgs) == 3
        assert msgs[0].content == "hello"

    def test_save_and_get_context_snapshot(self, store):
        session = store.get_or_create("/ws/proj", "main")
        msg_id = store.save_message(session.id, "assistant", "answer")

        store.save_context_snapshot(
            message_id=msg_id,
            chunk_ids=["abc", "def"],
            skill_cards=["/ws/.agent/index/skills/auth.md"],
        )

        snapshot = store.get_context_snapshot(msg_id)
        assert snapshot is not None
        assert "abc" in snapshot["chunk_ids"]
        assert "/ws/.agent/index/skills/auth.md" in snapshot["skill_cards"]

    def test_save_and_complete_operation(self, store):
        session = store.get_or_create("/ws/proj", "main")
        op_id = store.save_operation(
            session_id=session.id,
            type="modify",
            instruction="Add logging",
            files=["auth.py", "utils.py"],
        )
        assert op_id

        pending = store.get_pending_operations(session.id)
        assert len(pending) == 1
        assert pending[0].instruction == "Add logging"

        store.complete_operation(op_id)
        pending_after = store.get_pending_operations(session.id)
        assert len(pending_after) == 0

    def test_token_usage_tracking(self, store):
        session = store.get_or_create("/ws/proj", "main")
        store.record_token_usage(session.id, "ollama", "qwen2.5:14b", 100, 50, "rag")
        store.record_token_usage(session.id, "ollama", "qwen2.5:14b", 200, 80, "codeact")

        report = store.get_token_usage_report(session.id)
        assert len(report) == 1
        assert report[0]["provider"] == "ollama"
        assert report[0]["input_tokens"] == 300
        assert report[0]["output_tokens"] == 130
        assert report[0]["calls"] == 2

    def test_list_sessions(self, store):
        store.get_or_create("/ws/proj1", "main")
        store.get_or_create("/ws/proj1", "feature/auth")
        sessions = store.list_sessions("/ws/proj1")
        assert len(sessions) == 2

    def test_delete_session(self, store):
        session = store.get_or_create("/ws/proj", "main")
        store.save_message(session.id, "user", "test")

        store.delete_session(session.id)
        sessions = store.list_sessions("/ws/proj")
        assert len(sessions) == 0

    def test_summarise_old_turns(self, store):
        session = store.get_or_create("/ws/proj", "main")

        # Add 12 turns
        for i in range(12):
            store.save_message(session.id, "user", f"question {i}")
            store.save_message(session.id, "assistant", f"answer {i}")

        mock_provider = MagicMock()
        mock_provider.chat.return_value = LLMResponse(
            content="Summary: discussed questions 0-7",
            input_tokens=100,
            output_tokens=20,
            model="phi3",
            provider="ollama",
        )

        result = store.summarise_old_turns(
            session_id=session.id,
            provider=mock_provider,
            summarise_after_turns=8,
            keep_recent_turns=4,
        )
        assert result is True
        mock_provider.chat.assert_called_once()

    def test_no_summarise_when_below_threshold(self, store):
        session = store.get_or_create("/ws/proj", "main")
        store.save_message(session.id, "user", "hi")
        store.save_message(session.id, "assistant", "hello")

        mock_provider = MagicMock()
        result = store.summarise_old_turns(
            session_id=session.id,
            provider=mock_provider,
            summarise_after_turns=8,
        )
        assert result is False
        mock_provider.chat.assert_not_called()
