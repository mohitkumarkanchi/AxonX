"""
CodeAct agent — plan → approve → edit → syntax check → test.

Steps:
1. Locate target symbols in graph index
2. Read target file(s) + direct imports into context
3. Generate PLAN via coding LLM — numbered steps, files affected
4. SHOW PLAN to user → wait for approval
5. On approval:
   a. guardrails.check() — protected branch? scope? file count?
   b. checkpoint.create() — git stash snapshot
   c. branch_manager.create_working_branch()
   d. For each file in plan: apply str_replace edit → syntax check → update index
   e. Run test suite if detected
   f. Show diff summary
6. Ask: "Commit? (yes / undo / keep)"
"""

from __future__ import annotations

import ast
import json
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ..agents.base import AgentResult, BaseAgent
from ..config import Config
from ..index.faiss_store import FAISSStore
from ..index.graph_store import GraphStore
from ..indexer.embedder import embed_text
from ..indexer.incremental import IncrementalIndexer
from ..indexer.exclusions import load_exclusions
from ..llm.factory import build_provider
from ..llm.provider import Message

if TYPE_CHECKING:
    pass


PLAN_SYSTEM = """\
You are a senior software engineer planning a code change.
Given an instruction and relevant code context, output a JSON plan:
{
  "summary": "One sentence describing the change",
  "files": ["list of file paths that will be modified"],
  "steps": [
    {"step": 1, "file": "path/to/file.py", "description": "what to change", "edit": {"old": "exact string to replace", "new": "replacement string"}}
  ]
}
Output ONLY the JSON. No explanation. No markdown fences.
Each step MUST include the exact "old" string to replace and the "new" replacement.
"""

EDIT_SYSTEM = """\
You are a senior software engineer. Given a code file and an instruction,
produce a SINGLE str_replace edit as JSON:
{"old": "exact string to find and replace", "new": "replacement string"}
The "old" value must be an exact substring of the file content.
Output ONLY the JSON. No explanation.
"""


@dataclass
class EditStep:
    step: int
    file: str
    description: str
    old: str = ""
    new: str = ""


@dataclass
class Plan:
    summary: str
    files: list[str]
    steps: list[EditStep]


