"""
CLI entry point for axonx.

Usage:
  agent init --workspace <path> [--provider claude|ollama]
  agent chat [--provider claude|ollama] [--resume]
  agent modify "<instruction>" [--dry-run] [--provider claude|ollama]
  agent undo / redo / reset
  agent scope --path <subpath> / --clear
  agent index status / rebuild
  agent branches
  agent sessions --list / --resume <id> / --delete <id>
  agent context show / replay
  agent usage [--all]
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import click

from .config import load_config, Config
from .session import SessionStore


def _apply_model(config: Config, provider: str | None, model: str) -> None:
    """Override model fields on config for the active provider."""
    backend = provider or config.provider.default
    if backend == "claude":
        config.models.claude_reasoning = model
        config.models.claude_coding = model
        config.models.claude_summarise = model
    else:
        config.models.reasoning = model
        config.models.coding = model


# ------------------------------------------------------------------
# Root group
# ------------------------------------------------------------------

@click.group()
@click.pass_context
def main(ctx):
    """AxonX Workspace — local AI code intelligence engine."""
    ctx.ensure_object(dict)


# ------------------------------------------------------------------
# agent init
# ------------------------------------------------------------------

@main.command()
@click.option("--workspace", "-w", required=True, type=click.Path(exists=True), help="Path to workspace")
@click.option("--provider", type=click.Choice(["ollama", "claude"]), default=None)
@click.option("--model", default=None, help="Override LLM model name for the active provider")
def init(workspace: str, provider: str | None, model: str | None):
    """Seed the index for a workspace."""
    from .indexer.seed import seed_workspace

    config = load_config(workspace)
    if provider:
        config.provider.default = provider
    if model:
        _apply_model(config, provider, model)

    click.echo(f"Initialising index for {workspace} ...")
    manifest = seed_workspace(config, provider_override=provider)
    click.echo(f"Done. {manifest['chunk_count']} chunks indexed from {manifest['file_count']} files.")
    click.echo(f"Starting file watcher ...")
    _start_watcher(config)


# ------------------------------------------------------------------
# agent chat
# ------------------------------------------------------------------

@main.command()
@click.option("--workspace", "-w", default=".", type=click.Path(exists=True))
@click.option("--provider", type=click.Choice(["ollama", "claude"]), default=None)
@click.option("--model", default=None, help="Override LLM model name for the active provider")
@click.option("--resume/--no-resume", default=True, help="Resume last session (default: yes)")
@click.option("--serve", is_flag=True, default=False, help="Also start the HTTP sidebar server on port 7070")
@click.option("--port", default=7070, help="Port for the sidebar server (default: 7070)")
def chat(workspace: str, provider: str | None, model: str | None, resume: bool, serve: bool, port: int):
    """Start an interactive chat session."""
    config = load_config(workspace)
    if provider:
        config.provider.default = provider
    if model:
        _apply_model(config, provider, model)

    _run_chat_loop(config, provider_override=provider, auto_resume=resume, serve=serve, server_port=port)


# ------------------------------------------------------------------
# agent serve — start server only (no terminal chat loop)
# ------------------------------------------------------------------

@main.command()
@click.option("--workspace", "-w", default=".", type=click.Path(exists=True))
@click.option("--provider", type=click.Choice(["ollama", "claude"]), default=None)
@click.option("--model", default=None, help="Override LLM model name for the active provider")
@click.option("--port", default=7070, help="Port for the sidebar server (default: 7070)")
def serve(workspace: str, provider: str | None, model: str | None, port: int):
    """Start the HTTP sidebar server and agent loop (no terminal chat prompt)."""
    config = load_config(workspace)
    if provider:
        config.provider.default = provider
    if model:
        _apply_model(config, provider, model)
    _run_chat_loop(config, provider_override=provider, auto_resume=True, serve=True, server_port=port, headless=True)


# ------------------------------------------------------------------
# agent modify
# ------------------------------------------------------------------

@main.command()
@click.argument("instruction")
@click.option("--workspace", "-w", default=".", type=click.Path(exists=True))
@click.option("--provider", type=click.Choice(["ollama", "claude"]), default=None)
@click.option("--model", default=None, help="Override LLM model name for the active provider")
@click.option("--dry-run", is_flag=True, default=False, help="Show plan only, no writes")
def modify(instruction: str, workspace: str, provider: str | None, model: str | None, dry_run: bool):
    """Apply a natural language code modification."""
    from .agents.codeact_agent import CodeActAgent
    from .index.faiss_store import FAISSStore
    from .index.graph_store import GraphStore
    from .index.branch_index import detect_current_branch

    config = load_config(workspace)
    if provider:
        config.provider.default = provider
    if model:
        _apply_model(config, provider, model)

    branch = detect_current_branch(config.workspace_path)
    index_dir = config.agent_dir / "index" / "branches" / branch
    faiss = FAISSStore(index_dir / "vectors")
    graph = GraphStore(index_dir / "graph.db")

    agent = CodeActAgent(config, faiss, graph, provider_override=provider)
    result = agent.run(instruction, dry_run=dry_run)

    click.echo(result.content)

    if not dry_run and result.citations:
        # Ask for approval
        from .agents.codeact_agent import Plan
        from .ui.plan_renderer import prompt_approval
        answer = prompt_approval()
        if answer == "yes" and hasattr(agent, "_current_plan"):
            exec_result = agent.execute_plan(agent._current_plan)
            click.echo(exec_result.content)
        elif answer == "cancel":
            click.echo("Cancelled.")

    faiss.close()
    graph.close()


# ------------------------------------------------------------------
# agent undo / redo / reset
# ------------------------------------------------------------------

@main.command()
@click.option("--workspace", "-w", default=".", type=click.Path(exists=True))
def undo(workspace: str):
    """Undo the last code operation."""
    from .git.undo_redo import undo_last_operation
    from .index.branch_index import detect_current_branch

    config = load_config(workspace)
    store = SessionStore()
    branch = detect_current_branch(config.workspace_path)
    session = store.get_or_create(str(config.workspace_path), branch)

    ops = store.get_pending_operations(session.id)
    if not ops:
        click.echo("Nothing to undo.")
        return

    last_op = ops[-1]
    msg = undo_last_operation(
        workspace=config.workspace_path,
        checkpoint_ref=last_op.checkpoint_ref,
        files_affected=last_op.files_affected,
        working_branch=last_op.working_branch,
    )
    store.rollback_operation(last_op.id)
    click.echo(msg)


@main.command()
@click.option("--workspace", "-w", default=".", type=click.Path(exists=True))
def reset(workspace: str):
    """Discard working branch and return to base branch."""
    from .git.branch_manager import current_branch, delete_branch, switch_to_branch
    from .git.undo_redo import reset_to_base

    config = load_config(workspace)
    wb = current_branch(config.workspace_path)
    if wb.startswith("agent/change-"):
        msg = reset_to_base(config.workspace_path, "main", wb)
    else:
        msg = f"Not on a working branch (current: {wb})."
    click.echo(msg)


# ------------------------------------------------------------------
# agent scope
# ------------------------------------------------------------------

@main.command()
@click.option("--path", default=None, help="Pin scope to this subfolder")
@click.option("--clear", is_flag=True, default=False, help="Remove scope restriction")
@click.option("--workspace", "-w", default=".", type=click.Path(exists=True))
def scope(path: str | None, clear: bool, workspace: str):
    """Pin or clear the agent's scope to a subfolder."""
    config = load_config(workspace)
    store = SessionStore()
    from .index.branch_index import detect_current_branch
    branch = detect_current_branch(config.workspace_path)
    session = store.get_or_create(str(config.workspace_path), branch)

    if clear:
        store.update_session(session.id, scope_pin="")
        click.echo("Scope cleared — agent can access entire workspace.")
    elif path:
        store.update_session(session.id, scope_pin=path)
        click.echo(f"Scope pinned to: {path}")
    else:
        current = session.scope_pin or "(none)"
        click.echo(f"Current scope: {current}")


