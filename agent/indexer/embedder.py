"""Embed chunks via nomic-embed-text through Ollama — always local."""

from __future__ import annotations

import requests

OLLAMA_BASE = "http://localhost:11434"
DEFAULT_EMBED_MODEL = "nomic-embed-text"
EMBED_DIM = 768  # nomic-embed-text output dimension


def embed_text(text: str, model: str = DEFAULT_EMBED_MODEL) -> list[float]:
    """Generate a single embedding vector."""
    # Cap input text to 4000 characters to avoid Ollama embedding token limit errors (400 Bad Request)
    payload = {"model": model, "input": text[:4000]}
    r = requests.post(f"{OLLAMA_BASE}/api/embed", json=payload, timeout=60)
    r.raise_for_status()
    return r.json()["embeddings"][0]


def embed_batch(texts: list[str], model: str = DEFAULT_EMBED_MODEL) -> list[list[float]]:
    """Embed multiple texts in a single batch call."""
    if not texts:
        return []
    # Cap each input text to 4000 characters to avoid Ollama embedding token limit errors (400 Bad Request)
    payload = {"model": model, "input": [t[:4000] for t in texts]}
    r = requests.post(f"{OLLAMA_BASE}/api/embed", json=payload, timeout=60)
    r.raise_for_status()
    return r.json()["embeddings"]


def embed_chunks(chunks, model: str = DEFAULT_EMBED_MODEL) -> list[tuple]:
    """
    Embed a list of Chunk objects.
    Returns list of (chunk, vector) tuples.
    """
    if not chunks:
        return []
    texts = [f"{chunk.symbol}: {chunk.content}" for chunk in chunks]
    vectors = embed_batch(texts, model=model)
    return list(zip(chunks, vectors))
