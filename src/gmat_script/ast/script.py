"""The :class:`Script` root of the typed AST overlay — a mutable document over a parsed script.

:class:`Script` wraps a parsed :class:`~gmat_script.Tree` and presents it as typed resources and an
ordered mission sequence. Reading is a lossless *view*: :meth:`to_source` re-emits byte-for-byte
(D5 / D6) and the configuration ↔ sequence split is positional — statements before the
``BeginMissionSequence`` marker configure resources; statements after it are the mission sequence
(D5). A file without the marker is configuration-only (a valid corpus case, D4).

Editing keeps that lossless guarantee for every *untouched* byte. :class:`Script` owns the source
buffer; each mutation — a field set/delete through a :class:`Resource`, or a resource / command
method here — computes byte-range edits over the current tree, splices them in, and re-parses
(:mod:`gmat_script.ast.edit`). Only the touched spans change; the edited span is re-emitted in
canonical form for its construct. An edit that would make the script unparseable raises
:class:`~gmat_script.ast.edit.MutationError` and leaves the source unchanged, so a mutated script
always re-parses with zero ``ERROR`` nodes.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING

from ..parser import Tree, parse
from .base import node_text
from .commands import Command, build_command
from .edit import (
    MutationError,
    _Edit,
    collect_reference_edits,
    declaration_name_edits,
    detect_newline,
    line_span,
    splice,
)
from .literals import emit_value
from .resource import Resource, _ResourceData, split_reference

if TYPE_CHECKING:
    from tree_sitter import Node

    from .values import Value

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
    resources: dict[str, _ResourceData],
    by_type: dict[str, list[str]],
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
        resources[name] = _ResourceData(name, type_name, node, size_node)
        members = by_type.setdefault(type_name, [])
        if name not in members:
            members.append(name)


def _index(
    root: Node,
) -> tuple[dict[str, _ResourceData], dict[str, list[str]], list[Node], Node | None]:
    """Index a ``source_file`` into resource data, a by-type name index, the mission-sequence
    statement nodes, and the ``BeginMissionSequence`` marker node (``None`` if there is none)."""
    children = list(root.named_children)
    marker = next(
        (i for i, child in enumerate(children) if child.type == "begin_mission_sequence"), None
    )
    config = children if marker is None else children[:marker]
    sequence_nodes = [] if marker is None else children[marker + 1 :]

    resources: dict[str, _ResourceData] = {}
    by_type: dict[str, list[str]] = {}
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
        data = resources.get(root_name)
        if data is not None:
            data.assignments.append(node)

    sequence = [node for node in sequence_nodes if node.type in _STATEMENT_TYPES]
    marker_node = None if marker is None else children[marker]
    return resources, by_type, sequence, marker_node


class Script:
    """A typed, mutable overlay over a parsed GMAT script.

    Construct it from a :class:`~gmat_script.Tree` (``Script(tree)``) or parse in one call
    (:meth:`Script.parse`). Resources are reachable by name (:attr:`resources`), by type
    (:attr:`resources_by_type`, or the ``script.<lowercased-type>`` sugar — ``script.spacecraft``),
    and the mission sequence is the ordered :attr:`mission_sequence`. Field and operand values are
    coerced on access; nothing is copied eagerly.

    It is also the mutation root. Field edits go through a :class:`Resource`
    (``script.spacecraft["Sat"]["SMA"] = 7000``); resource and command edits are the methods here
    (:meth:`add_resource`, :meth:`rename_resource`, :meth:`insert_command`, …). Every mutator
    re-parses and returns ``self`` for chaining; reads after an edit reflect it.
    """

    __slots__ = (
        "_by_type",
        "_marker",
        "_mission_sequence",
        "_newline",
        "_resource_index",
        "_resources",
        "_text",
        "_tree",
    )

    def __init__(self, tree: Tree) -> None:
        self._tree = tree
        self._text = tree.text
        self._newline = detect_newline(self._text)
        self._rebuild()

    @classmethod
    def parse(cls, source: str) -> Script:
        """Parse *source* and overlay the typed model — ``Script(parse(source))`` in one call."""
        return cls(parse(source))

    def _rebuild(self) -> None:
        """Re-index the current tree and rebuild the resource views (run after every edit)."""
        resources, by_type, sequence, marker = _index(self._tree.root_node)
        self._resource_index = resources
        self._marker = marker
        views = {name: Resource(self, name) for name in resources}
        self._resources: Mapping[str, Resource] = MappingProxyType(views)
        self._by_type: Mapping[str, Mapping[str, Resource]] = MappingProxyType(
            {
                type_name: MappingProxyType({name: views[name] for name in names})
                for type_name, names in by_type.items()
            }
        )
        self._mission_sequence = tuple(build_command(node) for node in sequence)

    # -- read surface ---------------------------------------------------------------------------

    @property
    def tree(self) -> Tree:
        """The underlying :class:`~gmat_script.Tree` (the CST, current after edits)."""
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
        """The ordered mission-sequence commands (empty for a configuration-only script).

        The returned commands are a snapshot of the current tree; re-read this attribute after a
        command edit rather than reusing handles from before it."""
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
        """Re-emit the script source — byte-for-byte to the input until the first edit, and exact on
        every untouched byte after one (D6)."""
        return self._text

    def _resource_data(self, name: str) -> _ResourceData:
        """The backing data for *name* (used by :class:`Resource`) — ``KeyError`` if it is gone."""
        data = self._resource_index.get(name)
        if data is None:
            raise KeyError(name)
        return data

    # -- mutation: the edit engine --------------------------------------------------------------

    def _apply(self, edits: list[_Edit]) -> None:
        """Splice *edits*, re-parse, and commit — or raise and leave the source untouched.

        Refuses to edit a script that already has syntax errors, and rejects any edit whose result
        would not parse cleanly, so a committed mutation always re-parses with zero ``ERROR`` nodes.
        """
        if not edits:
            return
        if self._tree.has_errors:
            raise MutationError("cannot edit a script that has syntax errors")
        new_text = splice(self._text.encode("utf-8"), edits).decode("utf-8")
        new_tree = parse(new_text)
        if new_tree.has_errors:
            raise MutationError("the edit would produce an unparseable script")
        self._text = new_text
        self._tree = new_tree
        self._rebuild()

    def _insert_line(self, offset: int, line_text: str) -> _Edit:
        """A zero-width edit inserting *line_text* as its own line at byte *offset*, with the file's
        newline before (only if needed) and after, so it never fuses onto a neighbouring line."""
        source = self._text.encode("utf-8")
        newline = self._newline.encode("utf-8")
        leading = b"" if offset == 0 or source[offset - 1 : offset] == b"\n" else newline
        return _Edit(offset, offset, leading + line_text.encode("utf-8") + newline)

    @staticmethod
    def _line_removal(source: bytes, node: Node) -> _Edit:
        """An edit that excises the whole physical line(s) of *node*."""
        start, end = line_span(source, node.start_byte, node.end_byte)
        return _Edit(start, end, b"")

    # -- mutation: fields -----------------------------------------------------------------------

    def set_field(self, resource: str, field: str, value: Value) -> Script:
        """Set ``<resource>.<field>`` to *value*, formatting the literal value-type-aware.

        Rewrites the field's value in place when it is already assigned (the last-winning
        assignment), else appends a canonical ``<resource>.<field> = <value>`` line next to the
        resource's configuration. This backs ``script.spacecraft["Sat"]["SMA"] = 7000``.
        """
        data = self._resource_data(resource)
        literal = emit_value(value)
        existing = data.fields().get(field)
        if existing is not None:
            edit = _Edit(existing.start_byte, existing.end_byte, literal.encode("utf-8"))
        else:
            anchor = data.assignments[-1] if data.assignments else data.declaration
            source = self._text.encode("utf-8")
            offset = line_span(source, anchor.start_byte, anchor.end_byte)[1]
            edit = self._insert_line(offset, f"{resource}.{field} = {literal}")
        self._apply([edit])
        return self

    def delete_field(self, resource: str, field: str) -> Script:
        """Delete every assignment of ``<resource>.<field>``; raise ``KeyError`` if it has none."""
        data = self._resource_data(resource)
        source = self._text.encode("utf-8")
        targets = [
            assignment for assignment in data.assignments if _assignment_field(assignment) == field
        ]
        if not targets:
            raise KeyError(field)
        self._apply([self._line_removal(source, assignment) for assignment in targets])
        return self

    # -- mutation: resources --------------------------------------------------------------------

    def add_resource(
        self, resource_type: str, name: str, fields: Mapping[str, Value] | None = None
    ) -> Script:
        """Append ``Create <resource_type> <name>`` (plus any *fields*) to the configuration.

        The declaration lands just before ``BeginMissionSequence`` (or at end of file when the
        script has no marker). Raises :class:`~gmat_script.ast.edit.MutationError` if *name* exists.
        """
        if name in self._resource_index:
            raise MutationError(f"resource {name!r} already exists")
        lines = [f"Create {resource_type} {name}"]
        lines.extend(
            f"{name}.{field} = {emit_value(value)}" for field, value in (fields or {}).items()
        )
        source = self._text.encode("utf-8")
        if self._marker is not None:
            offset = line_span(source, self._marker.start_byte, self._marker.end_byte)[0]
        else:
            offset = len(source)
        self._apply([self._insert_line(offset, self._newline.join(lines))])
        return self

    def remove_resource(self, name: str) -> Script:
        """Remove resource *name*: drop its ``Create`` (or just its name from a multi-name one) and
        every configuration assignment rooted at it. References elsewhere are left as-is — use
        :meth:`rename_resource` to rewrite them."""
        data = self._resource_data(name)
        source = self._text.encode("utf-8")
        name_nodes = data.declaration.children_by_field_name("name")
        if len(name_nodes) <= 1:
            edits = [self._line_removal(source, data.declaration)]
        else:
            edits = [_drop_name_edit(name_nodes, name)]
        edits.extend(self._line_removal(source, assignment) for assignment in data.assignments)
        self._apply(edits)
        return self

    def rename_resource(self, old: str, new: str, *, update_references: bool = True) -> Script:
        """Rename resource *old* to *new*, rewriting references unless *update_references* is false.

        With references on (the default), every dotted reference root, array-index / call head, bare
        operand, and the declaration name is rewritten — best-effort over the textual reference
        forms (the scope is :func:`~gmat_script.ast.edit.collect_reference_edits`'s). With it off,
        only the declaration name changes. Raises :class:`~gmat_script.ast.edit.MutationError` on a
        name clash.
        """
        data = self._resource_data(old)
        if new != old and new in self._resource_index:
            raise MutationError(f"resource {new!r} already exists")
        if update_references:
            edits = collect_reference_edits(self._tree.root_node, old, new)
        else:
            edits = declaration_name_edits(data.declaration, old, new)
        self._apply(edits)
        return self

    # -- mutation: commands ---------------------------------------------------------------------

    def insert_command(self, index: int, text: str) -> Script:
        """Insert *text* as a new mission-sequence command before position *index* (or at the end).

        *text* is raw command source, inserted as its own line(s). Requires a mission sequence to
        insert into (a ``BeginMissionSequence`` marker) when the sequence is empty."""
        sequence = self._mission_sequence
        if not 0 <= index <= len(sequence):
            raise IndexError(index)
        source = self._text.encode("utf-8")
        if not sequence:
            if self._marker is None:
                raise MutationError("the script has no mission sequence to insert into")
            offset = line_span(source, self._marker.start_byte, self._marker.end_byte)[1]
        elif index < len(sequence):
            node = sequence[index].node
            offset = line_span(source, node.start_byte, node.end_byte)[0]
        else:
            node = sequence[-1].node
            offset = line_span(source, node.start_byte, node.end_byte)[1]
        self._apply([self._insert_line(offset, text.rstrip("\r\n"))])
        return self

    def remove_command(self, index: int) -> Script:
        """Remove the mission-sequence command at *index* (a whole block, if it is one)."""
        sequence = self._mission_sequence
        if not 0 <= index < len(sequence):
            raise IndexError(index)
        source = self._text.encode("utf-8")
        self._apply([self._line_removal(source, sequence[index].node)])
        return self

    def replace_command(self, index: int, text: str) -> Script:
        """Replace the command at *index* with *text* (its operands, re-emitted), in place.

        Rewrites only the command node's own span, so leading indentation and the trailing newline
        are preserved; pass *text* without a trailing newline."""
        sequence = self._mission_sequence
        if not 0 <= index < len(sequence):
            raise IndexError(index)
        node = sequence[index].node
        self._apply([_Edit(node.start_byte, node.end_byte, text.encode("utf-8"))])
        return self

    def move_command(self, from_index: int, to_index: int) -> Script:
        """Move the command at *from_index* so it ends up at *to_index* in the sequence."""
        sequence = self._mission_sequence
        count = len(sequence)
        if not 0 <= from_index < count:
            raise IndexError(from_index)
        if not 0 <= to_index < count:
            raise IndexError(to_index)
        if count == 1 or from_index == to_index:
            return self
        source = self._text.encode("utf-8")
        moved_node = sequence[from_index].node
        start, end = line_span(source, moved_node.start_byte, moved_node.end_byte)
        moved = source[start:end]
        remaining = [sequence[i].node for i in range(count) if i != from_index]
        if to_index < len(remaining):
            target = remaining[to_index]
            offset = line_span(source, target.start_byte, target.end_byte)[0]
        else:
            target = remaining[-1]
            offset = line_span(source, target.start_byte, target.end_byte)[1]
        self._apply([_Edit(start, end, b""), _Edit(offset, offset, moved)])
        return self

    # -- dunders --------------------------------------------------------------------------------

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


def _assignment_field(assignment: Node) -> str | None:
    """The dotted field path an ``assignment_command`` targets, or ``None`` for a non-field."""
    left = assignment.child_by_field_name("left")
    if left is None or left.type != "member_expression":
        return None
    _, segments = split_reference(left)
    return ".".join(segments) if segments else None


def _drop_name_edit(name_nodes: list[Node], name: str) -> _Edit:
    """The edit removing *name* (and one adjacent separator) from a multi-name ``Create``."""
    index = next(i for i, node in enumerate(name_nodes) if node_text(node) == name)
    target = name_nodes[index]
    if index > 0:
        return _Edit(name_nodes[index - 1].end_byte, target.end_byte, b"")
    return _Edit(target.start_byte, name_nodes[1].start_byte, b"")
