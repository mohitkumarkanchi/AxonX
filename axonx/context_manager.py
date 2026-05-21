"""
Context window manager — sliding window + summarisation + cross-session resume.

Handles two very different budgets:
- Ollama (qwen2.5:14b): ~6,000 working tokens
- Claude (sonnet-4-5): ~180,000 working tokens — pass much more context
"""

from __future__ import annotations

from .config import Config, WORKING_BUDGET
from .llm.provider import LLMProvider, Message
from .llm.token_counter import count_tokens


class ContextManager:
    """Trim and summarise conversation history to fit within token budgets."""

    def __init__(self, config: Config, provider: LLMProvider, provider_name: str) -> None:
        self._config = config
        self._provider = provider
        self._provider_name = provider_name

        # Determine budget based on provider
        if provider_name == "claude":
            self._budget = config.session.claude_context_budget
        else:
            self._budget = config.session.ollama_context_budget

    def trim(
        self,
        messages: list[Message],
        keep_recent: int | None = None,
    ) -> list[Message]:
        """
        Ensure messages fit within the working token budget.

        Strategy:
        1. Count tokens — if under budget, return as-is
        2. Keep system message (first if role=system)
        3. Keep last `keep_recent_turns` user+assistant turns always
        4. Summarise middle section using fast model (phi3 or haiku)
        5. Replace middle with summary message
        """
        if not messages:
            return messages

        n_keep = keep_recent or self._config.session.keep_recent_turns * 2

        if count_tokens(messages, provider=self._provider_name) <= self._budget:
            return messages

        if len(messages) <= n_keep + 1:
            # Can't split further — just truncate content of oldest messages
            return self._truncate_content(messages, n_keep)

        # Split: head (to summarise) + tail (to keep)
        tail = messages[-n_keep:]
        head = messages[:-n_keep]

        summary_text = self._summarise(head)
        summary_msg = Message(
            role="user",
            content=f"[Earlier conversation summary]: {summary_text}",
        )
        summary_reply = Message(
            role="assistant",
            content="Understood. Continuing from the summary.",
        )

        trimmed = [summary_msg, summary_reply] + list(tail)

        # If still too long after summarisation, truncate oldest
        if count_tokens(trimmed, provider=self._provider_name) > self._budget:
            trimmed = self._truncate_content(trimmed, n_keep)

        return trimmed

    def _summarise(self, messages: list[Message]) -> str:
        """Summarise a list of messages using the fast routing model (phi3 or haiku)."""
        from .llm.factory import build_provider

        # Always use fast/cheap model for summarisation
        summariser = build_provider("summarise", self._config)

        conversation = "\n".join(
            f"{m.role.upper()}: {m.content[:400]}" for m in messages
        )
        prompt = (
            "Summarise this conversation in 3-5 sentences. "
            "Preserve: files discussed, decisions made, code changes, unresolved questions.\n\n"
            f"{conversation}"
        )

        try:
            response = summariser.chat(
                [Message(role="user", content=prompt)],
                max_tokens=400,
            )
            return response.content
        except Exception as exc:
            # Fallback: just list the topics
            topics = " | ".join(m.content[:80] for m in messages[::2])
            return f"[Summary unavailable: {exc}] Topics: {topics}"

    def _truncate_content(
        self,
        messages: list[Message],
        keep_count: int,
    ) -> list[Message]:
        """Last-resort truncation: shorten content of older messages."""
        result = list(messages)
        # Shorten everything except the last keep_count
        for i in range(len(result) - keep_count):
            if len(result[i].content) > 200:
                result[i] = Message(
                    role=result[i].role,
                    content=result[i].content[:200] + " [truncated]",
                )
        return result

    def budget(self) -> int:
        return self._budget

    def tokens_used(self, messages: list[Message]) -> int:
        return count_tokens(messages, provider=self._provider_name)

    def tokens_remaining(self, messages: list[Message]) -> int:
        return max(0, self._budget - self.tokens_used(messages))

    def rag_top_k(self) -> int:
        """How many RAG chunks to retrieve based on context budget."""
        if self._provider_name == "claude":
            return 20  # Claude can handle much more
        return 8
