"""Claude API backend — anthropic SDK with streaming support."""

from __future__ import annotations

import os
from typing import Iterator

import anthropic

from .provider import LLMProvider, LLMResponse, Message

_NOT_GIVEN = anthropic.NOT_GIVEN


class ClaudeProvider(LLMProvider):
    """Requires ANTHROPIC_API_KEY environment variable."""

    def __init__(self, model: str = "claude-sonnet-4-5") -> None:
        self.model = model
        self.client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY automatically

    def chat(
        self,
        messages: list[Message],
        system: str = "",
        max_tokens: int = 2048,
    ) -> LLMResponse:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system if system else _NOT_GIVEN,
            messages=[{"role": m.role, "content": m.content} for m in messages],
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
            system=system if system else _NOT_GIVEN,
            messages=[{"role": m.role, "content": m.content} for m in messages],
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