# ------------------------------------------------------------------
# agent index
# ------------------------------------------------------------------

@main.group()
def index():
    """Index management commands."""


@index.command("status")
@click.option("--workspace", "-w", default=".", type=click.Path(exists=True))
def index_status(workspace: str):
    """Show index health and staleness."""
    from .index.staleness import StalenessChecker
    from .index.branch_index import detect_current_branch

    config = load_config(workspace)
    branch = detect_current_branch(config.workspace_path)
    index_dir = config.agent_dir / "index" / "branches" / branch

    checker = StalenessChecker(config.workspace_path, index_dir)
    status = checker.status()

    click.echo(f"Status: {status['status']}")
    click.echo(f"  {status['message']}")
    if status.get("file_count"):
        click.echo(f"  Files: {status['file_count']}, Chunks: {status.get('chunk_count', '?')}")
    if status.get("stale_files"):
        click.echo(f"  Stale files:")
        for f in status["stale_files"][:10]:
            click.echo(f"    - {f}")


@index.command("rebuild")
@click.option("--workspace", "-w", default=".", type=click.Path(exists=True))
@click.option("--provider", type=click.Choice(["ollama", "claude"]), default=None)
@click.option("--model", default=None, help="Override LLM model name for the active provider")
def index_rebuild(workspace: str, provider: str | None, model: str | None):
    """Force a full re-seed of the index."""
    from .indexer.seed import seed_workspace

    config = load_config(workspace)
    if provider:
        config.provider.default = provider
    if model:
        _apply_model(config, provider, model)
    click.echo("Rebuilding index ...")
    manifest = seed_workspace(config, provider_override=provider)
    click.echo(f"Done. {manifest['chunk_count']} chunks from {manifest['file_count']} files.")


