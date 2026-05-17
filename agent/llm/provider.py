"""Base LLM provider interface — all backends implement this."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator


@dataclass
class Message:
    role: str     # "user" | "assistant" | "system"
    content: str


@dataclass
class LLMResponse:
    content: str
    input_tokens: int
    output_tokens: int
    model: str
    provider: str  # "ollama" | "claude"


class LLMProvider(ABC):
    """Unified interface for all LLM backends."""

    @abstractmethod
    def chat(
        self,
        messages: list[Message],
        system: str = "",
        max_tokens: int = 2048,
    ) -> LLMResponse:
        """Single-shot completion."""

    @abstractmethod
    def stream(
        self,
        messages: list[Message],
        system: str = "",
        max_tokens: int = 2048,
    ) -> Iterator[str]:
        """Streaming token-by-token — for chat UI."""

    @abstractmethod
    def count_tokens(self, messages: list[Message]) -> int:
        """Estimate token count before sending — for context trimming."""
