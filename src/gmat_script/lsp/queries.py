"""Running the grammar's tree-sitter queries for the language server's navigation features.

Two of the vendored ``.scm`` queries (decisions D1 / #21) run over a parsed tree: ``locals.scm``
captures resource / function / loop-variable *definitions* and every identifier *reference* (go-to-
definition and find-references), and ``tags.scm`` captures the declared-symbol *tags* the document
outline is built from. The queries are vendored into the package at build time (``hatch_build.py``)
and loaded through :mod:`importlib.resources`, so they load the same from a wheel or an editable
install — no GMAT, and no grammar source tree, at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import TYPE_CHECKING

from tree_sitter import Query, QueryCursor

from ..ast.base import node_text
from ..parser import _gmat_language

if TYPE_CHECKING:
    from tree_sitter import Node

# Anchor the query files at the grammar package; they are vendored under its ``queries/`` directory.
_QUERY_ANCHOR = "gmat_script._grammar"
_QUERY_DIR = "queries"


@cache
def _load_query(name: str) -> Query:
    """Compile and cache the vendored query *name* (e.g. ``"locals.scm"``)."""
    source = (resources.files(_QUERY_ANCHOR) / _QUERY_DIR / name).read_text(encoding="utf-8")
    return Query(_gmat_language(), source)


def _captures(query_name: str, root: Node) -> dict[str, list[Node]]:
    """Run *query_name* over *root*; return its capture-name → matched-nodes mapping."""
    return QueryCursor(_load_query(query_name)).captures(root)


def definition_nodes(root: Node) -> list[Node]:
    """The ``@local.definition`` name nodes — resource, function, parameter, and loop-variable
    declarations (``locals.scm``)."""
    return _captures("locals.scm", root).get("local.definition", [])


def reference_nodes(root: Node) -> list[Node]:
    """The ``@local.reference`` name nodes — every identifier use (``locals.scm``).

    The query captures *every* identifier, so a declaration's own name node appears here too; the
    caller filters against :func:`definition_nodes` when a use-only set is wanted.
    """
    return _captures("locals.scm", root).get("local.reference", [])


@dataclass(frozen=True, slots=True)
class SymbolTag:
    """One declared-symbol tag from ``tags.scm``: its kind, name, and the spans for each."""

    kind: str  # "class" (a Create'd resource) or "function" (a GmatFunction header)
    name: str
    name_node: Node
    definition_node: Node


def symbol_tags(root: Node) -> list[SymbolTag]:
    """The declared-symbol tags (``@definition.class`` / ``@definition.function``) in source order.

    The ``@reference.call`` tags (command and call sites) are not part of the outline, so matches
    that carry only a reference capture are skipped.
    """
    cursor = QueryCursor(_load_query("tags.scm"))
    tags: list[SymbolTag] = []
    for _, capture in cursor.matches(root):
        names = capture.get("name")
        if not names:  # pragma: no cover - every tags.scm pattern captures a @name
            continue
        for capture_name in ("definition.class", "definition.function"):
            definitions = capture.get(capture_name)
            if definitions:
                tags.append(
                    SymbolTag(
                        kind=capture_name.split(".", 1)[1],
                        name=node_text(names[0]),
                        name_node=names[0],
                        definition_node=definitions[0],
                    )
                )
    tags.sort(key=lambda tag: tag.definition_node.start_byte)
    return tags
