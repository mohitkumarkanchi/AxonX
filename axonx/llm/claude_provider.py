"""Claude API backend — anthropic SDK with streaming and prompt caching support."""

from __future__ import annotations

import os
from typing import Iterator

import anthropic

from .provider import LLMProvider, LLMResponse, Message

_NOT_GIVEN = anthropic.NOT_GIVEN


def _build_system_with_cache(system: str) -> list[dict] | anthropic.NotGiven:
    """Wrap system prompt with cache_control so it is cached across calls."""
    if not system:
        return _NOT_GIVEN
    return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]


def _build_messages_with_cache(messages: list[Message]) -> list[dict]:
    """
    Convert Message list to Anthropic format, marking the last user message that
    contains a large code-context block for caching. The final user turn (the
    actual question) is intentionally left uncached so every unique question is
    a cache miss while the context prefix is a cache hit.
    """
    result = [{"role": m.role, "content": m.content} for m in messages]

    # Find the last user message that contains a code context block — mark it cached.
    # The heuristic: any user message whose content starts with "Context:\n" is the
    # RAG context injection. Cache that one because it's large and repeated.
    for i in range(len(result) - 2, -1, -1):
        if result[i]["role"] == "user" and result[i]["content"].startswith("Context:\n"):
            result[i] = {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": result[i]["content"],
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            }
            break

    return result


class ClaudeProvider(LLMProvider):
    """Requires ANTHROPIC_API_KEY environment variable."""

    def __init__(self, model: str = "claude-sonnet-4-6") -> None:
        self.model = model
        self.client = anthropic.Anthropic()

    def chat(
        self,
        messages: list[Message],
        system: str = "",
        max_tokens: int = 2048,
    ) -> LLMResponse:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=_build_system_with_cache(system),
            messages=_build_messages_with_cache(messages),
        )
        return LLMResponse(
            content=response.content[0].text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=self.model,
            provider="claude",
        )

    def stream(
        self,
        messages: list[Message],
        system: str = "",
        max_tokens: int = 2048,
    ) -> Iterator[str]:
        with self.client.messages.stream(
            model=self.model,
            max_tokens=max_tokens,
            system=_build_system_with_cache(system),
            messages=_build_messages_with_cache(messages),
        ) as stream:
            for text in stream.text_stream:
                yield text

    def count_tokens(self, messages: list[Message]) -> int:
        """Use Anthropic's exact token counting endpoint."""
        response = self.client.messages.count_tokens(
            model=self.model,
            messages=[{"role": m.role, "content": m.content} for m in messages],
        )
        return response.input_tokens

    @staticmethod
    def is_available() -> bool:
        return bool(os.environ.get("ANTHROPIC_API_KEY"))
