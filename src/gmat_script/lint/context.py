"""The shared analysis a linter run computes once and every rule reads.

:class:`LintContext` bundles the parsed :class:`~gmat_script.Script`, its ``Tree``, the resolved
:class:`~gmat_script.Catalog`, and structural indices derived from the tree
so each rule does not re-walk it: the ordered :class:`Declaration` list (every ``Create``'d name,
*including* duplicates the ``Script`` view collapses), the configuration-section field assignments
(:class:`FieldAssignment`), and the raw text of any ``BeginScript`` blocks. The reference collectors
that several rules share live in :mod:`gmat_script.lint.references`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..ast.base import node_text
from ..ast.resource import split_reference

if TYPE_CHECKING:
    from tree_sitter import Node

    from ..ast.script import Script
    from ..catalog import Catalog
    from ..parser import Tree

__all__ = ["Declaration", "FieldAssignment", "LintContext"]


@dataclass(frozen=True, slots=True)
class Declaration:
    """One name introduced by a ``Create`` — one per name, so ``Create Variable x y`` is two.

    A multi-name or repeated ``Create`` yields several declarations; :attr:`type_node` and
    :attr:`create_node` are shared, :attr:`name_node` is the specific name.
    """

    name: str
    type: str
    type_node: Node
    name_node: Node
    create_node: Node


@dataclass(frozen=True, slots=True)
class FieldAssignment:
    """A configuration-section ``resource.field[...] = value`` assignment.

    :attr:`segments` is the dotted field path after the resource root (``("SMA",)`` for ``Sat.SMA``,
    ``("GravityField", "Earth", "Degree")`` for the nested form); :attr:`field_node` is the last
    segment's node (where a field diagnostic points), :attr:`value_node` the right-hand side.
    """

    resource: str
    segments: tuple[str, ...]
    left_node: Node
    field_node: Node
    value_node: Node


class LintContext:
    """Everything a rule needs about one script: the model, the catalogue, and shared indices."""

    __slots__ = (
        "_config_nodes",
        "_sequence_nodes",
        "_value_refs",
        "catalog",
        "config_field_assignments",
        "declarations",
        "declared_names",
        "script",
        "script_block_texts",
        "tree",
    )

    def __init__(self, script: Script, tree: Tree, catalog: Catalog) -> None:
        self.script = script
        self.tree = tree
        self.catalog = catalog

        children = list(tree.root_node.named_children)
        marker = next(
            (i for i, child in enumerate(children) if child.type == "begin_mission_sequence"), None
        )
        self._config_nodes: list[Node] = children if marker is None else children[:marker]
        self._sequence_nodes: list[Node] = [] if marker is None else children[marker + 1 :]

        self.declarations: tuple[Declaration, ...] = self._collect_declarations()
        self.declared_names: frozenset[str] = frozenset(d.name for d in self.declarations)
        self.config_field_assignments: tuple[FieldAssignment, ...] = self._collect_config_fields()
        self.script_block_texts: tuple[str, ...] = self._collect_script_texts()
        self._value_refs: dict[str, list[Node]] | None = None

    # -- read accessors -------------------------------------------------------------------------

    @property
    def config_nodes(self) -> list[Node]:
        """The top-level configuration-section nodes (before ``BeginMissionSequence``)."""
        return self._config_nodes

    @property
    def sequence_nodes(self) -> list[Node]:
        """The top-level mission-sequence nodes (after ``BeginMissionSequence``)."""
        return self._sequence_nodes

    def resource_type(self, name: str) -> str | None:
        """The declared GMAT type of resource *name*, or ``None`` if it was never created."""
        resource = self.script.resources.get(name)
        return resource.type if resource is not None else None

    # -- index construction ---------------------------------------------------------------------

    def _collect_declarations(self) -> tuple[Declaration, ...]:
        """Every name declared by a ``Create`` in the configuration section, in source order."""
        declarations: list[Declaration] = []
        for node in self._config_nodes:
            if node.type != "create_command":
                continue
            type_node = node.child_by_field_name("type")
            if type_node is None:  # pragma: no cover - a Create always carries a type
                continue
            type_name = node_text(type_node)
            for name_node in node.children_by_field_name("name"):
                declarations.append(
                    Declaration(
                        name=node_text(name_node),
                        type=type_name,
                        type_node=type_node,
                        name_node=name_node,
                        create_node=node,
                    )
                )
        return tuple(declarations)

    def _collect_config_fields(self) -> tuple[FieldAssignment, ...]:
        """Every dotted ``resource.field = value`` assignment in the configuration section.

        Bare-name (``x = 5``) and array-element (``A(1,1) = …``) targets are excluded — they reach
        a resource but are not field assignments.
        """
        assignments: list[FieldAssignment] = []
        for node in self._config_nodes:
            if node.type != "assignment_command":
                continue
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            if left is None or right is None or left.type != "member_expression":
                continue
            root_name, segments = split_reference(left)
            if not segments:  # pragma: no cover - a member_expression yields >=1 segment
                continue
            field_node = left.child_by_field_name("property")
            assignments.append(
                FieldAssignment(
                    resource=root_name,
                    segments=tuple(segments),
                    left_node=left,
                    field_node=field_node if field_node is not None else left,
                    value_node=right,
                )
            )
        return tuple(assignments)

    def _collect_script_texts(self) -> tuple[str, ...]:
        """The raw body text of every ``BeginScript`` block (opaque to parsing, scanned as text)."""
        texts: list[str] = []
        stack: list[Node] = list(self.tree.root_node.children)
        while stack:
            node = stack.pop()
            if node.type == "script_body":
                texts.append(node_text(node))
                continue
            stack.extend(node.children)
        return tuple(texts)

    def value_references(self) -> dict[str, list[Node]]:
        """Names used in a value / operand position anywhere, mapped to their usage nodes (cached).

        Deliberately *generous*: it counts every identifier and dotted-reference root used as value
        — a config RHS, a command operand, a condition, a list / array / call argument
        — but not declarations, field-property names, or a configuration assignment's own left-hand
        target. Over-counting only ever *suppresses* an ``unused-resource`` finding (the safe
        direction), so this is the right bias for the rule that consumes it.
        """
        if self._value_refs is None:
            from .references import collect_value_references

            self._value_refs = collect_value_references(self)
        return self._value_refs
