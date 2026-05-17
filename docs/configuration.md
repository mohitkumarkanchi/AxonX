# AxonX Configuration Manual

AxonX is designed to be highly configurable via a simple, readable TOML format. It automatically loads configuration options from a `.agentrc` file located in the workspace root or falls back to a global configuration at `~/.agentrc`.

---

## 🛠️ Configuration Structure

Here is a complete breakdown of configuration sections inside a standard `.agentrc` file:

```toml
[provider]
# Primary LLM provider backend ("ollama" or "claude")
default = "ollama"

# Granular, role-based provider overrides
reasoning_provider = "ollama"
coding_provider    = "ollama"
summarise_provider = "ollama"

[models]
# Local Ollama model targets (fully self-healing fallbacks if unpulled!)
reasoning   = "qwen2.5:14b"
coding      = "qwen2.5-coder:14b"
routing     = "phi3:3.8b"
embedding   = "nomic-embed-text"

# Anthropic Claude model targets
claude_reasoning  = "claude-sonnet-4-5"
claude_coding     = "claude-sonnet-4-5"
claude_summarise  = "claude-haiku-4-5"

[safety]
# Git branches the agent is strictly banned from writing/modifying
protected_branches = ["main", "master", "production"]
# Maximum number of files the agent can edit in a single transaction
max_files_per_operation = 10
# Require explicit user approval before writing edits to disk
require_plan_approval = true
# Take git stash checkpoints before executing operations
auto_checkpoint = true

[index]
# Number of parallel processes to use during seed indexing
parallel_workers = 8
# Millisecond debounce buffer before starting incremental re-indexing
incremental_debounce_ms = 500
# Maximum file system size allocation for vector indices
max_index_size_gb = 2.0
# Cache semantic search queries in-memory for speed
cache_query_results = true

[session]
# Total token context budget for local Ollama models (to avoid truncation)
ollama_context_budget  = 6000
# Total token context budget for Claude models
claude_context_budget  = 180000
# Summarize past history turns after this count to save tokens
summarise_after_turns  = 8
# Number of recent history messages to keep intact after summarization
keep_recent_turns      = 4
# Automatically resume previous sessions on CLI start
auto_resume            = true

[tests]
# Automatically run test suites after completing a code modification
auto_run_after_modify = true
# Test command mapping per programming language
test_commands = { python = "pytest", javascript = "npm test", go = "go test ./..." }
```

---

## 🔌 Dynamic Model Fallback Mechanism

One of AxonX's most powerful production-grade features is its **Self-Healing Model Resolver**:
* If the configured model (e.g. `coding = "qwen2.5-coder:14b"`) is **not pulled** in your local Ollama server, AxonX does not crash.
* It dynamically queries `/api/tags` to fetch all available local models.
* It compares the list against a prioritized sequence of fallback options:
  `["qwen2.5-coder:14b", "qwen2.5-coder:7b", "qwen2.5-coder:1.5b", "qwen2.5:14b", "qwen2.5:7b", "llama3.2:latest", "llama3.2", "phi3:3.8b", "phi3"]`
* It selects the first matching, pulled model, prints a helpful terminal warning, and seamlessly proceeds:
  ```bash
  Warning: Ollama model 'qwen2.5-coder:14b' is not pulled. Seamlessly falling back to 'llama3.2:latest'.
  ```
* This guarantees that new developers or lightweight systems can run AxonX immediately without heavy model setup!
