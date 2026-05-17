"""Ollama LLM backend — chat + completion via /api/chat."""

from __future__ import annotations

import json
from typing import Iterator

import requests

from .provider import LLMProvider, LLMResponse, Message


class OllamaProvider(LLMProvider):
    BASE_URL = "http://localhost:11434"

    def __init__(self, model: str = "qwen2.5:14b") -> None:
        self.model = self._resolve_model(model)

    def _resolve_model(self, model: str) -> str:
        """
        Query Ollama to see if the requested model is pulled.
        If not, find a suitable pulled fallback model and log a warning.
        """
        try:
            r = requests.get(f"{self.BASE_URL}/api/tags", timeout=5)
            if r.status_code != 200:
                return model

            data = r.json()
            pulled_models = [m["name"] for m in data.get("models", [])]

            def normalize(name: str) -> str:
                return name.lower().split(":")[0]

            normalized_pulled = {normalize(m): m for m in pulled_models}
            requested_norm = normalize(model)

            # 1. Direct match (exact or normalized)
            if model in pulled_models:
                return model
            if requested_norm in normalized_pulled:
                return normalized_pulled[requested_norm]

            # 2. Not found — select first available fallback
            fallbacks = [
                "qwen2.5-coder:14b", "qwen2.5-coder:7b", "qwen2.5-coder:1.5b",
                "qwen2.5:14b", "qwen2.5:7b", "llama3.2:latest", "llama3.2",
                "phi3:3.8b", "phi3", "llama3:8b", "llama3"
            ]
            for fb in fallbacks:
                fb_norm = normalize(fb)
                if fb in pulled_models:
                    print(f"Warning: Ollama model '{model}' is not pulled. Seamlessly falling back to '{fb}'.")
                    return fb
                if fb_norm in normalized_pulled:
                    resolved = normalized_pulled[fb_norm]
                    print(f"Warning: Ollama model '{model}' is not pulled. Seamlessly falling back to '{resolved}'.")
                    return resolved

            # 3. Ultimate fallback — first loaded model that is NOT an embedding model
            for pm in pulled_models:
                if "embed" not in pm.lower() and "mxbai" not in pm.lower():
                    print(f"Warning: Ollama model '{model}' is not pulled. Seamlessly falling back to '{pm}'.")
                    return pm

            # 4. Absolutely nothing found, keep original
            return model
        except Exception:
            return model

    def chat(
        self,
        messages: list[Message],
        system: str = "",
        max_tokens: int = 2048,
    ) -> LLMResponse:
        payload = {
            "model": self.model,
            "messages": self._format(messages, system),
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
        r = requests.post(
            f"{self.BASE_URL}/api/chat",
            json=payload,
            timeout=120,
        )
        r.raise_for_status()
        data = r.json()
        return LLMResponse(
            content=data["message"]["content"],
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
            model=self.model,
            provider="ollama",
        )

    def stream(
        self,
        messages: list[Message],
        system: str = "",
        max_tokens: int = 2048,
    ) -> Iterator[str]:
        payload = {
            "model": self.model,
            "messages": self._format(messages, system),
            "stream": True,
            "options": {"num_predict": max_tokens},
        }
        with requests.post(
            f"{self.BASE_URL}/api/chat",
            json=payload,
            stream=True,
            timeout=120,
        ) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if line:
                    chunk = json.loads(line)
                    if token := chunk.get("message", {}).get("content", ""):
                        yield token

    def count_tokens(self, messages: list[Message]) -> int:
        # Ollama has no token-count endpoint — approximate via tiktoken cl100k_base
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            return sum(len(enc.encode(m.content)) for m in messages)
        except ImportError:
            # Rough fallback: ~4 chars per token
            return sum(len(m.content) // 4 for m in messages)

    def _format(self, messages: list[Message], system: str) -> list[dict]:
        result: list[dict] = []
        if system:
            result.append({"role": "system", "content": system})
        result += [{"role": m.role, "content": m.content} for m in messages]
        return result

    def is_available(self) -> bool:
        """Check if the Ollama server is reachable."""
        try:
            r = requests.get(f"{self.BASE_URL}/api/tags", timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def embed(self, text: str, model: str = "nomic-embed-text") -> list[float]:
        """Generate an embedding vector for text."""
        payload = {"model": model, "prompt": text}
        r = requests.post(
            f"{self.BASE_URL}/api/embeddings",
            json=payload,
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["embedding"]

    def embed_batch(self, texts: list[str], model: str = "nomic-embed-text") -> list[list[float]]:
        """Embed multiple texts sequentially (Ollama has no batch endpoint)."""
        return [self.embed(t, model=model) for t in texts]
