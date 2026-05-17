# AxonX — Local AI Code Intelligence Engine

A highly optimized, local-first AI coding agent with branch-aware dual-layer indexing (vector + call-graph), AST syntax guardrails, automated test integration, and a real-time VS Code sidebar.

---

## 📖 Project Documentation

We have compiled a complete, deep-dive documentation suite inside the [docs/](file:///Users/mohitkanchi/Desktop/localAgent/agent-workspace/docs) folder:

*   **[System Architecture](file:///Users/mohitkanchi/Desktop/localAgent/agent-workspace/docs/architecture.md)** — Learn about the lossless residue parser, SQLite call graphs, Reciprocal Rank Fusion (RRF), branch-aware delta indices, and AST-checked CodeAct safety sandboxes.
*   **[CLI Command Reference](file:///Users/mohitkanchi/Desktop/localAgent/agent-workspace/docs/cli_reference.md)** — Complete dictionary of `axonx` commands (`init`, `chat`, `modify`, `serve`, `branches`, `undo`, `usage`).
*   **[VS Code Sidebar Integration](file:///Users/mohitkanchi/Desktop/localAgent/agent-workspace/docs/vscode_integration.md)** — Guide on how the local SSE streaming server connects directly to your VS Code sidebar webview.
*   **[Configuration Guide (.agentrc)](file:///Users/mohitkanchi/Desktop/localAgent/agent-workspace/docs/configuration.md)** — Comprehensive breakdown of configuration keys, context budgets, and dynamic model tag fallbacks.

---

## Features

- **Dual LLM backends**: Ollama (fully local) and Claude API — switchable per session or per agent role
- **Code workspace indexing**: dual-layer index (semantic FAISS vectors + SQLite call graph)
- **Per-branch index**: separate delta index per git branch
- **Natural language queries**: routed to specialist agents (QA, Modify, Version, Orchestrator)
- **Read/modify/commit code**: with plan approval and safety guardrails
- **Incremental re-indexing**: on every file change (< 2s per file)
- **Persistent conversations**: full context across sessions, resumes exactly where you left off
- **VS Code sidebar**: real-time chat, token-by-token streaming, approve/cancel plan panel
- **Apple Silicon optimized**: Metal/MLX via Ollama

## Quick Start

### Prerequisites

1. Install [Ollama](https://ollama.ai) and pull required models:
   ```bash
   ollama pull qwen2.5:14b
   ollama pull qwen2.5-coder:14b
   ollama pull phi3:3.8b
   ollama pull nomic-embed-text
   ```

2. Create and activate the Python virtual environment:
   ```bash
   cd agent-workspace
   python3 -m venv .venv
   source .venv/bin/activate
   .venv/bin/pip install -e .
   ```

3. (Optional) For Claude backend:
   ```bash
   export ANTHROPIC_API_KEY=sk-ant-...
   ```

### Terminal Usage

```bash
# Index a workspace
axonx init --workspace /path/to/your/project

# Start chatting (terminal)
axonx chat

# Use Claude for this session
axonx chat --provider claude

# Start chat AND expose the HTTP+SSE server for the VS Code extension
axonx chat --serve --port 7070

# Start server only (headless — for the VS Code extension)
axonx serve --workspace /path/to/your/project --port 7070

# Direct code modification
axonx modify "refactor the auth middleware to use JWT"

# Dry run (plan only, no writes)
axonx modify "add logging to all API endpoints" --dry-run

# Undo last operation
axonx undo

# Check index health
axonx index status

# List past sessions
axonx sessions --list

# Show token usage
axonx usage
```

## VS Code Extension

The extension adds a **Local Agent** panel to the VS Code Activity Bar with a chat UI that streams responses in real time and shows plan approve/cancel buttons when the agent proposes code edits.

### Install

```bash
cd vscode-extension
bash install.sh
```

`install.sh` runs `npm install`, bundles the TypeScript with esbuild, packages a `.vsix`, and installs it into VS Code in one step. Requires `node` and `npm` on your PATH.

### What it does

- **Auto-starts** `axonx serve` when VS Code opens (configurable)
- **Falls back** to connecting to an already-running server (no duplicate processes)
- Streams agent tokens word-by-word via SSE (`GET /api/stream`)
- Shows workspace, branch, and provider in the status bar
- Approve or cancel a proposed code-edit plan without leaving VS Code

### Extension Settings

| Setting | Default | Description |
|---|---|---|
| `localAgent.port` | `7070` | Port the agent HTTP server listens on |
| `localAgent.pythonPath` | _(auto)_ | Path to Python executable; defaults to `.venv/bin/python` next to the extension |
| `localAgent.autoStart` | `true` | Auto-start the agent server when VS Code opens |

### Server API

The server (`agent/server.py`) runs on `http://127.0.0.1:7070` by default.

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/health` | Liveness check |
| GET | `/api/status` | Workspace, branch, provider, session info |
| GET | `/api/stream` | SSE event stream (tokens, plan, errors, index progress) |
| POST | `/api/chat` | Send a message (returns 202, response comes via SSE) |
| GET | `/api/operations` | Current pending plan |
| POST | `/api/operations/approve` | Approve the current plan |
| POST | `/api/operations/cancel` | Cancel the current plan |
| GET | `/api/usage` | Token usage for this session |
| GET | `/api/sessions` | List past sessions for the workspace |

## Architecture

```
agent-workspace/
├── agent/
│   ├── cli.py              # CLI entry point (chat, serve, init, modify, undo…)
│   ├── config.py           # .agentrc loader (TOML, Python 3.9 compatible)
│   ├── server.py           # HTTP + SSE server for the VS Code extension
│   ├── session.py          # SQLite session + conversation persistence
│   ├── watcher.py          # file watcher → incremental re-index
│   ├── router.py           # phi3-based intent classifier
│   ├── context_manager.py  # sliding window + summarisation
│   │
│   ├── llm/
│   │   ├── provider.py         # base interface (Message, LLMResponse, LLMProvider)
│   │   ├── ollama_provider.py
│   │   ├── claude_provider.py
│   │   └── factory.py          # routing/embedding always Ollama regardless of config
│   │
│   ├── indexer/
│   │   ├── seed.py             # parallel seed on init (ProcessPoolExecutor)
│   │   ├── incremental.py      # per-file update on save (< 2s)
│   │   ├── parser.py           # tree-sitter chunking (pinned 0.21.3)
│   │   ├── embedder.py         # nomic-embed-text → FAISS
│   │   ├── graph.py            # call graph → SQLite graph store
│   │   └── skill_writer.py     # SKILL.md cards per module
│   │
│   ├── agents/
│   │   ├── rag_agent.py        # read-only QA (RRF: semantic + graph)
│   │   ├── codeact_agent.py    # code modification (plan → approve → edit → syntax check)
│   │   ├── version_agent.py    # git history queries
│   │   └── orchestrator.py     # compound query sequencer
│   │
│   ├── index/
│   │   ├── faiss_store.py      # FAISS IndexIDMap + SQLite metadata sidecar
│   │   ├── graph_store.py      # SQLite-backed call graph
│   │   └── branch_index.py     # per-branch delta index
│   │
│   ├── git/
│   │   ├── branch_manager.py
│   │   ├── commit_writer.py
│   │   ├── conflict_resolver.py
│   │   └── undo_redo.py
│   │
│   ├── safety/
│   │   ├── guardrails.py       # protected branch + file limits
│   │   ├── checkpoint.py       # git stash snapshots
│   │   └── scope_pin.py        # subfolder restriction
│   │
│   └── ui/
│       ├── chat.py             # rich-based terminal chat loop
│       ├── diff_renderer.py
│       └── plan_renderer.py
│
├── vscode-extension/
│   ├── src/
│   │   ├── extension.ts        # activate/deactivate; starts or connects to agent serve
│   │   └── sidebarProvider.ts  # WebviewViewProvider; bridges webview ↔ HTTP API
│   ├── media/
│   │   ├── sidebar.html        # webview shell
│   │   ├── sidebar.css         # VS Code theme-variable styling
│   │   └── sidebar.js          # SSE client, chat UI, plan approve/cancel
│   ├── package.json
│   ├── tsconfig.json
│   ├── esbuild.js
│   └── install.sh              # one-shot build + install script
│
├── tests/                      # 76 tests, all passing
└── pyproject.toml
```

## Configuration

Edit `.agentrc` in your workspace root (or `~/.agentrc` for global defaults).

Key settings:

| Key | Default | Description |
|---|---|---|
| `provider.default` | `"ollama"` | `"ollama"` (fully local) or `"claude"` (needs API key) |
| `safety.protected_branches` | `["main","master"]` | Branches the agent can never modify |
| `session.claude_context_budget` | `160000` | Tokens available when using Claude |
| `session.ollama_context_budget` | `5000` | Tokens available with Ollama models |

## Provider Notes

- **Routing and embedding are always Ollama** — phi3:3.8b for routing, nomic-embed-text for embeddings, regardless of your provider setting
- **Claude's 180k context window**: when using Claude, the RAG agent sends far more context (top-20 chunks vs top-8, full SKILL.md cards, full small files)
- **claude-haiku-4-5 for summarisation**: cheap + fast for compressing old conversation turns
- **Token usage tracking**: `axonx usage` shows per-provider spend

## Implementation Notes

- **FAISS + SQLite** instead of ChromaDB — `IndexIDMap(IndexFlatL2(768))` for vectors, SQLite metadata sidecar keyed by stable SHA-256-derived int64 IDs
- **tree-sitter 0.21.3 pinned** — `tree-sitter-languages` 1.10.2 was compiled against the old `Language(path, name)` API; 0.22+ breaks it
- **Python 3.9 compatible** — `tomli` used as fallback TOML parser when `tomllib` (3.11+) is unavailable
- **SSE over WebSockets** — simpler, works natively in VS Code WebviewView without a socket server

## License

MIT
