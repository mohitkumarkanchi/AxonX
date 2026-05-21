"""
Parallel seed indexer — parse + embed + graph all files on `agent init`.

Steps:
1. Discover files (exclusions applied)
2. Parallel parse with ProcessPoolExecutor
3. Embed chunks via Ollama nomic-embed-text
4. Store vectors in FAISS store
5. Build call graph in SQLite graph store
6. Generate SKILL.md cards per module
7. Write manifest.json
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import time
from pathlib import Path

from ..config import Config
from ..indexer.embedder import embed_chunks
from ..indexer.exclusions import discover_files, load_exclusions
from ..indexer.graph import extract_edges
from ..indexer.parser import parse_file, Chunk
from ..index.faiss_store import FAISSStore
from ..index.graph_store import GraphStore


def _hash_file(filepath: Path) -> str:
    h = hashlib.sha256()
    try:
        h.update(filepath.read_bytes())
    except OSError:
        pass
    return h.hexdigest()


def _parse_worker(filepath: str) -> tuple[str, list[Chunk], str]:
    """Worker function run in subprocess — parse one file, return chunks."""
    p = Path(filepath)
    chunks = parse_file(p)
    file_hash = _hash_file(p)
    return filepath, chunks, file_hash


def seed_workspace(config: Config, provider_override: str | None = None) -> dict:
    """
    Full parallel seed of the workspace.
    Returns manifest dict.
    """
    workspace = config.workspace_path
    agent_dir = config.agent_dir
    agent_dir.mkdir(parents=True, exist_ok=True)

    # Determine current git branch for scoped index
    branch = _current_branch(workspace)
    index_dir = agent_dir / "index" / "branches" / branch
    index_dir.mkdir(parents=True, exist_ok=True)

    faiss_store = FAISSStore(index_dir / "vectors")
    graph_store = GraphStore(index_dir / "graph.db")
    skills_dir = agent_dir / "index" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)

    exclusions = load_exclusions(workspace)
    files = discover_files(workspace, exclusions)

    print(f"[seed] Discovered {len(files)} files in {workspace}")
    start = time.time()

    max_workers = min(config.index.parallel_workers, os.cpu_count() or 4)

    # Parallel parse
    all_chunks: list[Chunk] = []
    file_hashes: dict[str, str] = {}

    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_parse_worker, str(f)): f for f in files}
        for future in concurrent.futures.as_completed(futures):
            try:
                filepath, chunks, file_hash = future.result()
                all_chunks.extend(chunks)
                file_hashes[filepath] = file_hash
            except Exception as exc:
                print(f"[seed] Parse error for {futures[future]}: {exc}")

    print(f"[seed] Parsed {len(all_chunks)} chunks from {len(files)} files "
          f"({time.time()-start:.1f}s)")

    # Embed and store
    embed_start = time.time()
    print(f"[seed] Embedding {len(all_chunks)} chunks via nomic-embed-text ...")

    batch_size = 32
    embedded_count = 0
    for i in range(0, len(all_chunks), batch_size):
        batch = all_chunks[i:i + batch_size]
        try:
            chunk_vecs = embed_chunks(batch)
            for chunk, vec in chunk_vecs:
                faiss_store.upsert(
                    chunk_id=chunk.id,
                    vector=vec,
                    metadata={
                        "filepath":   chunk.filepath,
                        "symbol":     chunk.symbol,
                        "kind":       chunk.kind,
                        "start_line": chunk.start_line,
                        "end_line":   chunk.end_line,
                        "content":    chunk.content,
                        "language":   chunk.language,
                        "file_hash":  file_hashes.get(chunk.filepath, ""),
                    },
                )
            embedded_count += len(batch)
        except Exception as exc:
            print(f"[seed] Embed error batch {i}: {exc}")

    print(f"[seed] Embedded {embedded_count} chunks ({time.time()-embed_start:.1f}s)")

    # Build graph
    print("[seed] Building call graph ...")
    graph_start = time.time()
    for filepath in files:
        try:
            edges = extract_edges(filepath)
            if edges:
                graph_store.insert_edges_bulk(edges)
                for chunk in [c for c in all_chunks if c.filepath == str(filepath)]:
                    graph_store.upsert_node(
                        symbol=chunk.symbol,
                        file_path=chunk.filepath,
                        kind=chunk.kind,
                    )
        except Exception as exc:
            print(f"[seed] Graph error for {filepath}: {exc}")

    graph_stats = graph_store.stats()
    print(f"[seed] Graph: {graph_stats['nodes']} nodes, {graph_stats['edges']} edges "
          f"({time.time()-graph_start:.1f}s)")

    # Generate SKILL.md cards
    _generate_skill_cards(all_chunks, skills_dir, config, provider_override)

    # Write manifest
    try:
        import subprocess
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(workspace), text=True
        ).strip()
    except Exception:
        commit = "unknown"

    manifest = {
        "branch":       branch,
        "commit_hash":  commit,
        "indexed_at":   time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "file_count":   len(files),
        "chunk_count":  len(all_chunks),
        "embed_count":  embedded_count,
        "graph_nodes":  graph_stats["nodes"],
        "graph_edges":  graph_stats["edges"],
        "file_hashes":  file_hashes,
    }
    manifest_path = index_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    elapsed = time.time() - start
    print(f"[seed] Done in {elapsed:.1f}s. Manifest: {manifest_path}")

    graph_store.close()
    faiss_store.close()

    return manifest


def _generate_skill_cards(
    chunks: list[Chunk],
    skills_dir: Path,
    config: Config,
    provider_override: str | None,
) -> None:
    """Generate SKILL.md cards per top-level module directory."""
    from ..llm.factory import build_provider

    # Group chunks by top-level directory/module
    module_chunks: dict[str, list[Chunk]] = {}
    workspace = str(config.workspace_path)
    for chunk in chunks:
        rel = chunk.filepath.removeprefix(workspace).lstrip("/\\")
        top = rel.split("/")[0] if "/" in rel else rel
        module_chunks.setdefault(top, []).append(chunk)

    provider = build_provider("summarise", config, override=provider_override)

    for module, mod_chunks in module_chunks.items():
        card_path = skills_dir / f"{module.replace('/', '_')}.md"
        if card_path.exists():
            continue  # don't regenerate on partial re-seed

        # Build summary context from chunk symbols
        symbols = list({c.symbol for c in mod_chunks if c.symbol != "module"})[:30]
        sample_content = "\n".join(c.content[:200] for c in mod_chunks[:5])

        prompt = (
            f"Module: {module}\n"
            f"Symbols: {', '.join(symbols)}\n\n"
            f"Sample code:\n{sample_content}\n\n"
            "Write a 3-5 sentence skill card describing what this module does, "
            "its main responsibilities, and key public symbols. "
            "Be concise and developer-focused."
        )

        try:
            from ..llm.provider import Message
            response = provider.chat([Message(role="user", content=prompt)], max_tokens=256)
            card_content = f"# {module}\n\n{response.content}\n\n"
            card_content += f"**Symbols**: {', '.join(symbols[:20])}\n"
            card_path.write_text(card_content)
        except Exception as exc:
            print(f"[seed] Skill card error for {module}: {exc}")


def _current_branch(workspace: Path) -> str:
    try:
        import subprocess
        return subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(workspace),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip() or "main"
    except Exception:
        return "main"
