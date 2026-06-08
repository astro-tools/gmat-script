"""Shared base for the typed AST overlay — a read-only view over one CST node.

Every typed node (resource, command) wraps exactly one tree-sitter :class:`~tree_sitter.Node` and
holds no other state, so the overlay can never desync from the concrete syntax tree (D5): structured
access is recomputed from the node, and source provenance is the node's own byte range.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tree_sitter import Node

# The grammar field names a control-flow / solver block node carries in its header; everything else
# between the header and the matched end keyword is its nested body. Shared by the AST overlay (to
# find a block's body, :mod:`gmat_script.ast.commands`) and the formatter (to find its header,
# :mod:`gmat_script.format`) so a grammar change to a block header is made in one place.
BLOCK_HEADER_FIELDS = ("label", "condition", "variable", "range", "solver", "options")


def node_text(node: Node) -> str:
    """The exact source slice of *node*, decoded as UTF-8 (byte-for-byte; D6).

    tree-sitter types ``Node.text`` as ``bytes | None``; the ``None`` case (a node detached from its
    source) cannot arise for a node reached from a live parse tree, but is handled for totality.
    """
    text = node.text
    return text.decode("utf-8") if text is not None else ""


class AstNode:
    """Base for a typed overlay node: a thin, read-only view over one CST node.

    Subclasses add structured, computed access to the node's operands. The node itself is the single
    source of truth — nothing here caches a parallel copy that could drift from it.
    """

    __slots__ = ("_node",)

    def __init__(self, node: Node) -> None:
        self._node = node

    @property
    def node(self) -> Node:
        """The wrapped tree-sitter :class:`~tree_sitter.Node` — the CST source of truth."""
        return self._node

    @property
    def byte_range(self) -> tuple[int, int]:
        """This node's ``(start_byte, end_byte)`` span into the source (provenance)."""
        return (self._node.start_byte, self._node.end_byte)

    def to_source(self) -> str:
        """Re-emit this node's source slice, byte-for-byte (D6)."""
        return node_text(self._node)