# ------------------------------------------------------------------
# agent branches
# ------------------------------------------------------------------

@main.command()
@click.option("--workspace", "-w", default=".", type=click.Path(exists=True))
def branches(workspace: str):
    """List branches and their index status."""
    from .index.branch_index import BranchIndex, detect_current_branch

    config = load_config(workspace)
    current = detect_current_branch(config.workspace_path)
    bi = BranchIndex(config.agent_dir)
    branch_list = bi.list_branches()

    click.echo(f"{'BRANCH':<30} {'INDEXED':<10} {'COMMIT'}")
    for b in branch_list:
        marker = "* " if b["branch"] == current else "  "
        click.echo(
            f"{marker}{b['branch']:<28} {'yes' if b['indexed'] else 'no':<10} {b['latest_commit'][:7]}"
        )


# ------------------------------------------------------------------
# agent sessions
# ------------------------------------------------------------------

@main.group()
def sessions():
    """Session management commands."""


@sessions.command("list")
@click.option("--workspace", "-w", default=".", type=click.Path(exists=True))
def sessions_list(workspace: str):
    """List all past sessions for this workspace."""
    config = load_config(workspace)
    store = SessionStore()
    session_list = store.list_sessions(str(config.workspace_path))

    if not session_list:
        click.echo("No sessions found.")
        return

    click.echo(f"{'ID':<38} {'BRANCH':<20} {'LAST ACTIVE':<22} {'MSGS':<6} {'PENDING'}")
    for s in session_list:
        click.echo(
            f"{s.id:<38} {s.current_branch:<20} {s.last_active[:19]:<22} "
            f"{s.message_count:<6} {s.pending_operations}"
        )


@sessions.command("resume")
@click.argument("session_id")
@click.option("--workspace", "-w", default=".", type=click.Path(exists=True))
@click.option("--provider", type=click.Choice(["ollama", "claude"]), default=None)
def sessions_resume(session_id: str, workspace: str, provider: str | None):
    """Resume a specific past session."""
    config = load_config(workspace)
    if provider:
        config.provider.default = provider
    _run_chat_loop(config, provider_override=provider, session_id=session_id)


@sessions.command("delete")
@click.argument("session_id")
@click.confirmation_option(prompt="Delete this session and all history?")
def sessions_delete(session_id: str):
    """Delete a session and its history."""
    store = SessionStore()
    store.delete_session(session_id)
    click.echo(f"Session {session_id} deleted.")


# ------------------------------------------------------------------
# agent context
# ------------------------------------------------------------------

@main.group()
def context():
    """Context inspection commands."""


@context.command("show")
@click.option("--workspace", "-w", default=".", type=click.Path(exists=True))
def context_show(workspace: str):
    """Show what context was used for the last answer."""
    from .index.branch_index import detect_current_branch

    config = load_config(workspace)
    store = SessionStore()
    branch = detect_current_branch(config.workspace_path)
    session = store.get_or_create(str(config.workspace_path), branch)

    last_msg = store.get_last_message(session.id)
    if not last_msg:
        click.echo("No messages in this session.")
        return

    snapshot = store.get_context_snapshot(last_msg.id)
    if not snapshot:
        click.echo("No context snapshot recorded for last message.")
        return

    click.echo(f"Chunks used ({len(snapshot['chunk_ids'])}):")
    for cid in snapshot["chunk_ids"][:10]:
        click.echo(f"  - {cid}")

    if snapshot["skill_cards"]:
        click.echo(f"\nSkill cards:")
        for sc in snapshot["skill_cards"]:
            click.echo(f"  - {sc}")


