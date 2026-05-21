"""Generate or regenerate SKILL.md cards for a module using the LLM."""

from __future__ import annotations

from pathlib import Path

from ..llm.provider import LLMProvider, Message


def write_skill_card(
    module_name: str,
    symbols: list[str],
    sample_content: str,
    skills_dir: Path,
    provider: LLMProvider,
    force: bool = False,
) -> Path:
    """
    Generate a SKILL.md card for a module.
    Returns the path to the written card.
    """
    skills_dir.mkdir(parents=True, exist_ok=True)
    safe_name = module_name.replace("/", "_").replace("\\", "_")
    card_path = skills_dir / f"{safe_name}.md"

    if card_path.exists() and not force:
        return card_path

    prompt = (
        f"Module: {module_name}\n"
        f"Public symbols: {', '.join(symbols[:30])}\n\n"
        f"Sample code:\n{sample_content[:1500]}\n\n"
        "Write a 3-5 sentence SKILL.md card describing:\n"
        "1. What this module does\n"
        "2. Its main responsibilities\n"
        "3. Key public symbols and their purpose\n"
        "Be concise and developer-focused. No markdown headers."
    )

    try:
        response = provider.chat(
            [Message(role="user", content=prompt)],
            max_tokens=300,
        )
        content = f"# {module_name}\n\n{response.content.strip()}\n\n"
        if symbols:
            content += f"**Key symbols**: `{'`, `'.join(symbols[:15])}`\n"
        card_path.write_text(content, encoding="utf-8")
    except Exception as exc:
        card_path.write_text(
            f"# {module_name}\n\n*(Auto-generation failed: {exc})*\n",
            encoding="utf-8",
        )

    return card_path


def load_skill_card(module_name: str, skills_dir: Path) -> str:
    """Load a SKILL.md card by module name, or return empty string."""
    safe_name = module_name.replace("/", "_").replace("\\", "_")
    card_path = skills_dir / f"{safe_name}.md"
    if card_path.exists():
        return card_path.read_text(encoding="utf-8")
    return ""


def list_skill_cards(skills_dir: Path) -> list[Path]:
    """Return all existing SKILL.md card paths."""
    if not skills_dir.exists():
        return []
    return sorted(skills_dir.glob("*.md"))
