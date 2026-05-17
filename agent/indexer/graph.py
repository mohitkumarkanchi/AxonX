"""
Build a call graph and import tree from tree-sitter parse results.

Produces directed edges suitable for the SQLite graph store:
  (source_symbol, source_file) -[CALLS|IMPORTS|INHERITS]-> (target_symbol, target_file)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

try:
    from tree_sitter_languages import get_parser
    _HAS_TSL = True
except ImportError:
    _HAS_TSL = False

from .parser import EXTENSION_TO_LANG


@dataclass
class GraphEdge:
    source_file: str
    source_symbol: str
    relation: str     # "CALLS" | "IMPORTS" | "INHERITS" | "IMPLEMENTS"
    target_symbol: str
    target_file: str  # "" if not resolved


def extract_edges(filepath: str | Path) -> list[GraphEdge]:
    """Extract all graph edges from a source file."""
    filepath = Path(filepath)
    suffix = filepath.suffix.lower()
    lang_name = EXTENSION_TO_LANG.get(suffix)

    if not lang_name or not _HAS_TSL:
        return []

    try:
        source = filepath.read_bytes()
    except OSError:
        return []

    try:
        parser = get_parser(lang_name)
    except Exception:
        return []

    tree = parser.parse(source)
    edges: list[GraphEdge] = []

    if lang_name == "python":
        _extract_python_edges(tree.root_node, source, str(filepath), edges)
    elif lang_name in ("javascript", "typescript", "tsx"):
        _extract_js_edges(tree.root_node, source, str(filepath), edges)
    elif lang_name == "go":
        _extract_go_edges(tree.root_node, source, str(filepath), edges)
    else:
        _extract_generic_calls(tree.root_node, source, str(filepath), lang_name, edges)

    return edges


def _text(node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _find_nodes(node, node_types: set[str]) -> list:
    results = []
    if node.type in node_types:
        results.append(node)
    for child in node.children:
        results.extend(_find_nodes(child, node_types))
    return results


# ------------------------------------------------------------------
# Python-specific edge extraction
# ------------------------------------------------------------------

def _extract_python_edges(root, source: bytes, filepath: str, edges: list[GraphEdge]) -> None:
    # Import edges
    for node in _find_nodes(root, {"import_statement", "import_from_statement"}):
        module = ""
        for child in node.children:
            if child.type in ("dotted_name", "relative_import"):
                module = _text(child, source)
                break
        if module:
            edges.append(GraphEdge(
                source_file=filepath,
                source_symbol="module",
                relation="IMPORTS",
                target_symbol=module,
                target_file="",
            ))

    # Class inheritance edges
    for node in _find_nodes(root, {"class_definition"}):
        class_name = ""
        for child in node.children:
            if child.type == "identifier":
                class_name = _text(child, source)
                break
        # argument_list contains base classes
        for arg_list in _find_nodes(node, {"argument_list"}):
            for arg in arg_list.children:
                if arg.type in ("identifier", "attribute"):
                    edges.append(GraphEdge(
                        source_file=filepath,
                        source_symbol=class_name,
                        relation="INHERITS",
                        target_symbol=_text(arg, source),
                        target_file="",
                    ))

    # Function call edges — simple identifier calls
    for fn_node in _find_nodes(root, {"function_definition", "async_function_definition"}):
        fn_name = ""
        for child in fn_node.children:
            if child.type == "identifier":
                fn_name = _text(child, source)
                break
        for call in _find_nodes(fn_node, {"call"}):
            func = call.child_by_field_name("function")
            if func and func.type in ("identifier", "attribute"):
                callee = _text(func, source)
                if callee != fn_name:
                    edges.append(GraphEdge(
                        source_file=filepath,
                        source_symbol=fn_name,
                        relation="CALLS",
                        target_symbol=callee,
                        target_file="",
                    ))


# ------------------------------------------------------------------
# JavaScript/TypeScript edge extraction
# ------------------------------------------------------------------

def _extract_js_edges(root, source: bytes, filepath: str, edges: list[GraphEdge]) -> None:
    # Import declarations
    for node in _find_nodes(root, {"import_declaration", "import_statement"}):
        source_str = node.child_by_field_name("source")
        if source_str:
            module = _text(source_str, source).strip("'\"")
            edges.append(GraphEdge(
                source_file=filepath,
                source_symbol="module",
                relation="IMPORTS",
                target_symbol=module,
                target_file="",
            ))

    # Class inheritance
    for node in _find_nodes(root, {"class_declaration", "class"}):
        class_name = ""
        for child in node.children:
            if child.type == "identifier":
                class_name = _text(child, source)
                break
        heritage = node.child_by_field_name("class_heritage")
        if heritage:
            for id_node in _find_nodes(heritage, {"identifier"}):
                edges.append(GraphEdge(
                    source_file=filepath,
                    source_symbol=class_name,
                    relation="INHERITS",
                    target_symbol=_text(id_node, source),
                    target_file="",
                ))

    # Call expressions
    for call in _find_nodes(root, {"call_expression"}):
        func = call.child_by_field_name("function")
        if func and func.type in ("identifier", "member_expression"):
            edges.append(GraphEdge(
                source_file=filepath,
                source_symbol="module",
                relation="CALLS",
                target_symbol=_text(func, source),
                target_file="",
            ))


# ------------------------------------------------------------------
# Go edge extraction
# ------------------------------------------------------------------

def _extract_go_edges(root, source: bytes, filepath: str, edges: list[GraphEdge]) -> None:
    for node in _find_nodes(root, {"import_declaration", "import_spec"}):
        for path_node in _find_nodes(node, {"interpreted_string_literal"}):
            module = _text(path_node, source).strip('"')
            edges.append(GraphEdge(
                source_file=filepath,
                source_symbol="module",
                relation="IMPORTS",
                target_symbol=module,
                target_file="",
            ))

    for fn_node in _find_nodes(root, {"function_declaration", "method_declaration"}):
        fn_name = ""
        name_node = fn_node.child_by_field_name("name")
        if name_node:
            fn_name = _text(name_node, source)
        for call in _find_nodes(fn_node, {"call_expression"}):
            func = call.child_by_field_name("function")
            if func:
                edges.append(GraphEdge(
                    source_file=filepath,
                    source_symbol=fn_name or "module",
                    relation="CALLS",
                    target_symbol=_text(func, source),
                    target_file="",
                ))


# ------------------------------------------------------------------
# Generic fallback — just extract call_expression nodes
# ------------------------------------------------------------------

def _extract_generic_calls(root, source: bytes, filepath: str, lang: str, edges: list[GraphEdge]) -> None:
    for call in _find_nodes(root, {"call_expression", "function_call", "method_call"}):
        func_text = _text(call, source)[:80]
        edges.append(GraphEdge(
            source_file=filepath,
            source_symbol="module",
            relation="CALLS",
            target_symbol=func_text,
            target_file="",
        ))