# ------------------------------------------------------------------
# agent usage
# ------------------------------------------------------------------

@main.command()
@click.option("--workspace", "-w", default=".", type=click.Path(exists=True))
@click.option("--all", "show_all", is_flag=True, default=False, help="Show all sessions")
def usage(workspace: str, show_all: bool):
    """Show token usage by provider."""
    from .index.branch_index import detect_current_branch

    config = load_config(workspace)
    store = SessionStore()

    if show_all:
        rows = store.get_all_token_usage()
        click.echo("All-time token usage:")
    else:
        branch = detect_current_branch(config.workspace_path)
        session = store.get_or_create(str(config.workspace_path), branch)
        rows = store.get_token_usage_report(session.id)
        click.echo("This session token usage:")

    if not rows:
        click.echo("  No usage recorded.")
        return

    click.echo(f"  {'PROVIDER':<10} {'MODEL':<30} {'IN':>10} {'OUT':>10} {'CALLS':>6}")
    for r in rows:
        click.echo(
            f"  {r['provider']:<10} {r['model']:<30} "
            f"{r['input_tokens']:>10,} {r['output_tokens']:>10,} {r['calls']:>6}"
        )


# ------------------------------------------------------------------
# Chat loop implementation
# ------------------------------------------------------------------

def _run_chat_loop(
    config,
    provider_override: str | None = None,
    auto_resume: bool = True,
    session_id: str | None = None,
    serve: bool = False,
    server_port: int = 7070,
    headless: bool = False,
) -> None:
    """Main interactive chat loop (optionally with HTTP sidebar server)."""
    import queue as _queue

    from .agents.codeact_agent import CodeActAgent
    from .agents.orchestrator import Orchestrator
    from .agents.rag_agent import RagAgent
    from .agents.version_agent import VersionAgent
    from .context_manager import ContextManager
    from .git.branch_manager import current_branch as get_branch
    from .git.commit_writer import generate_commit_message, stage_and_commit
    from .git.conflict_resolver import find_conflicts, format_conflicts_for_chat
    from .git.undo_redo import undo_last_operation
    from .index.branch_index import detect_current_branch
    from .index.faiss_store import FAISSStore
    from .index.graph_store import GraphStore
    from .llm.factory import build_provider
    from .router import Router
    from .session import SessionStore
    from .ui.chat import ChatUI
    from .ui.diff_renderer import render_workspace_diff
    from .ui.plan_renderer import prompt_approval, render_operation_result, render_plan

    ui = ChatUI()
    store = SessionStore()
    router = Router()

    workspace = config.workspace_path
    branch = detect_current_branch(workspace)

    # Get or create session
    if session_id:
        session = store.get_or_create(str(workspace), branch, config.provider.default)
        session.id = session_id
        session.is_resumed = True
    elif auto_resume:
        session = store.get_or_create(str(workspace), branch, config.provider.default)
    else:
        import uuid as _uuid
        session = store.get_or_create(str(workspace) + str(_uuid.uuid4()), branch)

    # Open FAISS + graph stores
    index_dir = config.agent_dir / "index" / "branches" / branch
    faiss = FAISSStore(index_dir / "vectors")
    graph = GraphStore(index_dir / "graph.db")

    # Build agents
    rag = RagAgent(config, faiss, graph, provider_override)
    codeact = CodeActAgent(config, faiss, graph, provider_override)
    version = VersionAgent(config, provider_override)
    orchestrator = Orchestrator(config, faiss, graph, provider_override)

    # Build LLM provider for context manager / summarisation
    provider = build_provider("reasoning", config, override=provider_override)

    # ------------------------------------------------------------------
    # Optional HTTP sidebar server
    # ------------------------------------------------------------------
    srv = None
    if serve:
        from .server import state as _srv_state, start_server, is_port_available
        from .index.staleness import StalenessChecker

        # Populate shared state so API handlers can read it
        _srv_state.workspace   = str(workspace)
        _srv_state.branch      = branch
        _srv_state.provider    = config.provider.default
        _srv_state.session_id  = session.id

        checker = StalenessChecker(workspace, index_dir)
        _srv_state.index_status = checker.status()

        # Queue that the server uses to inject messages into the chat loop
        _inject_queue: _queue.Queue = _queue.Queue()

        def _inject(text: str) -> None:
            _inject_queue.put(text)

        _srv_state.chat_fn = _inject

        if is_port_available(server_port):
            srv = start_server(server_port)
            if not headless:
                click.echo(f"Sidebar server: http://localhost:{server_port}")
        else:
            if not headless:
                click.echo(f"Port {server_port} already in use — connecting to existing server.")
    else:
        _inject_queue = None

    # ------------------------------------------------------------------
    # Banner + startup checks
    # ------------------------------------------------------------------
    last_msg = store.get_last_message(session.id)
    pending = store.get_pending_operations(session.id)

    if not headless:
        ui.print_banner(
            workspace=str(workspace),
            branch=branch,
            provider=config.provider.default,
            resumed=session.is_resumed,
            last_message=last_msg.content if last_msg else "",
            pending_ops=len(pending),
        )

        conflicts = find_conflicts(workspace)
        if conflicts:
            ui.print_info(format_conflicts_for_chat(conflicts))

        ui.print_info("Type 'exit' or press Ctrl+C to quit.")

    # ------------------------------------------------------------------
    # Helpers shared by both terminal and server approval paths
    # ------------------------------------------------------------------

    def _run_modify(user_input: str) -> str:
        """Execute a modify instruction end-to-end. Returns assistant reply."""
        result = codeact.run(user_input, session=session)

        if not (hasattr(codeact, "_current_plan") and codeact._current_plan):
            return result.content

        plan = codeact._current_plan

        # Broadcast plan to sidebar clients
        if serve:
            from .server import state as _s
            _s.pending_plan = {
                "summary": plan.summary,
                "files":   plan.files,
                "steps":   [{"step": s.step, "file": s.file, "description": s.description}
                            for s in plan.steps],
            }
            _s.broadcast("plan", _s.pending_plan)
            _s.approval_event.clear()

        # Get approval — from sidebar (non-blocking wait) or terminal prompt
        if serve:
            from .server import state as _s
            approved = _s.approval_event.wait(timeout=300)  # 5 min timeout
            answer = _s.approval_result if approved else "cancel"
            _s.pending_plan = None
            _s.broadcast("plan_cleared", {})
        else:
            render_plan(plan, console=ui.console)
            answer = prompt_approval(console=ui.console)

        if answer == "yes":
            op_id = store.save_operation(
                session_id=session.id,
                type="modify",
                instruction=user_input,
                plan=[s.__dict__ for s in plan.steps],
                files=plan.files,
            )
            exec_result = codeact.execute_plan(plan, session=session)
            if not headless:
                render_operation_result(exec_result.content, console=ui.console)
            store.complete_operation(op_id)
            store.save_message(
                session_id=session.id,
                role="assistant",
                content=exec_result.content,
                agent_type="codeact",
                provider=config.provider.default,
            )
            return exec_result.content
        else:
            return "Cancelled."

    def _process_message(user_input: str) -> None:
        """Route a message, run the agent, broadcast/display the result."""
        # Save user message
        store.save_message(session_id=session.id, role="user", content=user_input)

        # Broadcast to sidebar
        if serve:
            from .server import state as _s
            _s.broadcast("user_message", {"content": user_input})

        route = router.classify(user_input)

        if route.intent == "modify":
            reply = _run_modify(user_input)
            if not headless:
                ui.print_assistant(reply, agent_type="codeact")
            if serve:
                from .server import state as _s
                _s.broadcast("assistant_message", {"content": reply, "agent": "codeact"})

        elif route.intent == "version":
            result = version.run(user_input, session=session)
            reply = result.content
            if not headless:
                ui.print_assistant(reply, agent_type="version")
            store.save_message(session_id=session.id, role="assistant", content=reply,
                               agent_type="version", provider=config.provider.default)
            if serve:
                from .server import state as _s
                _s.broadcast("assistant_message", {"content": reply, "agent": "version"})

        elif route.intent == "compound":
            result = orchestrator.run(user_input, session=session, sub_tasks=route.sub_tasks)
            reply = result.content
            if not headless:
                ui.print_assistant(reply, agent_type="orchestrator")
                ui.print_citations(result.citations)
            store.save_message(session_id=session.id, role="assistant", content=reply,
                               agent_type="orchestrator", provider=config.provider.default)
            if serve:
                from .server import state as _s
                _s.broadcast("assistant_message", {
                    "content": reply, "agent": "orchestrator",
                    "citations": result.citations,
                })

        else:  # qa
            result = rag.run(user_input, session=session, scope=route.scope)
            reply = result.content
            if not headless:
                ui.print_assistant(reply, agent_type="rag")
                ui.print_citations(result.citations)
            assistant_msg_id = store.save_message(
                session_id=session.id, role="assistant", content=reply,
                agent_type="rag", provider=config.provider.default)
            if config.context_store.store_rag_snapshots and result.used_chunks:
                store.save_context_snapshot(
                    message_id=assistant_msg_id,
                    chunk_ids=result.used_chunks,
                    skill_cards=result.used_skill_cards,
                )
            if serve:
                from .server import state as _s
                _s.broadcast("assistant_message", {
                    "content": reply, "agent": "rag",
                    "citations": result.citations,
                })

        # Periodic summarisation
        store.summarise_old_turns(
            session_id=session.id,
            provider=provider,
            summarise_after_turns=config.session.summarise_after_turns,
            keep_recent_turns=config.session.keep_recent_turns,
        )

    # ------------------------------------------------------------------
    # Main event loop
    # ------------------------------------------------------------------
    while True:
        # Pull from server inject queue (non-blocking) OR terminal input
        if _inject_queue is not None:
            try:
                user_input = _inject_queue.get_nowait()
            except _queue.Empty:
                user_input = None

            if user_input is None:
                if headless:
                    import time
                    time.sleep(0.05)
                    continue
                # Fall through to terminal input when not headless
                try:
                    user_input = ui.get_input()
                except (KeyboardInterrupt, EOFError):
                    ui.print_info("\nGoodbye.")
                    break
        else:
            try:
                user_input = ui.get_input()
            except (KeyboardInterrupt, EOFError):
                ui.print_info("\nGoodbye.")
                break

        if not user_input:
            continue

        cmd = user_input.lower().strip()

        # Built-in terminal commands (ignored in headless mode)
        if cmd in ("exit", "quit", "bye"):
            if not headless:
                ui.print_info("Goodbye.")
            break
        elif cmd == "diff" and not headless:
            render_workspace_diff(workspace, console=ui.console)
            continue
        elif cmd == "undo":
            ops = store.get_pending_operations(session.id)
            if ops:
                last_op = ops[-1]
                msg = undo_last_operation(
                    workspace=workspace,
                    checkpoint_ref=last_op.checkpoint_ref,
                    files_affected=last_op.files_affected,
                    working_branch=last_op.working_branch,
                )
                store.rollback_operation(last_op.id)
                if not headless:
                    ui.print_assistant(msg)
                if serve:
                    from .server import state as _s
                    _s.broadcast("assistant_message", {"content": msg, "agent": "system"})
            else:
                if not headless:
                    ui.print_info("Nothing to undo.")
            continue
        elif cmd.startswith("commit") and not headless:
            msg = generate_commit_message(workspace, provider)
            ui.print_info(f"Proposed commit message:\n  {msg}")
            confirm = input("Commit? (yes/no): ").strip().lower()
            if confirm == "yes":
                try:
                    commit_hash = stage_and_commit(workspace, [], msg)
                    ui.print_assistant(f"Committed: {commit_hash[:7]}")
                    for op in store.get_pending_operations(session.id):
                        store.complete_operation(op.id)
                except Exception as exc:
                    ui.print_error(str(exc))
            continue

        _process_message(user_input)

    faiss.close()
    graph.close()
    if srv:
        srv.shutdown()


# ------------------------------------------------------------------
# Start file watcher (background daemon)
# ------------------------------------------------------------------

def _start_watcher(config) -> None:
    """Start a background file watcher for incremental index updates."""
    import threading
    from .index.branch_index import detect_current_branch
    from .index.faiss_store import FAISSStore
    from .index.graph_store import GraphStore
    from .indexer.exclusions import load_exclusions
    from .indexer.incremental import IncrementalIndexer
    from .watcher import FileWatcher

    workspace = config.workspace_path
    branch = detect_current_branch(workspace)
    index_dir = config.agent_dir / "index" / "branches" / branch
    exclusions = load_exclusions(workspace)

    indexer = IncrementalIndexer(
        index_dir=index_dir,
        workspace_root=workspace,
        exclusions=exclusions,
    )

    watcher = FileWatcher(
        workspace=workspace,
        indexer=indexer,
        exclusions=exclusions,
        debounce_ms=config.index.incremental_debounce_ms,
    )

    t = threading.Thread(target=watcher.start, daemon=True)
    t.start()
    click.echo(f"File watcher started (debounce: {config.index.incremental_debounce_ms}ms)")


if __name__ == "__main__":
    main()
