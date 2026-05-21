"""
Version agent — git history queries (log, blame, diff, branches).

Safe read-only git commands only. Summarises output via LLM.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..agents.base import AgentResult, BaseAgent
from ..config import Config
from ..llm.factory import build_provider
from ..llm.provider import Message

GIT_SYSTEM = """\
You are a git history analyst. Given the output of git commands,
summarise the key changes, authors, and patterns in clear plain English.
Reference commit hashes, author names, and file paths when relevant.
Be concise — a paragraph or two is enough.
"""


@dataclass
class GitResult:
    command: str
    output: str
    error: str = ""


class VersionAgent(BaseAgent):
    agent_type = "version"

    def __init__(
        self,
        config: Config,
        provider_override: str | None = None,
    ) -> None:
        self._config = config
        self._workspace = config.workspace_path
        self._provider = build_provider("reasoning", config, override=provider_override)

    def run(self, query: str, session=None) -> AgentResult:
        # Detect which git operation to run
        git_result = self._dispatch(query)

        if git_result.error:
            return AgentResult(
                content=f"Git error: {git_result.error}\nCommand: {git_result.command}",
                agent_type=self.agent_type,
                citations=[],
                used_chunks=[],
                used_skill_cards=[],
            )

        # Summarise via LLM
        prompt = (
            f"Query: {query}\n\n"
            f"Command: {git_result.command}\n\n"
            f"Output:\n{git_result.output[:6000]}"
        )

        try:
            response = self._provider.chat(
                messages=[Message(role="user", content=prompt)],
                system=GIT_SYSTEM,
                max_tokens=1024,
            )
            content = response.content
        except Exception as exc:
            content = f"[Raw git output]\n{git_result.output}\n\n(LLM summarisation failed: {exc})"

        return AgentResult(
            content=content,
            agent_type=self.agent_type,
            citations=[],
            used_chunks=[],
            used_skill_cards=[],
        )

    def _dispatch(self, query: str) -> GitResult:
        q = query.lower()

        if any(kw in q for kw in ("history", "log", "commits", "recent changes")):
            return self._run_git(["git", "log", "--oneline", "-20"])

        if any(kw in q for kw in ("blame", "who changed", "who wrote", "who modified")):
            file_path = self._extract_file(query)
            if file_path:
                return self._run_git(["git", "blame", "--line-porcelain", file_path])
            return self._run_git(["git", "log", "--oneline", "-10"])

        if "diff" in q:
            refs = self._extract_refs(query)
            if len(refs) >= 2:
                return self._run_git(["git", "diff", refs[0], refs[1]])
            elif len(refs) == 1:
                return self._run_git(["git", "diff", refs[0]])
            return self._run_git(["git", "diff", "HEAD~1", "HEAD"])

        if any(kw in q for kw in ("branches", "branch list")):
            return self._run_git(["git", "branch", "-a"])

        if any(kw in q for kw in ("what changed in", "changes to", "history of")):
            file_path = self._extract_file(query)
            if file_path:
                return self._run_git(["git", "log", "--follow", "--oneline", "--", file_path])
            return self._run_git(["git", "log", "--oneline", "-10"])

        if any(kw in q for kw in ("status", "uncommitted", "staged", "unstaged")):
            return self._run_git(["git", "status"])

        if any(kw in q for kw in ("stash", "stashes")):
            return self._run_git(["git", "stash", "list"])

        # Default: recent log
        return self._run_git(["git", "log", "--oneline", "-15"])

    def _run_git(self, cmd: list[str]) -> GitResult:
        """Run a git command safely (read-only, never modifying)."""
        # Safety: only allow specific git subcommands
        allowed = {"log", "blame", "diff", "branch", "status", "stash", "show",
                   "rev-parse", "shortlog", "describe"}
        if len(cmd) >= 2 and cmd[1] not in allowed:
            return GitResult(
                command=" ".join(cmd),
                output="",
                error=f"Blocked git subcommand: {cmd[1]}",
            )

        try:
            result = subprocess.run(
                cmd,
                cwd=str(self._workspace),
                capture_output=True,
                text=True,
                timeout=30,
            )
            return GitResult(
                command=" ".join(cmd),
                output=result.stdout or result.stderr,
                error=result.stderr if result.returncode != 0 else "",
            )
        except subprocess.TimeoutExpired:
            return GitResult(
                command=" ".join(cmd),
                output="",
                error="Git command timed out",
            )
        except Exception as exc:
            return GitResult(
                command=" ".join(cmd),
                output="",
                error=str(exc),
            )

    def _extract_file(self, query: str) -> str:
        """Try to extract a file path from the query."""
        # Look for quoted strings or path-like tokens
        quoted = re.findall(r'["\']([^"\']+)["\']', query)
        if quoted:
            return quoted[0]
        # Look for tokens with slashes or dots
        tokens = query.split()
        for tok in tokens:
            if "/" in tok or tok.endswith((".py", ".js", ".ts", ".go", ".rs", ".java")):
                return tok
        return ""

    def _extract_refs(self, query: str) -> list[str]:
        """Extract git refs (commit hashes, branch names) from query."""
        # Match SHA-ish tokens
        return re.findall(r'\b([a-f0-9]{7,40}|HEAD[~^]\d*|main|master|[a-zA-Z0-9._/-]+)\b', query)
