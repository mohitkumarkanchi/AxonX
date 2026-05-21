"""tree-sitter chunking — extract function/class/module-level chunks from source files."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

try:
    from tree_sitter_languages import get_language, get_parser
    _HAS_TSL = True
except ImportError:
    _HAS_TSL = False


EXTENSION_TO_LANG: dict[str, str] = {
    ".py":   "python",
    ".js":   "javascript",
    ".jsx":  "javascript",
    ".ts":   "typescript",
    ".tsx":  "tsx",
    ".go":   "go",
    ".rs":   "rust",
    ".rb":   "ruby",
    ".java": "java",
    ".c":    "c",
    ".cpp":  "cpp",
    ".cc":   "cpp",
    ".h":    "c",
    ".hpp":  "cpp",
    ".cs":   "c_sharp",
    ".kt":   "kotlin",
    ".swift":"swift",
    ".php":  "php",
    ".r":    "r",
    ".scala":"scala",
    ".sh":   "bash",
    ".bash": "bash",
    ".lua":  "lua",
    ".ex":   "elixir",
    ".exs":  "elixir",
    ".hs":   "haskell",
    ".ml":   "ocaml",
    ".md":   None,   # no tree-sitter — whole file as one chunk
    ".txt":  None,
    ".json": None,
    ".yaml": None,
    ".yml":  None,
    ".toml": None,
}

# Tree-sitter node types that represent top-level symbols
SYMBOL_NODES: dict[str, list[str]] = {
    "python":     ["function_definition", "async_function_definition", "class_definition"],
    "javascript": ["function_declaration", "function_expression", "arrow_function",
                   "class_declaration", "method_definition"],
    "typescript": ["function_declaration", "function_expression", "arrow_function",
                   "class_declaration", "method_definition", "interface_declaration",
                   "type_alias_declaration"],
    "tsx":        ["function_declaration", "function_expression", "arrow_function",
                   "class_declaration", "jsx_element"],
    "go":         ["function_declaration", "method_declaration", "type_declaration"],
    "rust":       ["function_item", "impl_item", "struct_item", "enum_item", "trait_item"],
    "ruby":       ["method", "singleton_method", "class", "module"],
    "java":       ["method_declaration", "class_declaration", "interface_declaration"],
    "c":          ["function_definition", "struct_specifier"],
    "cpp":        ["function_definition", "class_specifier", "struct_specifier"],
    "c_sharp":    ["method_declaration", "class_declaration", "interface_declaration"],
    "kotlin":     ["function_declaration", "class_declaration", "object_declaration"],
}


@dataclass
class Chunk:
    id: str              # sha256(filepath + symbol_name)
    filepath: str
    symbol: str          # function/class name, or "" for module-level
    kind: str            # "function" | "class" | "module" | "method"
    start_line: int
    end_line: int
    content: str
    language: str


def _chunk_id(filepath: str, symbol: str) -> str:
    key = f"{filepath}::{symbol}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _extract_name(node, source_bytes: bytes) -> str:
    """Extract the identifier/name from a node."""
    for child in node.children:
        if child.type in ("identifier", "name", "property_identifier",
                          "type_identifier", "field_identifier"):
            return source_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="replace")
    return ""


def _kind_for_node(node_type: str) -> str:
    if "class" in node_type or "struct" in node_type or "interface" in node_type:
        return "class"
    if "method" in node_type:
        return "method"
    if "function" in node_type or "arrow" in node_type:
        return "function"
    return "symbol"


def parse_file(filepath: str | Path) -> list[Chunk]:
    """Parse a source file into chunks using tree-sitter."""
    filepath = Path(filepath)
    suffix = filepath.suffix.lower()
    lang_name = EXTENSION_TO_LANG.get(suffix, None)

    try:
        source = filepath.read_bytes()
    except OSError:
        return []

    source_str = source.decode("utf-8", errors="replace")
    lines = source_str.splitlines()

    # Files with no tree-sitter support → one chunk per file
    if lang_name is None or not _HAS_TSL:
        return [Chunk(
            id=_chunk_id(str(filepath), "module"),
            filepath=str(filepath),
            symbol="module",
            kind="module",
            start_line=1,
            end_line=len(lines),
            content=source_str[:8000],  # cap very large files
            language=lang_name or "text",
        )]

    try:
        parser = get_parser(lang_name)
    except Exception:
        # Unknown language — fallback to whole-file chunk
        return [Chunk(
            id=_chunk_id(str(filepath), "module"),
            filepath=str(filepath),
            symbol="module",
            kind="module",
            start_line=1,
            end_line=len(lines),
            content=source_str[:8000],
            language=lang_name,
        )]

    tree = parser.parse(source)
    target_types = set(SYMBOL_NODES.get(lang_name, []))

    chunks: list[Chunk] = []
    covered_lines: set[int] = set()

    def walk(node) -> None:
        if node.type in target_types:
            name = _extract_name(node, source) or node.type
            start = node.start_point[0] + 1  # 1-indexed
            end = node.end_point[0] + 1
            content = source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
            chunks.append(Chunk(
                id=_chunk_id(str(filepath), name),
                filepath=str(filepath),
                symbol=name,
                kind=_kind_for_node(node.type),
                start_line=start,
                end_line=end,
                content=content[:4000],  # cap individual chunk size
                language=lang_name,
            ))
            for i in range(start, end + 1):
                covered_lines.add(i)
        for child in node.children:
            walk(child)

    walk(tree.root_node)

    # Add a module-level chunk for top-level code not covered by any symbol
    uncovered = [
        lines[i] for i in range(len(lines)) if (i + 1) not in covered_lines
    ]
    if uncovered:
        module_content = "\n".join(uncovered)[:4000]
        chunks.append(Chunk(
            id=_chunk_id(str(filepath), "module"),
            filepath=str(filepath),
            symbol="module",
            kind="module",
            start_line=1,
            end_line=len(lines),
            content=module_content,
            language=lang_name,
        ))

    return chunks
