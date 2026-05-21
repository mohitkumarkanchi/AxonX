"""
Orchestrator — sequences multiple agents for compound queries.

Example: ["qa", "modify"] → explain first, then modify using explanation as context.
The output of agent N is passed as additional context into agent N+1.
"""

from __future__ import annotations

from ..agents.base import AgentResult, BaseAgent
from ..agents.rag_agent import RagAgent
from ..agents.version_agent import VersionAgent
from ..agents.codeact_agent import CodeActAgent
from ..config import Config
from ..index.faiss_store import FAISSStore
from ..index.graph_store import GraphStore


class Orchestrator(BaseAgent):
    agent_type = "orchestrator"

    def __init__(
        self,
        config: Config,
        faiss_store: FAISSStore,
        graph_store: GraphStore,
        provider_override: str | None = None,
    ) -> None:
        self._config = config
        self._rag = RagAgent(config, faiss_store, graph_store, provider_override)
        self._version = VersionAgent(config, provider_override)
        self._codeact = CodeActAgent(config, faiss_store, graph_store, provider_override)

    def run(
        self,
        query: str,
        session=None,
        sub_tasks: list[str] | None = None,
    ) -> AgentResult:
        if not sub_tasks:
            sub_tasks = ["qa"]

        accumulated_context = ""
        final_result: AgentResult | None = None
        all_citations: list[dict] = []
        all_chunks: list[str] = []
        all_skills: list[str] = []

        for i, intent in enumerate(sub_tasks):
            # Augment query with output from previous task
            augmented_query = query
            if accumulated_context:
                augmented_query = (
                    f"{query}\n\n[Context from previous step]:\n{accumulated_context}"
                )

            result = self._dispatch(intent, augmented_query, session)
            accumulated_context = result.content
            final_result = result
            all_citations.extend(result.citations)
            all_chunks.extend(result.used_chunks)
            all_skills.extend(result.used_skill_cards)

        if final_result is None:
            return AgentResult(
                content="No sub-tasks to run.",
                agent_type=self.agent_type,
                citations=[],
                used_chunks=[],
                used_skill_cards=[],
            )

        return AgentResult(
            content=final_result.content,
            agent_type=self.agent_type,
            citations=all_citations,
            used_chunks=all_chunks,
            used_skill_cards=all_skills,
        )

    def _dispatch(self, intent: str, query: str, session) -> AgentResult:
        if intent == "modify":
            return self._codeact.run(query, session=session)
        elif intent == "version":
            return self._version.run(query, session=session)
        else:
            return self._rag.run(query, session=session)
