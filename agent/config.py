"""Load and expose .agentrc configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib  # type: ignore[import]  # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib  # type: ignore[import,no-redef]
    except ImportError:
        tomllib = None  # type: ignore[assignment]


@dataclass
class ModelsConfig:
    reasoning: str = "qwen2.5:14b"
    coding: str = "qwen2.5-coder:14b"
    routing: str = "phi3:3.8b"
    embedding: str = "nomic-embed-text"
    claude_reasoning: str = "claude-sonnet-4-6"
    claude_coding: str = "claude-sonnet-4-6"
    claude_summarise: str = "claude-haiku-4-5-20251001"


@dataclass
class ProviderConfig:
    default: str = "ollama"
    reasoning_provider: str = "ollama"
    coding_provider: str = "ollama"
    summarise_provider: str = "ollama"


@dataclass
class SafetyConfig:
    protected_branches: list[str] = field(default_factory=lambda: ["main", "master", "production"])
    max_files_per_operation: int = 10
    require_plan_approval: bool = True
    auto_checkpoint: bool = True


@dataclass
class IndexConfig:
    parallel_workers: int = 8
    incremental_debounce_ms: int = 500
    max_index_size_gb: float = 2.0
    cache_query_results: bool = True


@dataclass
class SessionConfig:
    ollama_context_budget: int = 6_000
    claude_context_budget: int = 180_000
    summarise_after_turns: int = 8
    keep_recent_turns: int = 4
    auto_resume: bool = True


@dataclass
class ContextStoreConfig:
    store_rag_snapshots: bool = True
    store_token_usage: bool = True
    max_sessions_stored: int = 50
    max_messages_per_session: int = 10_000


@dataclass
class TestsConfig:
    auto_run_after_modify: bool = True
    test_commands: dict[str, str] = field(default_factory=lambda: {
        "python": "pytest",
        "javascript": "npm test",
        "go": "go test ./...",
    })


@dataclass
class Config:
    provider: ProviderConfig = field(default_factory=ProviderConfig)
    models: ModelsConfig = field(default_factory=ModelsConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    index: IndexConfig = field(default_factory=IndexConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    context_store: ContextStoreConfig = field(default_factory=ContextStoreConfig)
    tests: TestsConfig = field(default_factory=TestsConfig)

    # Runtime state (not from .agentrc)
    workspace_path: Path = field(default_factory=Path)
    agent_dir: Path = field(default_factory=Path)


def _merge(dataclass_instance, raw: dict) -> None:
    """Shallow-merge raw dict keys into a dataclass instance."""
    for key, value in raw.items():
        if hasattr(dataclass_instance, key):
            setattr(dataclass_instance, key, value)


def load_config(workspace_path: str | Path) -> Config:
    """Load .agentrc from workspace root (falls back to ~/.agentrc, then defaults)."""
    workspace_path = Path(workspace_path).resolve()
    cfg = Config()
    cfg.workspace_path = workspace_path
    cfg.agent_dir = workspace_path / ".agent"

    # Search order: workspace .agentrc → home .agentrc
    workspace_rc = workspace_path / ".agentrc"
    home_rc = Path.home() / ".agentrc"

    # Auto-generate a beautiful .agentrc in workspace root if none exists anywhere
    if not workspace_rc.exists() and not home_rc.exists():
        try:
            default_content = """\
[provider]
# "ollama" = fully local, no API key needed
# "claude" = uses ANTHROPIC_API_KEY env var
default = "ollama"

# Per-role overrides
reasoning_provider = "ollama"
coding_provider    = "ollama"
summarise_provider = "ollama"

[models]
# Ollama models (local LLM fallback is automatic if missing!)
reasoning   = "qwen2.5:14b"
coding      = "qwen2.5-coder:14b"
routing     = "phi3:3.8b"
embedding   = "nomic-embed-text"

# Claude models (used when provider = "claude")
# Available: claude-opus-4-7 (most capable), claude-sonnet-4-6 (balanced), claude-haiku-4-5-20251001 (fast)
claude_reasoning  = "claude-sonnet-4-6"
claude_coding     = "claude-sonnet-4-6"
claude_summarise  = "claude-haiku-4-5-20251001"

[safety]
protected_branches = ["main", "master", "production"]
max_files_per_operation = 10
require_plan_approval = true
auto_checkpoint = true

[index]
parallel_workers = 8
incremental_debounce_ms = 500
max_index_size_gb = 2.0
cache_query_results = true

[session]
ollama_context_budget  = 6000
claude_context_budget  = 180000
summarise_after_turns  = 8
keep_recent_turns      = 4
auto_resume            = true

[context_store]
store_rag_snapshots    = true
store_token_usage      = true
max_sessions_stored    = 50
max_messages_per_session = 10000

[tests]
auto_run_after_modify = true
test_commands = { python = "pytest", javascript = "npm test", go = "go test ./..." }
"""
            workspace_rc.write_text(default_content, encoding="utf-8")
            print(f"Generated default configuration: {workspace_rc}")
        except Exception:
            pass

    search_paths = [workspace_rc, home_rc]

    raw: dict = {}
    if tomllib is not None:
        for p in search_paths:
            if p.exists():
                try:
                    with open(p, "rb") as f:
                        raw = tomllib.load(f)
                    break
                except Exception:
                    pass

    if "provider" in raw:
        _merge(cfg.provider, raw["provider"])
    if "models" in raw:
        _merge(cfg.models, raw["models"])
    if "safety" in raw:
        safety_raw = raw["safety"].copy()
        # TOML arrays come in as lists already
        _merge(cfg.safety, safety_raw)
    if "index" in raw:
        _merge(cfg.index, raw["index"])
    if "session" in raw:
        _merge(cfg.session, raw["session"])
    if "context_store" in raw:
        _merge(cfg.context_store, raw["context_store"])
    if "tests" in raw:
        _merge(cfg.tests, raw["tests"])

    # Override provider from env if set
    env_provider = os.environ.get("AGENT_PROVIDER")
    if env_provider in ("ollama", "claude"):
        cfg.provider.default = env_provider

    return cfg


CONTEXT_LIMITS: dict[str, int] = {
    "claude-opus-4-7":          200_000,
    "claude-sonnet-4-6":        200_000,
    "claude-haiku-4-5-20251001": 200_000,
    # legacy names kept for backwards-compat with old .agentrc files
    "claude-sonnet-4-5":        200_000,
    "claude-haiku-4-5":         200_000,
    "qwen2.5:14b":               32_000,
    "qwen2.5-coder:14b":         32_000,
    "phi3:3.8b":                  4_000,
}

WORKING_BUDGET: dict[str, int] = {
    "claude-opus-4-7":          180_000,
    "claude-sonnet-4-6":        180_000,
    "claude-haiku-4-5-20251001": 180_000,
    # legacy
    "claude-sonnet-4-5":        180_000,
    "claude-haiku-4-5":         180_000,
    "qwen2.5:14b":                6_000,
    "qwen2.5-coder:14b":          6_000,
    "phi3:3.8b":                  2_000,
}
