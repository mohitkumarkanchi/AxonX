# AxonX CLI Command Reference

The `axonx` CLI is the main interaction interface for indexing, searching, modifying, and hosting your code intelligence engine.

---

## 🚀 Commands Overview

### `axonx init`
Initializes and builds the dual-layer index for your workspace.
* **Under the Hood:** Recursively parses all workspace files, extracts AST scopes, generates semantic vector embeddings via Ollama/Claude, and compiles the directed call-graph into SQLite.
* **Usage:**
  ```bash
  axonx init [OPTIONS]
  ```
* **Options:**
  * `--workspace, -w PATH` - Absolute path to the workspace root (default: current directory `.`).
* **Example:**
  ```bash
  axonx init -w /Users/mohitkanchi/Desktop/my-project
  ```

---

### `axonx chat`
Launches a rich, interactive terminal session directly with the AxonX agent.
* **Under the Hood:** Boots up a terminal-friendly Chat REPL, reads past sessions, automatically detects branch states, and implements sliding-context windows with Haiku-based summarizations. Exposes an optional background server for the VS Code extension sidebar.
* **Usage:**
  ```bash
  axonx chat [OPTIONS]
  ```
* **Options:**
  * `--workspace, -w PATH` - Target codebase directory (default: `.`).
  * `--provider [ollama|claude]` - Override default LLM provider.
  * `--model TEXT` - Override specific model name (e.g. `llama3.2:latest`, `phi3`).
  * `--resume/--no-resume` - Resumes the last conversation thread (default: `--resume`).
  * `--serve` - Starts the background HTTP server on a local port simultaneously.
  * `--port INTEGER` - Specifies the sidebar communication port (default: `7070`).
* **Example:**
  ```bash
  axonx chat --provider ollama --model phi3
  ```

---

### `axonx modify`
Applies a natural language code modification to the codebase in a safe sandbox.
* **Under the Hood:** Clasifies intent, runs hybrid vector-graph search to fetch affected code context, coordinates a surgical diff proposal, validates python syntax via AST compiler checks, runs automated tests, and auto-commits the validated result.
* **Usage:**
  ```bash
  axonx modify [OPTIONS] INSTRUCTION
  ```
* **Options:**
  * `--workspace, -w PATH` - Target codebase directory (default: `.`).
  * `--provider [ollama|claude]` - Override LLM provider.
  * `--model TEXT` - Override model name.
  * `--dry-run` - Generates and displays the modification plan without writing changes to disk.
* **Example:**
  ```bash
  axonx modify "add validation error handling to register_user in auth.py" --dry-run
  ```

---

### `axonx serve`
Starts the HTTP + Server-Sent Events (SSE) server for the VS Code extension sidebar.
* **Under the Hood:** Spins up a lightweight background server that bridges VS Code interactions (chat, plan approvals, cancellations) directly to the AxonX RAG core via standard-library event streaming.
* **Usage:**
  ```bash
  axonx serve [OPTIONS]
  ```
* **Options:**
  * `--workspace, -w PATH` - Target codebase directory (default: `.`).
  * `--provider [ollama|claude]` - Override LLM provider.
  * `--model TEXT` - Override model name.
  * `--port INTEGER` - Port for sidebar server (default: `7070`).
* **Example:**
  ```bash
  axonx serve --port 7070
  ```

---

### `axonx branches`
Lists all git branches and their corresponding index status.
* **Under the Hood:** Scans the `.agent/index/branches` directory to show which branches have built-in delta vector and graph indexes, along with size and last modified metadata.
* **Usage:**
  ```bash
  axonx branches
  ```

---

### `axonx undo`
Safely rollbacks the last successful modification applied by the agent.
* **Under the Hood:** Inspects git history and session stashes, performing a hard checkout/revert to return the workspace exactly to the previous validated commit.
* **Usage:**
  ```bash
  axonx undo
  ```

---

### `axonx usage`
Displays detailed token consumption and active costs.
* **Under the Hood:** Queries SQLite logs to break down input tokens, output tokens, total cost, and invocation frequency across Ollama and Claude providers.
* **Usage:**
  ```bash
  axonx usage
  ```
