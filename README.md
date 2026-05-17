# AxonX — Local AI Code Intelligence Engine

A highly optimized, local-first AI coding agent for **Python codebases** featuring branch-aware dual-layer indexing (vector + call-graph), AST syntax guardrails, automated test integration, and a real-time VS Code sidebar.

---

## 📖 Project Documentation

We have compiled a complete, deep-dive documentation suite inside the [docs/](docs) folder:

*   **[System Architecture](docs/architecture.md)** — Learn about the lossless residue parser, SQLite call graphs, Reciprocal Rank Fusion (RRF), branch-aware delta indices, and AST-checked CodeAct safety sandboxes.
*   **[CLI Command Reference](docs/cli_reference.md)** — Complete dictionary of `axonx` commands (`init`, `chat`, `modify`, `serve`, `branches`, `undo`, `usage`).
*   **[VS Code Sidebar Integration](docs/vscode_integration.md)** — Guide on how the local SSE streaming server connects directly to your VS Code sidebar webview.
*   **[Configuration Guide (.agentrc)](docs/configuration.md)** — Comprehensive breakdown of configuration keys, context budgets, and dynamic model tag fallbacks.
*   **[Roadmap & Research Directions](docs/roadmap_research.md)** — Future engineering directions for MLX native embeddings, speculative decoding, TS/Rust graph expansions, and containerized runs.

---

## Features

- **Python-Exclusive Support**: Designed and mathematically optimized **exclusively for Python codebases** (AST compile validation and call-graph indexing are natively written for Python).
- **Dual LLM backends**: Ollama (fully local) and Claude API — switchable per session or per agent role
- **Code workspace indexing**: dual-layer index (semantic FAISS vectors + SQLite call graph)
- **Per-branch index**: separate delta index per git branch
- **Natural language queries**: routed to specialist agents (QA, Modify, Version, Orchestrator)
- **Read/modify/commit code**: with plan approval and safety guardrails
- **Incremental re-indexing**: on every file change (< 2s per file)
- **Persistent conversations**: full context across sessions, resumes exactly where you left off
- **VS Code sidebar**: real-time chat, token-by-token streaming, approve/cancel plan panel
- **Apple Silicon optimized**: Metal/MLX via Ollama

---

## 💬 Chat Capabilities, Scope & Examples

AxonX provides a highly advanced, context-aware interactive chat experience natively inside both the CLI (`axonx chat`) and your VS Code Sidebar panel. 

The chat utilizes our **Intent Router** to classify your prompts, automatically invoking the appropriate specialized agent behind the scenes.

### 🎯 Capability Scopes

1. **RAG-Powered codebase Q&A (Read-Only)**
   * **What it does**: Searches both the CPU-optimized FAISS vector database and SQLite call-graph databases, combining results using Reciprocal Rank Fusion (RRF) to answer conceptual or structural queries.
   * **LLM Used**: Ollama `llama3.2:latest` (or `claude-sonnet-4-5` if provider is overridden).
   * **Includes**: Full files, exact line ranges, symbol definitions, and `.agentrc` context.

2. **CodeAct Code Modification (Write & Self-Heal)**
   * **What it does**: Compiles a multi-step proposed plan for making workspace changes, waits for user approval, compiles the diffs in an AST-validated sandbox, runs your native test suite, and stashes changes in a millisecond on fail.
   * **LLM Used**: Ollama `qwen2.5-coder:14b` (or `claude-sonnet-4-5`).

3. **Version & Git Intelligence**
   * **What it does**: Interrogates git commit histories, traces file modifications, displays delta layers, and coordinates branch-aware swaps.
   * **LLM Used**: Ollama `phi3:3.8b` (Specialized in fast structural commands).

---

### 💡 Concrete Examples & Prompts

#### 🔍 Example 1: Codebase Q&A & Configuration Exploration
Ask AxonX to explain complex structural architectures or parameters.
* **Prompt**: 
  > *"How does the configuration system handle fallback TOML parsers, and what file is responsible?"*
* **Response**: 
  AxonX will scan the vector index, trace class imports, and output that `agent/config.py` handles the configuration, utilizing `tomli` as a robust fallback for Python versions older than `3.11` (which lack native `tomllib`). It will print the exact lines from the code.

#### 🕸️ Example 2: Relational Call-Graph Query
Leverage the Relational SQLite Call-Graph index to track inheritance and dependencies.
* **Prompt**:
  > *"Find all provider classes that implement LLMProvider and show where their source files are located."*
* **Response**:
  The Q&A agent traverses the relational call-graph SQLite tables to find subclasses of `LLMProvider`. It instantly returns:
  * `OllamaProvider` inside [agent/llm/ollama_provider.py](agent/llm/ollama_provider.py)
  * `ClaudeProvider` inside [agent/llm/claude_provider.py](agent/llm/claude_provider.py)

#### 🛠️ Example 3: Automated Sandbox Refactoring
Trigger the self-healing CodeAct loop to safely make codebase changes.
* **Prompt**:
  > *"Refactor the watcher in watcher.py to debounce index updates by 1000ms instead of 500ms."*
* **Response**:
  1. The agent compiles an **Implementation Plan** showing the exact target files and steps.
  2. The VS Code Sidebar displays a custom approval card.
  3. Upon clicking **Approve**, the agent writes the change, compiles it through Python `ast.parse` to confirm no syntax errors, and runs `pytest` automatically.
  4. If tests pass, the change is committed. If a test fails, the workspace is immediately rolled back using a git stash snapshot in 1ms!

---

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
   cd axonx
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

## VS Code & Antigravity IDE Extension

The extension adds a premium, high-fidelity **Local Agent** panel to your editor's Activity Bar with a beautiful chat interface, live status indicator, and interactive approval cards.

### 🚀 Package and Install (One-Step Script)

We provide a direct helper script that builds and installs the extension into both **VS Code** and **Antigravity IDE** instantly:

```bash
cd vscode-extension
bash install.sh
```
*(Requires `node` and `npm` on your PATH).*

---

### 📦 Manual VSIX Installation (For Release)

The project includes a pre-packaged [local-agent.vsix](vscode-extension/local-agent.vsix) inside the `vscode-extension/` directory.

#### Method 1: Through the Editor GUI (e.g. Antigravity IDE)
1. Launch **Antigravity** (or VS Code).
2. Open the **Extensions** view (`Cmd + Shift + X`).
3. Click the **three dots (`...`)** in the top-right corner of the Extensions pane.
4. Select **Install from VSIX...** from the dropdown.
5. Select [vscode-extension/local-agent.vsix](vscode-extension/local-agent.vsix) to complete the installation!

#### Method 2: Via the Terminal CLI
To install the pre-built VSIX file via the CLI, run the appropriate command for your editor:

```bash
# Standard VS Code
code --install-extension vscode-extension/local-agent.vsix

# Antigravity IDE
antigravity --install-extension vscode-extension/local-agent.vsix
```

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
axonx/
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
