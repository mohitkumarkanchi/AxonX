"""Base agent loop — shared interface for all specialist agents."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class AgentResult:
    content: str
    agent_type: str
    citations: list[dict]       # list of {filepath, symbol, start_line, end_line}
    used_chunks: list[str]      # chunk IDs used
    used_skill_cards: list[str] # SKILL.md paths included


class BaseAgent(ABC):
    """Every specialist agent implements this interface."""

    agent_type: str = "base"

    @abstractmethod
    def run(self, query: str, session) -> AgentResult:
        """
        Process a query in the context of a session.
        Returns an AgentResult with the response and provenance.
        """
