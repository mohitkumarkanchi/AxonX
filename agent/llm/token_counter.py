"""Token counting utilities for both Ollama and Claude backends."""

from __future__ import annotations

from .provider import Message


def count_tokens_tiktoken(messages: list[Message]) -> int:
    """Approximate token count using tiktoken cl100k_base (good for Ollama models)."""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        total = 0
        for m in messages:
            # 4 overhead tokens per message (role + separators)
            total += 4 + len(enc.encode(m.content))
        return total
    except ImportError:
        # Rough fallback: ~4 chars per token
        return sum(4 + len(m.content) // 4 for m in messages)


def count_tokens_claude(messages: list[Message], model: str = "claude-sonnet-4-5") -> int:
    """Exact token count via Anthropic's count_tokens endpoint."""
    try:
        import anthropic
        client = anthropic.Anthropic()
        response = client.messages.count_tokens(
            model=model,
            messages=[{"role": m.role, "content": m.content} for m in messages],
        )
        return response.input_tokens
    except Exception:
        # Fallback to tiktoken approximation
        return count_tokens_tiktoken(messages)


def count_tokens(messages: list[Message], provider: str = "ollama", model: str = "") -> int:
    """Count tokens for the given provider."""
    if provider == "claude":
        return count_tokens_claude(messages, model=model or "claude-sonnet-4-5")
    return count_tokens_tiktoken(messages)


def fits_in_budget(
    messages: list[Message],
    budget: int,
    provider: str = "ollama",
    model: str = "",
) -> bool:
    """Return True if messages fit within the token budget."""
    return count_tokens(messages, provider=provider, model=model) <= budget


def trim_to_budget(
    messages: list[Message],
    budget: int,
    provider: str = "ollama",
    model: str = "",
    keep_first: int = 1,
) -> list[Message]:
    """
    Trim messages list to fit within budget by removing middle messages.
    Always keeps the first `keep_first` messages (system prompt) and last message.
    """
    if fits_in_budget(messages, budget, provider=provider, model=model):
        return messages

    result = list(messages)
    # Never drop the first keep_first messages or the last message
    while len(result) > keep_first + 1:
        # Remove the oldest message after the keep_first block
        result.pop(keep_first)
        if fits_in_budget(result, budget, provider=provider, model=model):
            break

    return result
