"""Parse GMAT mission scripts into a concrete syntax tree.

The v0.1 entry point. :func:`parse` loads the vendored, compiled tree-sitter grammar — no C or Node
toolchain, and never GMAT, at runtime (see the design decisions, D2 / D9 / D12) — and returns a thin
:class:`Tree` wrapper over the tree-sitter concrete syntax tree (CST). It exposes byte-exact
re-emission (:attr:`Tree.text` / :meth:`Tree.to_source`, D6) and structured access to syntax errors
(:attr:`Tree.errors` / :attr:`Tree.has_errors`, D7): a malformed script never raises — it yields a
partial tree with ``ERROR`` / ``MISSING`` nodes localised to the broken construct.

The surface here is deliberately minimal and additive: the v0.2 typed-AST overlay wraps this tree
(via :attr:`Tree.root_node`) without a breaking change.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

from tree_sitter import Language, Parser

from ._grammar import language

if TYPE_CHECKING:
    from tree_sitter import Node, Point
    from tree_sitter import Tree as _TSTree

__all__ = ["ErrorNode", "Position", "Tree", "parse"]


@lru_cache(maxsize=1)
def _gmat_language() -> Language:
    """Load and cache the vendored GMAT grammar as a tree-sitter ``Language``.

    The grammar is immutable and the load is pure, so it is cached for the process. Each
    :func:`parse` call still constructs a fresh :class:`~tree_sitter.Parser` (parsers are cheap and
    must not be shared across threads); only the language object is shared.
    """
    return Language(language())


@dataclass(frozen=True, slots=True)
class Position:
    """A 1-indexed line/column position into the source (compiler / human convention).

    tree-sitter's native points are 0-indexed; the wrapper converts (decision D8). ``column`` is a
    1-indexed byte offset within its line.
    """

    line: int
    column: int


@dataclass(frozen=True, slots=True)
class ErrorNode:
    """A syntax error surfaced from the concrete syntax tree.

    One record per ``ERROR`` or ``MISSING`` node: its :class:`Position` range and a short message.
    These are *data*, not exceptions — :func:`parse` never raises on malformed input (D7).
    """

    type: str
    start: Position
    end: Position
    message: str


_ERROR_MESSAGE = "unexpected token"
# Message for a MISSING hidden token (the statement terminator) that the child walk cannot reach.
_MISSING_TERMINATOR_MESSAGE = "missing statement separator"


def _to_position(point: Point) -> Position:
    """Convert a 0-indexed tree-sitter point to a 1-indexed :class:`Position`."""
    return Position(line=point.row + 1, column=point.column + 1)


def _collect_errors(root: Node) -> list[ErrorNode]:
    """Collect every ``ERROR`` / ``MISSING`` node, in source order (D7).

    The walk records one entry per broken construct: an ``ERROR`` node's descendants are the
    partial / unexpected tokens of that same construct, so the walk does not descend into it, and a
    visible ``MISSING`` token (e.g. a ``MISSING ')'``) is recorded directly.

    A ``MISSING`` instance of a *hidden* token — this grammar's statement ``_terminator`` — is the
    one case the child walk cannot see: tree-sitter flags it on ``root.has_error`` but does not
    surface it through the node-child API (``child_count`` omits it; ``.children``, ``child(i)``, a
    ``TreeCursor`` walk, and ``(MISSING)`` queries all skip it in tree-sitter 0.25). Left unhandled,
    such a tree would read as clean and the CLI would exit 0 on input tree-sitter rejects. So when
    the tree is flagged erroneous but the walk localised nothing, descend by ``has_error`` to the
    narrowest accessible subtree still flagged and synthesise one record there — keeping
    :attr:`Tree.errors` consistent with the authoritative :attr:`Tree.has_errors`.
    """
    errors: list[ErrorNode] = []
    stack: list[Node] = [root]
    while stack:
        node = stack.pop()
        if node.is_error or node.is_missing:
            errors.append(
                ErrorNode(
                    type="MISSING" if node.is_missing else "ERROR",
                    start=_to_position(node.start_point),
                    end=_to_position(node.end_point),
                    message=f"missing {node.type!r}" if node.is_missing else _ERROR_MESSAGE,
                )
            )
            continue
        stack.extend(node.children)

    if not errors and root.has_error:
        node = root
        while True:
            flagged = next((child for child in node.children if child.has_error), None)
            if flagged is None:
                break
            node = flagged
        errors.append(
            ErrorNode(
                type="MISSING",
                start=_to_position(node.start_point),
                end=_to_position(node.end_point),
                message=_MISSING_TERMINATOR_MESSAGE,
            )
        )

    errors.sort(key=lambda error: (error.start.line, error.start.column))
    return errors


class Tree:
    """A thin wrapper over the tree-sitter concrete syntax tree of a parsed GMAT script.

    Returned by :func:`parse`. v0.1 exposes only what the parser contract needs: byte-exact
    re-emission (:attr:`text` / :meth:`to_source`), syntax-error access (:attr:`errors` /
    :attr:`has_errors`), and the raw :attr:`root_node` for layers built on top (the v0.2 typed-AST
    overlay, the ``parse`` CLI).
    """

    __slots__ = ("_errors", "_source", "_tree")

    def __init__(self, source: str, tree: _TSTree) -> None:
        self._source = source
        self._tree = tree
        self._errors: list[ErrorNode] | None = None

    @property
    def root_node(self) -> Node:
        """The root :class:`~tree_sitter.Node` of the concrete syntax tree (a ``source_file``)."""
        return self._tree.root_node

    @property
    def text(self) -> str:
        """The script's source text, byte-for-byte identical to the input of :func:`parse` (D6)."""
        return self._source

    def to_source(self) -> str:
        """Re-emit the script source, identical byte-for-byte to the text passed to :func:`parse`.

        Equivalent to :attr:`text`. The CST preserves every leaf token and all interstitial layout
        (whitespace, comments, the ``...`` continuation, the optional ``;``), so concatenating them
        in order reproduces the input exactly; the test suite asserts that reconstruction directly.
        """
        return self._source

    @property
    def errors(self) -> list[ErrorNode]:
        """The ``ERROR`` / ``MISSING`` nodes in source order — empty if it parsed cleanly."""
        errors = self._errors
        if errors is None:
            errors = _collect_errors(self._tree.root_node)
            self._errors = errors
        return errors

    @property
    def has_errors(self) -> bool:
        """Whether the tree contains any ``ERROR`` or ``MISSING`` node.

        Reads tree-sitter's own ``has_error`` flag, which is authoritative: it counts a ``MISSING``
        instance of a hidden token (the statement terminator) that the node-child API does not
        expose, so this never under-reports relative to :attr:`errors` (see
        :func:`_collect_errors`).
        """
        return self._tree.root_node.has_error


def parse(source: str) -> Tree:
    """Parse GMAT script *source* into a concrete syntax tree.

    Loads the vendored grammar (no GMAT, C, or Node toolchain needed) and returns a :class:`Tree`.
    *source* is UTF-8 text; its line endings are preserved exactly — the library performs no EOL
    normalisation (D6). Malformed input never raises: the returned tree carries ``ERROR`` /
    ``MISSING`` nodes localised to the broken construct, surfaced via :attr:`Tree.errors` (D7).

    :param source: the ``.script`` or ``.gmf`` text to parse.
    :returns: a :class:`Tree` wrapping the parsed concrete syntax tree.
    """
    parser = Parser(_gmat_language())
    tree = parser.parse(source.encode("utf-8"))
    return Tree(source, tree)