class CodeActAgent(BaseAgent):
    agent_type = "codeact"

    def __init__(
        self,
        config: Config,
        faiss_store: FAISSStore,
        graph_store: GraphStore,
        provider_override: str | None = None,
    ) -> None:
        self._config = config
        self._faiss = faiss_store
        self._graph = graph_store
        self._provider = build_provider("coding", config, override=provider_override)
        self._provider_name = provider_override or config.provider.default

    def run(self, instruction: str, session=None, dry_run: bool = False) -> AgentResult:
        # 1. Find target context via semantic search
        context_chunks = self._fetch_context(instruction)

        # 2. Generate plan
        plan = self._generate_plan(instruction, context_chunks)
        if plan is None:
            return AgentResult(
                content="Could not generate a valid plan. Try a more specific instruction.",
                agent_type=self.agent_type,
                citations=[],
                used_chunks=[],
                used_skill_cards=[],
            )

        # Dry-run: show plan only, no writes
        if dry_run:
            return AgentResult(
                content=self._format_plan(plan) + "\n\n[DRY RUN — no files modified]",
                agent_type=self.agent_type,
                citations=[{"filepath": f} for f in plan.files],
                used_chunks=[],
                used_skill_cards=[],
            )

        # 3. Show plan and get approval (handled by caller — UI layer)
        # The session/UI layer calls approve() after showing plan
        self._current_plan = plan
        return AgentResult(
            content=self._format_plan(plan),
            agent_type=self.agent_type,
            citations=[{"filepath": f} for f in plan.files],
            used_chunks=[],
            used_skill_cards=[],
        )

    def execute_plan(
        self,
        plan: Plan,
        session=None,
        operation_id: str | None = None,
    ) -> AgentResult:
        """Execute an approved plan. Called after user approves."""
        from ..safety.guardrails import GuardrailError, check_operation
        from ..safety.checkpoint import create_checkpoint
        from ..git.branch_manager import create_working_branch

        workspace = self._config.workspace_path

        # a. Guardrails check
        try:
            check_operation(
                files=plan.files,
                workspace=workspace,
                config=self._config,
            )
        except GuardrailError as exc:
            return AgentResult(
                content=f"Blocked by guardrails: {exc}",
                agent_type=self.agent_type,
                citations=[],
                used_chunks=[],
                used_skill_cards=[],
            )

        # b. Checkpoint (git stash)
        checkpoint_ref = ""
        if self._config.safety.auto_checkpoint:
            try:
                checkpoint_ref = create_checkpoint(workspace)
            except Exception as exc:
                print(f"[codeact] Checkpoint warning: {exc}")

        # c. Create working branch
        working_branch = ""
        try:
            working_branch = create_working_branch(workspace)
        except Exception as exc:
            print(f"[codeact] Branch warning: {exc}")

        # d. Apply each step
        applied: list[str] = []
        errors: list[str] = []
        exclusions = load_exclusions(workspace)

        # Initialise incremental indexer for live index updates
        active_branch = working_branch or "main"
        branch_dir = self._config.agent_dir / "index" / "branches" / active_branch
        indexer = None
        try:
            indexer = IncrementalIndexer(
                index_dir=branch_dir,
                workspace_root=workspace,
                exclusions=exclusions,
            )
        except Exception:
            pass

        for step in plan.steps:
            filepath = Path(workspace / step.file if not Path(step.file).is_absolute() else step.file)

            if not filepath.exists():
                errors.append(f"Step {step.step}: file not found — {filepath}")
                continue

            # Apply str_replace edit
            try:
                original = filepath.read_text(encoding="utf-8")
                if step.old and step.old not in original:
                    errors.append(
                        f"Step {step.step}: could not find edit target in {filepath.name}"
                    )
                    continue

                if step.old:
                    modified = original.replace(step.old, step.new, 1)
                else:
                    modified = original + "\n" + step.new

                # Syntax check before writing
                if filepath.suffix == ".py":
                    syntax_ok, syntax_err = _check_python_syntax(modified)
                    if not syntax_ok:
                        errors.append(f"Step {step.step}: syntax error — {syntax_err}")
                        continue

                filepath.write_text(modified, encoding="utf-8")
                applied.append(str(filepath))

                # Incremental index update
                if indexer:
                    indexer.update_file(filepath)

            except Exception as exc:
                errors.append(f"Step {step.step}: {exc}")

        if indexer:
            indexer.close()

        # e. Run tests
        test_output = ""
        if self._config.tests.auto_run_after_modify and applied:
            test_output = _run_tests(workspace, self._config)

        # f. Build result message
        diff_text = _git_diff(workspace)
        lines = [f"Applied {len(applied)}/{len(plan.steps)} steps."]
        if errors:
            lines.append("\nErrors:")
            lines.extend(f"  - {e}" for e in errors)
        if test_output:
            lines.append(f"\nTests:\n{test_output[:800]}")
        if diff_text:
            lines.append(f"\nDiff summary:\n{diff_text[:2000]}")
        if working_branch:
            lines.append(f"\nWorking branch: {working_branch}")
        lines.append("\nCommit this? Type: yes / undo / keep")

        return AgentResult(
            content="\n".join(lines),
            agent_type=self.agent_type,
            citations=[{"filepath": f} for f in applied],
            used_chunks=[],
            used_skill_cards=[],
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_context(self, instruction: str, top_k: int = 8) -> list[dict]:
        """Semantic search for relevant code context."""
        try:
            vec = embed_text(instruction, model=self._config.models.embedding)
            return self._faiss.query(vec, top_k=top_k)
        except Exception:
            return []

    def _generate_plan(self, instruction: str, chunks: list[dict]) -> Plan | None:
        """Ask the coding LLM to produce an edit plan."""
        context = "\n\n".join(
            f"--- {r.get('filepath', '')}:{r.get('start_line', '')} ---\n{r.get('content', '')}"
            for r in chunks
        )

        prompt = (
            f"Instruction: {instruction}\n\n"
            f"Relevant code context:\n{context[:4000]}\n\n"
            "Produce the JSON edit plan."
        )

        try:
            response = self._provider.chat(
                messages=[Message(role="user", content=prompt)],
                system=PLAN_SYSTEM,
                max_tokens=2048,
            )
            return self._parse_plan(response.content)
        except Exception as exc:
            print(f"[codeact] Plan generation error: {exc}")
            return None

    def _parse_plan(self, raw: str) -> Plan | None:
        import re
        raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        raw = re.sub(r"\s*```$", "", raw)
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group())
            steps = []
            for i, s in enumerate(data.get("steps", []), 1):
                edit = s.get("edit", {})
                steps.append(EditStep(
                    step=i,
                    file=s.get("file", ""),
                    description=s.get("description", ""),
                    old=edit.get("old", ""),
                    new=edit.get("new", ""),
                ))
            return Plan(
                summary=data.get("summary", ""),
                files=data.get("files", [s.file for s in steps]),
                steps=steps,
            )
        except Exception:
            return None

    def _format_plan(self, plan: Plan) -> str:
        lines = [f"Plan: {plan.summary}", "", "Files affected:"]
        for f in plan.files:
            lines.append(f"  - {f}")
        lines.append("\nSteps:")
        for step in plan.steps:
            lines.append(f"  {step.step}. [{step.file}] {step.description}")
        return "\n".join(lines)


def _check_python_syntax(code: str) -> tuple[bool, str]:
    try:
        ast.parse(code)
        return True, ""
    except SyntaxError as e:
        return False, str(e)


def _git_diff(workspace: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "diff", "--stat"],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout
    except Exception:
        return ""


def _run_tests(workspace: Path, config) -> str:
    """Detect and run test suite, return output snippet."""
    commands = config.tests.test_commands

    # Priority: explicit test config files first, then generic markers.
    # pyproject.toml alone is not sufficient — it's present in many non-Python projects.
    is_python = (
        (workspace / "pytest.ini").exists()
        or (workspace / "setup.cfg").exists()
        or (workspace / "tox.ini").exists()
        or (
            (workspace / "pyproject.toml").exists()
            and not (workspace / "package.json").exists()
        )
    )
    is_js = (workspace / "package.json").exists()
    is_go = (workspace / "go.mod").exists()

    if is_python:
        cmd = commands.get("python", "pytest").split()
    elif is_js:
        cmd = commands.get("javascript", "npm test").split()
    elif is_go:
        cmd = commands.get("go", "go test ./...").split()
    else:
        return ""

    try:
        result = subprocess.run(
            cmd,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=120,
        )
        return (result.stdout + result.stderr)[:1000]
    except Exception as exc:
        return f"Test run failed: {exc}"
