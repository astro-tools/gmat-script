"""Typed resource nodes with dict-like, mutable field access.

A :class:`Resource` is one ``Create``'d GMAT object viewed as a mapping from field name to its
configured value. ``resource["SMA"]`` reads the value assigned in the configuration section
(``Sat.SMA = …``), coerced structurally (:mod:`gmat_script.ast.values`); ``resource["SMA"] = 7000``
and ``del resource["SMA"]`` edit it, re-emitting only the touched span. The split between the
configuration section and the mission sequence is positional and owned by :class:`~.script.Script`
(D5); a resource only ever sees configuration-section assignments.

A :class:`Resource` is a *live cursor*, not a snapshot: it holds only its owning :class:`Script` and
its name, and resolves its declaration and fields from the script's current tree on every access. So
a handle kept across an edit reflects the edit — and if the resource is removed or renamed out from
under it, the next access raises :class:`KeyError` rather than reading stale data.
"""

from __future__ import annotations

from collections.abc import Iterator, MutableMapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .base import node_text
from .values import Value, coerce_value

if TYPE_CHECKING:
    from tree_sitter import Node

    from .script import Script


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
        if obj is not None and prop is not None:  # pragma: no cover - a member_expression has both
            root, segments = split_reference(obj)
            return root, [*segments, node_text(prop)]
    if node.type == "call_expression":
        function = node.child_by_field_name("function")
        if function is not None:  # pragma: no cover - a call_expression always has a function
            return split_reference(function)
    return node_text(node), []


@dataclass(slots=True)
class _ResourceData:
    """The raw CST nodes backing one resource, rebuilt by :class:`Script` after every edit.

    Holds the ``Create`` declaration node, the GMAT type, the optional ``Array`` size suffix, and
    the configuration assignments rooted at this resource — the source of truth a live
    :class:`Resource` reads through. Field resolution is cached here (not on the cursor), so it dies
    with the tree.
    """

    name: str
    type: str
    declaration: Node
    array_size: Node | None
    assignments: list[Node] = field(default_factory=list)
    _field_cache: dict[str, Node] | None = field(default=None, repr=False)

    def fields(self) -> dict[str, Node]:
        """Field name → its (last-winning) value node, resolved lazily from the assignments."""
        if self._field_cache is None:
            fields: dict[str, Node] = {}
            for assignment in self.assignments:
                left = assignment.child_by_field_name("left")
                right = assignment.child_by_field_name("right")
                if left is None or right is None or left.type != "member_expression":
                    continue  # bare-name / array-index targets are not fields
                _, segments = split_reference(left)
                if segments:  # pragma: no cover - a member_expression yields >=1 segment
                    fields[".".join(segments)] = right  # last write wins (source order)
            self._field_cache = fields
        return self._field_cache


class Resource(MutableMapping[str, Value]):
    """A configured GMAT resource — one ``Create``'d object — with dict-like, mutable field access.

    ``resource["SMA"]`` reads the value assigned to that field in the configuration section, coerced
    structurally; the last assignment to a field wins (GMAT applies them in order). Assigning
    (``resource["SMA"] = 7000``) rewrites that field's value in place — or appends a canonical
    assignment if the field is new — and deleting (``del resource["SMA"]``) removes every assignment
    to it. Being a :class:`~collections.abc.MutableMapping`, it also supports ``update``, ``pop``,
    ``setdefault``, and ``clear`` for free, all routed through those two edits.

    The mapping spans dotted field assignments (``Sat.SMA = …``); whole-object assignments
    (``x = 5``) and array-element writes (``A(1, 1) = …``) reach the resource via
    :attr:`assignments` but are not fields. Iterating the resource yields its field names.

    The wrapped node (:attr:`node` / :attr:`declaration`) is the ``Create`` command; for a
    multi-name declaration (``Create Variable x y z``) every name is its own :class:`Resource`
    sharing that declaration.
    """

    __slots__ = ("_name", "_script")

    def __init__(self, script: Script, name: str) -> None:
        self._script = script
        self._name = name

    @property
    def _data(self) -> _ResourceData:
        """The current backing data for this name — raises ``KeyError`` if the resource is gone."""
        return self._script._resource_data(self._name)

    # -- declaration metadata -------------------------------------------------------------------

    @property
    def name(self) -> str:
        """The resource's declared name (its key in :attr:`Script.resources`)."""
        return self._name

    @property
    def type(self) -> str:
        """The resource's GMAT type, verbatim from ``Create <type> …`` (e.g. ``Spacecraft``)."""
        return self._data.type

    @property
    def node(self) -> Node:
        """The ``Create`` command node that declares this resource (the CST source of truth)."""
        return self._data.declaration

    @property
    def declaration(self) -> Node:
        """The ``Create`` command node that declares this resource (same as :attr:`node`)."""
        return self._data.declaration

    @property
    def byte_range(self) -> tuple[int, int]:
        """The declaration's ``(start_byte, end_byte)`` span into the source (provenance)."""
        declaration = self._data.declaration
        return (declaration.start_byte, declaration.end_byte)

    def to_source(self) -> str:
        """Re-emit the ``Create`` declaration's source slice, byte-for-byte (D6)."""
        return node_text(self._data.declaration)

    @property
    def array_dimensions(self) -> tuple[int, ...] | None:
        """The ``Array`` size suffix as integers — ``Create Array A[3, 3]`` → ``(3, 3)``; else
        ``None``. Generic: only ``Array`` uses the suffix, but the parser accepts it on any name."""
        array_size = self._data.array_size
        if array_size is None:
            return None
        return tuple(
            int(node_text(child)) for child in array_size.named_children if child.type == "number"
        )

    @property
    def assignments(self) -> tuple[Node, ...]:
        """Every configuration assignment whose target is rooted at this resource, in source order
        — including the bare-name and array-element writes that :class:`Resource` does not expose as
        fields. Raw CST nodes."""
        return tuple(self._data.assignments)

    # -- MutableMapping interface ---------------------------------------------------------------

    def __getitem__(self, field: str) -> Value:
        node = self._data.fields().get(field)
        if node is None:
            raise KeyError(field)
        return coerce_value(node)

    def __setitem__(self, field: str, value: Value) -> None:
        self._script.set_field(self._name, field, value)

    def __delitem__(self, field: str) -> None:
        self._script.delete_field(self._name, field)

    def __iter__(self) -> Iterator[str]:
        return iter(self._data.fields())

    def __len__(self) -> int:
        return len(self._data.fields())

    def __repr__(self) -> str:
        return f"Resource({self._name!r}, type={self.type!r}, fields={len(self)})"
