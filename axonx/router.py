"""
Intent router — phi3:3.8b via Ollama classifies every user message.

ALWAYS uses Ollama/phi3, never Claude — too expensive for high-frequency routing.

Returns a RouterResult with intent, targets, scope, and sub_tasks.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .llm.ollama_provider import OllamaProvider
from .llm.provider import Message

ROUTING_MODEL = "phi3:3.8b"

SYSTEM_PROMPT = """\
You are an intent classifier for a code agent. Given a user message, output ONLY a JSON object:
{
  "intent": one of ["qa", "modify", "version", "compound"],
  "targets": [list of file paths, function names, or class names mentioned],
  "scope": one of ["local", "broad"],
  "sub_tasks": []
}
If intent is "compound", populate sub_tasks with an ordered list of intent strings.
Output ONLY the JSON object. No explanation, no markdown, no code fences.
"""

EXAMPLES = """
Examples:
User: "What does the auth middleware do?"
-> {"intent": "qa", "targets": ["auth middleware"], "scope": "local", "sub_tasks": []}

User: "Refactor the UserService class to use dependency injection"
-> {"intent": "modify", "targets": ["UserService"], "scope": "local", "sub_tasks": []}

User: "Who last changed the login function and what did they change?"
-> {"intent": "version", "targets": ["login"], "scope": "local", "sub_tasks": []}

User: "Explain the payment flow and then add error handling to it"
-> {"intent": "compound", "targets": ["payment"], "scope": "broad", "sub_tasks": ["qa", "modify"]}
"""


@dataclass
class RouterResult:
    intent: str                    # "qa" | "modify" | "version" | "compound"
    targets: list[str] = field(default_factory=list)
    scope: str = "local"           # "local" | "broad"
    sub_tasks: list[str] = field(default_factory=list)
    raw_response: str = ""


class Router:
    """Intent classifier — uses Ollama/phi3 when available, heuristic otherwise."""

    def __init__(self, model: str = ROUTING_MODEL) -> None:
        self._llm = OllamaProvider(model=model)
        self._ollama_available: bool | None = None  # lazy-checked once per session

    def _check_ollama(self) -> bool:
        if self._ollama_available is None:
            self._ollama_available = self._llm.is_available()
            if not self._ollama_available:
                print(
                    "[router] Ollama is not running — using heuristic intent detection. "
                    "Start Ollama for more accurate routing."
                )
        return self._ollama_available

    def classify(self, message: str) -> RouterResult:
        """Classify a user message and return a RouterResult."""
        if not self._check_ollama():
            return self._heuristic_fallback(message)

        prompt = EXAMPLES + f"\nUser: \"{message}\"\n->"

        try:
            response = self._llm.chat(
                messages=[Message(role="user", content=prompt)],
                system=SYSTEM_PROMPT,
                max_tokens=256,
            )
            raw = response.content.strip()
            return self._parse(raw, message)
        except Exception as exc:
            print(f"[router] LLM error: {exc}. Falling back to heuristic.")
            self._ollama_available = False  # don't retry a broken connection
            return self._heuristic_fallback(message)

    def _parse(self, raw: str, original_message: str) -> RouterResult:
        """Parse the LLM JSON response into a RouterResult."""
        # Strip any accidental markdown fences
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        # Find first JSON object in the response
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return self._heuristic_fallback(original_message)

        try:
            data = json.loads(match.group())
            intent = data.get("intent", "qa")
            if intent not in ("qa", "modify", "version", "compound"):
                intent = "qa"
            return RouterResult(
                intent=intent,
                targets=data.get("targets", []),
                scope=data.get("scope", "local"),
                sub_tasks=data.get("sub_tasks", []),
                raw_response=raw,
            )
        except json.JSONDecodeError:
            return self._heuristic_fallback(original_message)

    def _heuristic_fallback(self, message: str) -> RouterResult:
        """Rule-based fallback when LLM output can't be parsed."""
        msg = message.lower()

        # Use word-boundary-safe substrings to avoid false positives like "changed" → modify
        has_modify = any(kw in msg for kw in (
            "refactor", "change ", "add ", "remove ", "fix ", "update ",
            "rename ", "move ", "delete ",
        ))
        has_version = any(kw in msg for kw in (
            "history", "blame", "who changed", "commit", "diff",
            "branch", "log", "when was",
        ))
        # Compound: explicit sequencing connectors take priority over individual signals
        has_compound = any(kw in msg for kw in (" and then ", " then ", "after that")) or (
            " and " in msg and (has_modify or has_version)
        )

        if has_compound:
            intent = "compound"
        elif has_modify:
            intent = "modify"
        elif has_version:
            intent = "version"
        else:
            intent = "qa"

        return RouterResult(intent=intent, scope="local", raw_response="[heuristic fallback]")

    def is_available(self) -> bool:
        return self._llm.is_available()
