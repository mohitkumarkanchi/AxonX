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

## 📢 LinkedIn Launch Post Template
*(Copy and paste this directly onto LinkedIn to share your project!)*

```text
🚀 I got tired of AI coding agents breaking my builds, leaking my codebase to the cloud, and freezing every time I switched Git branches.

So, I built something better: AxonX. 🤖

AxonX is a high-performance, 100% local AI code intelligence engine. It operates completely offline inside an AST-validated safety sandbox, merging semantic vector indexing with static call graphs right inside your editor.

Here are the 3 technical breakthroughs that make AxonX different:

🌿 1. Branch-Aware Delta Indexing (< 2s Swaps)
Most agents force a slow, redundant indexing cycle when you check out a new branch. AxonX actively watches `.git/HEAD` and swaps branch-specific delta layers in less than 2 seconds, leaving your master index completely untouched.

🕸️ 2. Spatial Code Awareness (Vector-Graph RRF)
Semantic vector search is blind to actual compiler execution paths. AxonX combines a CPU-optimized FAISS vector database with a relational SQLite call graph (mapping imports, calls, and inheritance). We fuse them using Reciprocal Rank Fusion (RRF) so the LLM gets an accurate spatial map of your code flow.

🛡️ 3. AST-Checked Self-Healing Sandbox
No more syntax errors or broken compilers. AxonX proposes edits as surgical JSON diffs, compiles the code using Abstract Syntax Tree (`ast.parse`) parsing pre-commit, and automatically runs your project's native tests. If anything fails, it rolls back your workspace to a Git stash snapshot in 1 millisecond.

🛠️ The Tech Stack:
• LLM: Ollama (phi3:3.8b for routing, llama3.2:latest for chat)
• Embeddings: nomic-embed-text
• Vector DB: FAISS IndexIDMap + SQLite metadata sidecar
• AST: tree-sitter 0.21.3
• Server: Python standard-library HTTP + SSE (super lightweight!)

⚡ Best part? It's completely local, offline-first, and features dynamic model tag fallbacks to heal itself on the fly.

Check out the full open-source codebase, architecture maps, and CLI docs on GitHub:
👉 https://github.com/mohitkumarkanchi/AxonX.git

I’d love to hear your thoughts and get your feedback! Let's build offline-first code intelligence together. 💻

#AI #SoftwareEngineering #OpenSource #LocalLLM #Ollama #Python #VSCode #RAG #GenerativeAI #CodingAgent
```
