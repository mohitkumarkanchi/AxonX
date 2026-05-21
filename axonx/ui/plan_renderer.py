"""Render CodeAct modify plans as numbered approval prompts."""

from __future__ import annotations

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    _HAS_RICH = True
except ImportError:
    _HAS_RICH = False


def render_plan(plan, console=None) -> None:
    """
    Render a Plan object as a numbered step list for user approval.
    plan: agents.codeact_agent.Plan
    """
    if not _HAS_RICH:
        print(f"\nPlan: {plan.summary}")
        print(f"\nFiles affected: {', '.join(plan.files)}")
        print("\nSteps:")
        for step in plan.steps:
            print(f"  {step.step}. [{step.file}] {step.description}")
        return

    if console is None:
        console = Console()

    table = Table(show_header=True, header_style="bold magenta", box=None)
    table.add_column("#", style="dim", width=3)
    table.add_column("File", style="cyan")
    table.add_column("Change")

    for step in plan.steps:
        table.add_row(str(step.step), step.file or "—", step.description)

    console.print(Panel(
        table,
        title=f"[bold]Plan: {plan.summary}[/bold]",
        subtitle=f"[dim]{len(plan.files)} file(s) affected[/dim]",
        border_style="yellow",
    ))


def prompt_approval(console=None) -> str:
    """
    Ask the user to approve, edit, or cancel the plan.
    Returns: "yes" | "cancel" | or user's free-text edit
    """
    if console is None and _HAS_RICH:
        from rich.console import Console
        console = Console()

    options = "[bold green]yes[/bold green] / [bold red]cancel[/bold red] / [dim]describe changes to edit plan[/dim]"

    if _HAS_RICH and console:
        console.print(f"\nApprove plan? {options}")
        response = input("> ").strip()
    else:
        print("\nApprove plan? (yes / cancel / describe edits)")
        response = input("> ").strip()

    return response.lower() if response.lower() in ("yes", "cancel") else response


def render_operation_result(result_content: str, console=None) -> None:
    """Display the result of a completed CodeAct operation."""
    if not _HAS_RICH:
        print(result_content)
        return

    if console is None:
        from rich.console import Console
        console = Console()

    console.print(Panel(
        result_content,
        title="[bold]Operation Result[/bold]",
        border_style="green",
    ))
