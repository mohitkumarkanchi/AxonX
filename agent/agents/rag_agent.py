"""
RAG agent — read-only semantic QA over the indexed workspace.

Steps:
1. Embed query with nomic-embed-text
2. FAISS similarity search → top 8 (Ollama) or top 20 (Claude) chunks
3. If scope=="broad": also query graph for symbol dependencies
4. RRF merge: combine semantic + graph results
5. Assemble context: chunks + skill cards for relevant modules
6. Trim to token budget
7. Call LLM with context + query
8. Return answer with file:line citations
"""

from __future__ import annotations

from pathlib import Path

from ..agents.base import AgentResult, BaseAgent
from ..config import Config, WORKING_BUDGET
from ..index.faiss_store import FAISSStore
from ..index.graph_store import GraphStore
from ..indexer.embedder import embed_text
from ..indexer.skill_writer import load_skill_card
from ..llm.factory import build_provider
from ..llm.provider import Message
from ..llm.token_counter import count_tokens, trim_to_budget


SYSTEM_PROMPT = """\
You are a code intelligence assistant. Answer questions about a software codebase
accurately and concisely. Use the provided code context and call graph information.
Cite file paths and line numbers when referencing specific code.
Format: filepath:line_number — e.g. src/auth/middleware.py:42
"""


class RagAgent(BaseAgent):
    agent_type = "rag"

    def __init__(
        self,
        config: Config,
        faiss_store: FAISSStore,
        graph_store: GraphStore,
        provider_override: str | None = None,
    ) -> None:
        self._config = config
        self._faiss = faiss_store
        self._graph = graph_store
        self._provider = build_provider("reasoning", config, override=provider_override)
        self._provider_name = provider_override or config.provider.default

    def run(self, query: str, session=None, scope: str = "local", session_store=None) -> AgentResult:
        # 1. Embed query
        try:
            query_vec = embed_text(query, model=self._config.models.embedding)
        except Exception as exc:
            return AgentResult(
                content=f"Error: could not embed query — is Ollama running? ({exc})",
                agent_type=self.agent_type,
                citations=[],
                used_chunks=[],
                used_skill_cards=[],
            )

        # 2. Semantic search — more chunks for Claude (large context window)
        top_k = 20 if self._provider_name == "claude" else 8
        semantic_results = self._faiss.query(query_vec, top_k=top_k)

        # 3. Graph augmentation for broad scope
        graph_results: list[dict] = []
        if scope == "broad" and semantic_results:
            # Find top symbols and get their neighbourhood
            top_symbols = list({r["symbol"] for r in semantic_results[:5] if r.get("symbol")})
            for sym in top_symbols[:3]:
                edges = self._graph.symbol_neighbourhood(sym, depth=1)
                # Convert edges to pseudo-chunks for context
                for edge in edges[:5]:
                    graph_results.append({
                        "symbol":   f"{edge.get('src_symbol')} -> {edge.get('tgt_symbol')}",
                        "filepath": edge.get("src_file", ""),
                        "content":  f"[{edge.get('relation')}] {edge.get('src_symbol')} → {edge.get('tgt_symbol')}",
                        "kind":     "edge",
                        "start_line": None,
                        "end_line":   None,
                        "score":    999.0,
                    })

        # 4. RRF merge (semantic wins; graph provides supplementary context)
        all_results = _rrf_merge(semantic_results, graph_results, k=top_k)

        # 5. Load SKILL.md cards for relevant modules
        skills_dir = self._config.agent_dir / "index" / "skills"
        modules_seen: set[str] = set()
        skill_cards_used: list[str] = []

        for r in all_results[:5]:
            fp = r.get("filepath", "")
            if fp:
                try:
                    rel = Path(fp).relative_to(self._config.workspace_path)
                    top = rel.parts[0] if len(rel.parts) > 1 else str(rel)
                    if top not in modules_seen:
                        modules_seen.add(top)
                        card = load_skill_card(top, skills_dir)
                        if card:
                            skill_cards_used.append(str(skills_dir / f"{top}.md"))
                except ValueError:
                    pass

        # 6. Build context string
        context_parts: list[str] = []

        for card_path in skill_cards_used:
            try:
                card_content = Path(card_path).read_text()
                context_parts.append(f"=== SKILL CARD ===\n{card_content}")
            except OSError:
                pass

        chunk_ids: list[str] = []
        citations: list[dict] = []
        for r in all_results:
            chunk_ids.append(r.get("chunk_id", ""))
            fp = r.get("filepath", "")
            sym = r.get("symbol", "")
            sl = r.get("start_line")
            el = r.get("end_line")
            content = r.get("content", "")

            ref = f"{fp}:{sl}" if sl else fp
            context_parts.append(
                f"--- {ref} [{sym}] ---\n{content}"
            )
            if fp:
                citations.append({
                    "filepath":   fp,
                    "symbol":     sym,
                    "start_line": sl,
                    "end_line":   el,
                })

        context_text = "\n\n".join(context_parts)

        # 7. Build messages and trim to budget
        budget = (
            WORKING_BUDGET.get(self._provider.model, 180_000)
            if self._provider_name == "claude"
            else self._config.session.ollama_context_budget
        )

        # Load conversation history via session_store (session is a Session dataclass, not SessionStore)
        history: list[Message] = []
        if session_store is not None and session is not None:
            try:
                history = session_store.load_conversation_messages(session.id)
            except Exception:
                pass

        messages: list[Message] = history + [
            Message(role="user", content=f"Context:\n{context_text}\n\nQuestion: {query}")
        ]

        # Trim if needed — preserve last message
        messages = trim_to_budget(messages, budget, provider=self._provider_name)

        # 8. Call LLM
        try:
            response = self._provider.chat(
                messages=messages,
                system=SYSTEM_PROMPT,
                max_tokens=2048,
            )
            return AgentResult(
                content=response.content,
                agent_type=self.agent_type,
                citations=citations,
                used_chunks=[c for c in chunk_ids if c],
                used_skill_cards=skill_cards_used,
            )
        except Exception as exc:
            return AgentResult(
                content=f"Error calling LLM: {exc}",
                agent_type=self.agent_type,
                citations=[],
                used_chunks=[],
                used_skill_cards=[],
            )


def _rrf_merge(
    semantic: list[dict],
    graph: list[dict],
    k: int = 60,
    top_k: int = 20,
) -> list[dict]:
    """
    Reciprocal Rank Fusion — combine semantic and graph results.
    Lower FAISS distance = better; RRF uses 1/(rank + k).
    """
    scores: dict[str, float] = {}
    items: dict[str, dict] = {}

    for rank, r in enumerate(semantic):
        cid = r.get("chunk_id") or r.get("symbol", f"s{rank}")
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (rank + k)
        items[cid] = r

    for rank, r in enumerate(graph):
        cid = r.get("chunk_id") or r.get("symbol", f"g{rank}")
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (rank + k) * 0.5  # down-weight graph
        items[cid] = r

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [items[cid] for cid, _ in ranked[:top_k]]
