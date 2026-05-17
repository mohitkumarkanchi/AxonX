"""Detect and surface merge conflicts in the workspace."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ConflictBlock:
    filepath: str
    ours: str
    theirs: str
    start_line: int


def find_conflicts(workspace: Path) -> list[ConflictBlock]:
    """Scan workspace for files containing conflict markers."""
    conflicts: list[ConflictBlock] = []

    # Ask git which files have conflicts
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=U"],
        cwd=str(workspace),
        capture_output=True,
        text=True,
    )
    conflicted_files = [
        workspace / f for f in result.stdout.strip().splitlines() if f
    ]

    for filepath in conflicted_files:
        try:
            blocks = _parse_conflict_blocks(filepath)
            conflicts.extend(blocks)
        except OSError:
            pass

    return conflicts


def _parse_conflict_blocks(filepath: Path) -> list[ConflictBlock]:
    """Parse <<<<<<< ... ======= ... >>>>>>> blocks from a file."""
    content = filepath.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines()
    blocks: list[ConflictBlock] = []

    i = 0
    while i < len(lines):
        if lines[i].startswith("<<<<<<<"):
            start = i + 1
            ours_lines: list[str] = []
            theirs_lines: list[str] = []
            in_theirs = False
            j = i + 1

            while j < len(lines):
                if lines[j].startswith("======="):
                    in_theirs = True
                elif lines[j].startswith(">>>>>>>"):
                    break
                elif in_theirs:
                    theirs_lines.append(lines[j])
                else:
                    ours_lines.append(lines[j])
                j += 1

            blocks.append(ConflictBlock(
                filepath=str(filepath),
                ours="\n".join(ours_lines),
                theirs="\n".join(theirs_lines),
                start_line=start,
            ))
            i = j + 1
        else:
            i += 1

    return blocks


def resolve_conflict(
    filepath: str,
    start_line: int,
    keep: str,  # "ours" | "theirs" | "both"
) -> None:
    """
    Resolve a conflict block by keeping one side.
    keep="ours": keep the HEAD version
    keep="theirs": keep the MERGE_HEAD version
    keep="both": keep both (concatenated)
    """
    path = Path(filepath)
    content = path.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines(keepends=True)
    result_lines: list[str] = []

    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("<<<<<<<"):
            ours: list[str] = []
            theirs: list[str] = []
            in_theirs = False
            j = i + 1
            while j < len(lines):
                l = lines[j]
                if l.startswith("======="):
                    in_theirs = True
                elif l.startswith(">>>>>>>"):
                    break
                elif in_theirs:
                    theirs.append(l)
                else:
                    ours.append(l)
                j += 1

            if keep == "ours":
                result_lines.extend(ours)
            elif keep == "theirs":
                result_lines.extend(theirs)
            else:  # both
                result_lines.extend(ours)
                result_lines.extend(theirs)

            i = j + 1
        else:
            result_lines.append(line)
            i += 1

    path.write_text("".join(result_lines), encoding="utf-8")


def format_conflicts_for_chat(conflicts: list[ConflictBlock]) -> str:
    """Format conflict blocks for display in the terminal chat."""
    if not conflicts:
        return "No merge conflicts found."

    lines = [f"Found {len(conflicts)} conflict block(s):\n"]
    for i, block in enumerate(conflicts, 1):
        lines.append(f"Conflict {i} — {block.filepath}:{block.start_line}")
        lines.append("  OURS:\n" + "\n".join(f"  | {l}" for l in block.ours.splitlines()[:8]))
        lines.append("  THEIRS:\n" + "\n".join(f"  | {l}" for l in block.theirs.splitlines()[:8]))
        lines.append(
            f"\nOptions: resolve conflict {i} [keep mine | keep theirs | keep both]\n"
        )

    return "\n".join(lines)
