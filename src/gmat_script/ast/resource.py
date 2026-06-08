"""Typed resource nodes with dict-like field access (issue #12).

A :class:`Resource` is one ``Create``'d GMAT object viewed as a mapping from field name to its
configured value. ``resource["SMA"]`` reads the value assigned in the configuration section
(``Sat.SMA = …``), coerced structurally (:mod:`gmat_script.ast.values`). The split between the
configuration section and the mission sequence is positional and owned by :class:`~.script.Script`
(D5); a resource only ever sees configuration-section assignments.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING

from .base import AstNode, node_text
from .values import Value, coerce_value

if TYPE_CHECKING:
    from tree_sitter import Node


def split_reference(node: Node) -> tuple[str, list[str]]:
    """Split a reference into its root object name and its dotted field-path segments.

    ``Sat`` → ``("Sat", [])``; ``Sat.SMA`` → ``("Sat", ["SMA"])``;
    ``FM.GravityField.Earth.PotentialFile`` →
    ``("FM", ["GravityField", "Earth", "PotentialFile"])``. An array-indexed target (a
    ``call_expression`` like ``A(1, 1)``) returns its root name with no segments, so it attaches to
    the resource but is not a field.
    """
    if node.type == "member_expression":
        obj = node.child_by_field_name("object")
        prop = node.child_by_field_name("property")
        if obj is not None and prop is not None:
            root, segments = split_reference(obj)
            return root, [*segments, node_text(prop)]
    if node.type == "call_expression":
        function = node.child_by_field_name("function")
        if function is not None:
            return split_reference(function)
    return node_text(node), []


class Resource(AstNode, Mapping[str, Value]):
    """A configured GMAT resource — one ``Create``'d object — with dict-like field access.

    ``resource["SMA"]`` reads the value assigned to that field in the configuration section, coerced
    structurally; the last assignment to a field wins (GMAT applies them in order). The mapping
    spans dotted field assignments (``Sat.SMA = …``); whole-object assignments (``x = 5``) and
    array-element writes (``A(1, 1) = …``) reach the resource via :attr:`assignments` but are not
    fields. Iterating the resource yields its field names.

    The wrapped node (:attr:`node` / :attr:`declaration`) is the ``Create`` command; for a
    multi-name declaration (``Create Variable x y z``) every name is its own :class:`Resource`
    sharing that declaration.
    """

    __slots__ = ("_array_size", "_assignments", "_field_cache", "_name", "_type")

    def __init__(self, name: str, type_: str, declaration: Node, array_size: Node | None) -> None:
        super().__init__(declaration)
        self._name = name
        self._type = type_
        self._array_size = array_size
        self._assignments: list[Node] = []
        self._field_cache: dict[str, Node] | None = None

    # -- declaration metadata -------------------------------------------------------------------

    @property
    def name(self) -> str:
        """The resource's declared name (its key in :attr:`Script.resources`)."""
        return self._name

    @property
    def type(self) -> str:
        """The resource's GMAT type, verbatim from ``Create <type> …`` (e.g. ``Spacecraft``)."""
        return self._type

    @property
    def declaration(self) -> Node:
        """The ``Create`` command node that declares this resource (same as :attr:`node`)."""
        return self._node

    @property
    def array_dimensions(self) -> tuple[int, ...] | None:
        """The ``Array`` size suffix as integers — ``Create Array A[3, 3]`` → ``(3, 3)``; else
        ``None``. Generic: only ``Array`` uses the suffix, but the parser accepts it on any name."""
        if self._array_size is None:
            return None
        return tuple(
            int(node_text(child))
            for child in self._array_size.named_children
            if child.type == "number"
        )

    @property
    def assignments(self) -> tuple[Node, ...]:
        """Every configuration assignment whose target is rooted at this resource, in source order
        — including the bare-name and array-element writes that :class:`Resource` does not expose as
        fields. Raw CST nodes, for the mutation layer (#13) to consume."""
        return tuple(self._assignments)

    # -- internal: wiring from Script -----------------------------------------------------------

    def _add_assignment(self, assignment: Node) -> None:
        """Record a configuration ``assignment_command`` targeting this resource (Script use)."""
        self._assignments.append(assignment)
        self._field_cache = None

    @property
    def _fields(self) -> dict[str, Node]:
        """Field name → its (last-winning) value node, resolved lazily from the assignments."""
        if self._field_cache is None:
            fields: dict[str, Node] = {}
            for assignment in self._assignments:
                left = assignment.child_by_field_name("left")
                right = assignment.child_by_field_name("right")
                if left is None or right is None or left.type != "member_expression":
                    continue  # bare-name / array-index targets are not fields
                _, segments = split_reference(left)
                if segments:
                    fields[".".join(segments)] = right  # last write wins (source order)
            self._field_cache = fields
        return self._field_cache

    # -- Mapping interface ----------------------------------------------------------------------

    def __getitem__(self, field: str) -> Value:
        node = self._fields.get(field)
        if node is None:
            raise KeyError(field)
        return coerce_value(node)

    def __iter__(self) -> Iterator[str]:
        return iter(self._fields)

    def __len__(self) -> int:
        return len(self._fields)

    def __repr__(self) -> str:
        return f"Resource({self._name!r}, type={self._type!r}, fields={len(self._fields)})"
