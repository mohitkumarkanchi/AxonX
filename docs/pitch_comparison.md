# AxonX: Next-Generation Local Code Intelligence
### *Pitch Deck & Comparative Analysis*

---

## 🚀 The Core Problem: The Agent Workspace Gap
Current AI coding assistants (like Copilot Workspace, Aider, and Sweep) suffer from three massive flaws:
1. **Structural Blindness:** They rely purely on semantic vector search, making them blind to execution paths (e.g. which classes call a method or inherit from a base class).
2. **Heavy Branch Latency:** When switching branches in Git, existing tools force developers to wait minutes for a complete repository re-indexing cycle.
3. **Build & Syntax Fragility:** Standard agents blindly overwrite source files, committing broken compilers and syntax errors that disrupt development workflows.
4. **Cloud Privacy Risk:** Sending entire codebases to cloud services raises corporate security concerns.

---

## 🌟 The AxonX Breakthrough
AxonX is a **high-performance, local-first AI code intelligence engine** that operates inside an AST-validated safety sandbox. It indexes your workspace across a **dual-layer vector-graph network** and integrates directly with a real-time VS Code sidebar.

---

## 📊 Core Feature Matrix: AxonX vs. Competitors

| Feature Dimension | **AxonX** | **Aider** | **Sweep** | **GitHub Copilot** |
| :--- | :--- | :--- | :--- | :--- |
| **Local-First & Offline** | **100% Local (Ollama)** or Claude API | Local (API key req.) | Cloud-only | Cloud-only |
| **Search Architecture** | **Hybrid RRF (FAISS Vector + SQLite Call-Graph)** | Universal ctags only | Simple semantic vector | Simple semantic vector |
| **Branch Awareness** | **Branch Delta Indexes (<2s swap)** | Full re-index required | Re-runs indexer | Cloud-cached |
| **Build Safety Loop** | **AST Compiles Check + Auto-Git Stash + Native Tests** | Direct git writes | Post-execution actions | Manual compile |
| **AST Parser Precision** | **Tree-Sitter + Module Residue Extraction** | Regex chunking | Regex / AST | File-level truncation |
| **IDE Interface** | **Native SSE VS Code Sidebar Panel** | Terminal only | GitHub PRs only | Tab-complete / Chat pane |
| **API Footprint** | **Standard-Library SSE Server** | Python wrapper | Heavy Cloud Daemon | Proprietary closed-source |

---

## 🧠 Technical Deep Dive: Why AxonX Wins

### 1. Spatial Code Awareness (Vector-Graph RRF)
Instead of matching simple keywords:
* **FAISS Vector Store** handles semantic concept similarities.
* **SQLite Call Graph** tracks actual compiler dependencies (`CALLS`, `INHERITS`, `IMPORTS`).
* **Reciprocal Rank Fusion (RRF)** blends them. If a function is retrieved, its calling coordinates are automatically pulled into context, giving the LLM an unparalleled spatial map of your code flow.

### 2. Branch Swapping under 2 Seconds
AxonX registers a filesystem watchdog on `.git/HEAD`.
* When a developer runs `git checkout`, the watcher intercepts it and instantly loads a **branch-specific delta index store**.
* The main branch index remains completely untouched. No latency, no redundant database writes, and 100% accuracy across branches.

### 3. Surgical Diff Plans & AST-Checked Commits
AxonX treats your codebase with respect:
* Takes a automatic git stash snapshot before modifying anything.
* Proposes edits as **surgical string-replacement JSON plans** rather than writing whole files.
* Checks compilation via Python's AST compiler (`ast.parse`) **before writing**.
* Invokes your automated test suites (`pytest`, `npm test`) on completion. If tests fail, it rolls back the workspace automatically to the git stash.

---

