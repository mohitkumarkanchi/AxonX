# 🗺️ AxonX Future Roadmap & Research Directions

This document outlines the elite research directions and engineering roadmap for future iterations of **AxonX** (v0.4.0 and beyond).

---

## 🚀 1. MLX-Native Local Embeddings (Apple Silicon Acceleration) 🍏

- **The Objective**: Integrate Apple’s native **MLX library** directly into the indexer pipeline.
- **Why It Matters**: Currently, AxonX calls Ollama to compute embeddings via `nomic-embed-text`. By leveraging MLX directly, we can compute embeddings on the Apple Silicon unified memory GPU, achieving up to a **5x speedup** on repository seed indexing and removing local HTTP overhead.

## 🕸️ 2. Multi-Language Tree-Sitter Expansion

- **The Objective**: Extend the lossless residue parser and SQLite call-graph schema to support other languages.
- **Why It Matters**: While AxonX currently supports **Python exclusively**, the core graph architecture (SQLite relations of `CALLS`, `INHERITS`, `IMPORTS`) can be mapped to TypeScript/JavaScript, Go, and Rust by compiling and integrating their respective tree-sitter grammars.

## ⚡ 3. Local Speculative Decoding

- **The Objective**: Implement a speculative drafting pipeline for local code generation.
- **Why It Matters**: Local LLM execution can sometimes experience latency. By using a tiny, hyper-fast model (like `qwen2.5-coder:1.5b` or `deepseek-coder:1.3b`) to draft proposed edits, and using our larger `qwen2.5-coder:14b` in a single forward pass to verify and correct, we can boost local generation speeds by **200% to 300%** on standard consumer GPUs.

## 🐳 4. Secure Containerized Sandboxing

- **The Objective**: Run the self-healing sandbox inside containerized runners.
- **Why It Matters**: Currently, CodeAct compiles and tests edits on the native workspace. Moving this loop into a lightweight, ephemeral Docker container would isolate local bash executions and automated tests, adding an ironclad layer of security.

## 📂 5. Late Interaction Retrievers (ColBERT)

- **The Objective**: Transition from basic FAISS cosine-similarity lookups to a multi-vector late interaction model.
- **Why It Matters**: Multi-vector models like ColBERT analyze code at token-level granularities rather than full-sentence averages. This dramatically increases retrieval accuracy for highly technical or complex developer queries.
