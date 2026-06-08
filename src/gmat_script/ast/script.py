"""The :class:`Script` root of the typed AST overlay (issue #12).

:class:`Script` wraps a parsed :class:`~gmat_script.Tree` and presents it as typed resources and an
ordered mission sequence. It is a read-only *view*: it holds nothing but the tree and an index of
node references into it, so it cannot desync from the CST and :meth:`to_source` re-emits
byte-for-byte (D5 / D6). The configuration ↔ sequence split is positional — statements before the
``BeginMissionSequence`` marker configure resources; statements after it are the mission sequence
(D5). A file without the marker is configuration-only (a valid corpus case, D4).
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING

from ..parser import Tree, parse
from .base import node_text
from .commands import Command, build_command
from .resource import Resource, split_reference

if TYPE_CHECKING:
    from tree_sitter import Node

__all__ = ["Script"]

# Top-level node types that are mission-sequence statements (vs. the marker, comments, or stray
# configuration nodes). ``include`` is top-level-only but tolerated here for totality.
_STATEMENT_TYPES = frozenset(
    {
        "command",
        "assignment_command",
        "function_call_command",
        "if_statement",
        "for_statement",
        "while_statement",
        "target_statement",
        "optimize_statement",
        "script_block",
        "include",
    }
)


def _declare(
    node: Node,
    resources: dict[str, Resource],
    by_type: dict[str, dict[str, Resource]],
) -> None:
    """Register every name declared by one ``Create`` command, pairing ``Array`` size suffixes."""
    type_node = node.child_by_field_name("type")
    if type_node is None:  # pragma: no cover - a Create always carries a type
        return
    type_name = node_text(type_node)
    name_ids = {name.id for name in node.children_by_field_name("name")}
    # Walk named children in order so each name picks up a trailing ``array_size`` sibling, if any.
    paired: list[tuple[Node, Node | None]] = []
    for child in node.named_children:
        if child.id in name_ids:
            paired.append((child, None))
        elif child.type == "array_size" and paired:
            name_node, _ = paired[-1]
            paired[-1] = (name_node, child)
    for name_node, size_node in paired:
        name = node_text(name_node)
        resource = Resource(name, type_name, node, size_node)
        resources[name] = resource
        by_type.setdefault(type_name, {})[name] = resource


def _build(
    root: Node,
) -> tuple[
    Mapping[str, Resource],
    Mapping[str, Mapping[str, Resource]],
    tuple[Command, ...],
]:
    """Index a ``source_file`` into resources, a by-type view, and the typed mission sequence."""
    children = list(root.named_children)
    marker = next(
        (i for i, child in enumerate(children) if child.type == "begin_mission_sequence"), None
    )
    config = children if marker is None else children[:marker]
    sequence_nodes = [] if marker is None else children[marker + 1 :]

    resources: dict[str, Resource] = {}
    by_type: dict[str, dict[str, Resource]] = {}
    for node in config:
        if node.type == "create_command":
            _declare(node, resources, by_type)
    for node in config:
        if node.type != "assignment_command":
            continue
        left = node.child_by_field_name("left")
        if left is None:  # pragma: no cover - an assignment always has a left-hand side
            continue
        root_name, _ = split_reference(left)
        resource = resources.get(root_name)
        if resource is not None:
            resource._add_assignment(node)

    sequence = tuple(
        build_command(node) for node in sequence_nodes if node.type in _STATEMENT_TYPES
    )
    by_type_ro: dict[str, Mapping[str, Resource]] = {
        type_name: MappingProxyType(members) for type_name, members in by_type.items()
    }
    return MappingProxyType(resources), MappingProxyType(by_type_ro), sequence


class Script:
    """A typed, read-only overlay over a parsed GMAT script.

    Construct it from a :class:`~gmat_script.Tree` (``Script(tree)``) or parse in one call
    (:meth:`Script.parse`). Resources are reachable by name (:attr:`resources`), by type
    (:attr:`resources_by_type`, or the ``script.<lowercased-type>`` sugar — ``script.spacecraft``),
    and the mission sequence is the ordered :attr:`mission_sequence`. The overlay never mutates and
    never copies values eagerly: field and operand values are coerced on access.
    """

    __slots__ = ("_by_type", "_mission_sequence", "_resources", "_tree")

    def __init__(self, tree: Tree) -> None:
        self._tree = tree
        resources, by_type, sequence = _build(tree.root_node)
        self._resources = resources
        self._by_type = by_type
        self._mission_sequence = sequence

    @classmethod
    def parse(cls, source: str) -> Script:
        """Parse *source* and overlay the typed model — ``Script(parse(source))`` in one call."""
        return cls(parse(source))

    @property
    def tree(self) -> Tree:
        """The underlying :class:`~gmat_script.Tree` (the CST source of truth)."""
        return self._tree

    @property
    def resources(self) -> Mapping[str, Resource]:
        """All configured resources, keyed by name."""
        return self._resources

    @property
    def resources_by_type(self) -> Mapping[str, Mapping[str, Resource]]:
        """Resources grouped by GMAT type, e.g. ``resources_by_type["Spacecraft"]["Sat"]``."""
        return self._by_type

    @property
    def mission_sequence(self) -> tuple[Command, ...]:
        """The ordered mission-sequence commands (empty for a configuration-only script)."""
        return self._mission_sequence

    @property
    def byte_range(self) -> tuple[int, int]:
        """The script's ``(start_byte, end_byte)`` span (provenance)."""
        root = self._tree.root_node
        return (root.start_byte, root.end_byte)

    @property
    def has_errors(self) -> bool:
        """Whether the underlying parse carried any syntax error (delegates to the tree)."""
        return self._tree.has_errors

    def to_source(self) -> str:
        """Re-emit the script source, byte-for-byte identical to the parsed input (D6)."""
        return self._tree.to_source()

    def __getattr__(self, name: str) -> Mapping[str, Resource]:
        """Sugar: ``script.<lowercased-type>`` is the by-type view for that GMAT type.

        ``script.spacecraft`` ≡ ``script.resources_by_type["Spacecraft"]``. Only types present in
        this script resolve; anything else (and any private / dunder name) raises ``AttributeError``
        so typos surface rather than returning an empty mapping.
        """
        if name.startswith("_"):
            raise AttributeError(name)
        for type_name, members in self._by_type.items():
            if type_name.lower() == name:
                return members
        known = sorted(type_name.lower() for type_name in self._by_type)
        raise AttributeError(
            f"{type(self).__name__!r} object has no resource type {name!r} (known: {known})"
        )

    def __repr__(self) -> str:
        return (
            f"Script(resources={len(self._resources)}, "
            f"mission_sequence={len(self._mission_sequence)})"
        )
