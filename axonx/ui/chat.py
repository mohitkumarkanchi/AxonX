"""Rich-based terminal chat loop."""

from __future__ import annotations

from pathlib import Path

try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.prompt import Prompt
    from rich.rule import Rule
    from rich.text import Text
    _HAS_RICH = True
except ImportError:
    _HAS_RICH = False


class ChatUI:
    """Terminal chat interface."""

    def __init__(self) -> None:
        if _HAS_RICH:
            self._console = Console()
        else:
            self._console = None

    def print_banner(
        self,
        workspace: str,
        branch: str,
        provider: str,
        resumed: bool,
        last_message: str = "",
        pending_ops: int = 0,
    ) -> None:
        """Print the startup banner."""
        if _HAS_RICH:
            status = "[green]resumed[/green]" if resumed else "[blue]new session[/blue]"
            self._console.print(Panel(
                f"[bold]Agent Workspace[/bold]\n"
                f"Workspace: [cyan]{workspace}[/cyan]\n"
                f"Branch:    [yellow]{branch}[/yellow]\n"
                f"Provider:  [magenta]{provider}[/magenta]\n"
                f"Session:   {status}",
                title="[bold blue]Agent[/bold blue]",
                border_style="blue",
            ))
            if resumed and last_message:
                self._console.print(
                    f"[dim]Last message: \"{last_message[:80]}...\"[/dim]"
                )
            if pending_ops:
                self._console.print(
                    f"[bold yellow]⚠ {pending_ops} uncommitted operation(s) pending.[/bold yellow]\n"
                    "  Type [bold]agent operations[/bold] to review."
                )
        else:
            print(f"\n=== Agent Workspace ===")
            print(f"Workspace: {workspace} | Branch: {branch} | Provider: {provider}")
            if resumed:
                print(f"Resumed session. Last: \"{last_message[:60]}\"")

    def print_assistant(self, content: str, agent_type: str = "") -> None:
        """Render an assistant response."""
        if _HAS_RICH:
            label = f"[dim]{agent_type}[/dim] " if agent_type else ""
            self._console.print(f"\n[bold green]Agent {label}[/bold green]")
            try:
                self._console.print(Markdown(content))
            except Exception:
                self._console.print(content)
        else:
            print(f"\nAgent: {content}")

    def print_citations(self, citations: list[dict]) -> None:
        """Show file:line citations below the response."""
        if not citations:
            return
        seen: set[str] = set()
        refs = []
        for c in citations:
            fp = c.get("filepath", "")
            sl = c.get("start_line")
            ref = f"{fp}:{sl}" if sl else fp
            if ref and ref not in seen:
                seen.add(ref)
                refs.append(ref)

        if refs and _HAS_RICH:
            self._console.print(
                Text("Sources: " + " · ".join(refs[:6]), style="dim")
            )
        elif refs:
            print(f"Sources: {' | '.join(refs[:6])}")

    def print_error(self, message: str) -> None:
        if _HAS_RICH:
            self._console.print(f"[bold red]Error:[/bold red] {message}")
        else:
            print(f"Error: {message}")

    def print_info(self, message: str) -> None:
        if _HAS_RICH:
            self._console.print(f"[dim]{message}[/dim]")
        else:
            print(message)

    def print_rule(self, title: str = "") -> None:
        if _HAS_RICH:
            self._console.print(Rule(title, style="dim"))
        else:
            print("-" * 60)

    def get_input(self, prompt: str = "") -> str:
        """Get user input."""
        if _HAS_RICH:
            return Prompt.ask(
                f"\n[bold blue]You[/bold blue]",
                default="",
                show_default=False,
            )
        else:
            return input(f"\n{prompt}You: ").strip()

    def stream_tokens(self) -> "StreamContext":
        """Context manager for streaming LLM output."""
        return StreamContext(self._console)

    @property
    def console(self):
        return self._console


class StreamContext:
    """Context manager that buffers streamed tokens and prints them live."""

    def __init__(self, console) -> None:
        self._console = console
        self._buffer = ""

    def __enter__(self):
        if _HAS_RICH and self._console:
            self._console.print("\n[bold green]Agent[/bold green]", end=" ")
        else:
            print("\nAgent: ", end="", flush=True)
        return self

    def write(self, token: str) -> None:
        self._buffer += token
        if _HAS_RICH and self._console:
            self._console.print(token, end="")
        else:
            print(token, end="", flush=True)

    def __exit__(self, *args) -> None:
        print()  # newline after stream ends

    @property
    def full_content(self) -> str:
        return self._buffer
