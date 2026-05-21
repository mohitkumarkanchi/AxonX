"""Build the right LLM provider from config or --provider flag."""

from __future__ import annotations

import os

from .claude_provider import ClaudeProvider
from .ollama_provider import OllamaProvider
from .provider import LLMProvider


def build_provider(
    role: str,
    config,  # agent.config.Config
    override: str | None = None,
) -> LLMProvider:
    """
    role: "reasoning" | "coding" | "routing" | "summarise"
    override: "ollama" | "claude" | None  (use config default)

    Rules:
    - "routing" → ALWAYS OllamaProvider(phi3:3.8b). Never Claude.
    - "embedding" → always Ollama nomic-embed-text. Claude has no embedding API.
    - All other roles → use config[provider] unless override is set.
    - If provider=="claude" but ANTHROPIC_API_KEY not set → warn + fall back to Ollama.
    """
    # Routing and embedding are always Ollama regardless of override
    if role in ("routing", "embedding"):
        return OllamaProvider(model=config.models.routing if role == "routing" else config.models.embedding)

    # Determine backend
    if override:
        backend = override
    else:
        role_map = {
            "reasoning": config.provider.reasoning_provider,
            "coding":    config.provider.coding_provider,
            "summarise": config.provider.summarise_provider,
        }
        backend = role_map.get(role, config.provider.default)

    if backend == "claude":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("Warning: ANTHROPIC_API_KEY not set. Falling back to Ollama.")
            backend = "ollama"

    if backend == "claude":
        model_map = {
            "reasoning": config.models.claude_reasoning,
            "coding":    config.models.claude_coding,
            "summarise": config.models.claude_summarise,
        }
        return ClaudeProvider(model=model_map.get(role, config.models.claude_reasoning))

    # Ollama
    model_map = {
        "reasoning": config.models.reasoning,
        "coding":    config.models.coding,
        "summarise": config.models.routing,   # phi3 — small + fast for summarise
    }
    return OllamaProvider(model=model_map.get(role, config.models.reasoning))
