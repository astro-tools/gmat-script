"""The two reference collectors the relationship rules share.

* :func:`collect_value_references` — *generous*: every name used as a value or operand anywhere,
  backing ``unused-resource`` (over-counting a use only suppresses a finding, the safe direction).
* :func:`object_reference_uses` — *high-confidence*: only the values of catalogue-typed
  object-reference fields, backing ``undeclared-reference`` and ``ref-target-mismatch``. Keeping the
  scope to fields the catalogue marks as object references is what holds those rules to zero false
  positives on real scripts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..ast.base import node_text

if TYPE_CHECKING:
    from tree_sitter import Node

    from .context import LintContext

__all__ = ["ObjectRefUse", "collect_value_references", "object_reference_uses", "reference_root"]

_BOOLEANS = frozenset({"true", "false"})
_SKIP_NODE_TYPES = frozenset(
    {"create_command", "comment", "begin_mission_sequence", "include", "script_body"}
)


def reference_root(node: Node) -> Node:
    """The leftmost identifier of a reference — the object a dotted / indexed path is rooted at.

    ``Sat.SMA`` → ``Sat``; ``FM.GravityField.Earth.Degree`` → ``FM``; ``A(1, 1)`` → ``A``.
    """
    current = node
    while True:
        if current.type == "member_expression":
            obj = current.child_by_field_name("object")
            if obj is None:  # pragma: no cover - a member_expression always has an object
                return current
            current = obj
        elif current.type == "call_expression":
            function = current.child_by_field_name("function")
            if function is None:  # pragma: no cover - a call always has a function
                return current
            current = function
        else:
            return current


def collect_value_references(ctx: LintContext) -> dict[str, list[Node]]:
    """Map every name used in a value / operand position to its usage nodes (the generous scan)."""
    refs: dict[str, list[Node]] = {}

    def add(name: str, node: Node) -> None:
        if name in _BOOLEANS:
            return
        refs.setdefault(name, []).append(node)

    def walk(node: Node, in_config: bool) -> None:
        kind = node.type
        if kind in _SKIP_NODE_TYPES:
            return
        if kind == "assignment_command" and in_config:
            # A configuration assignment's left side is the resource configuring itself — not a use.
            right = node.child_by_field_name("right")
            if right is not None:  # pragma: no branch - a clean-parse assignment carries a right
                walk(right, in_config)
            return
        if kind == "member_expression":
            root = reference_root(node)
            add(node_text(root), root)
            return
        if kind == "call_expression":
            function = node.child_by_field_name("function")
            arguments = node.child_by_field_name("arguments")
            if function is not None:  # pragma: no branch - a clean-parse call has a function
                walk(function, in_config)
            if arguments is not None:  # pragma: no branch - a clean-parse call has arguments
                for argument in arguments.named_children:
                    walk(argument, in_config)
            return
        if kind == "identifier":
            add(node_text(node), node)
            return
        for child in node.named_children:
            walk(child, in_config)

    for node in ctx.config_nodes:
        walk(node, True)
    for node in ctx.sequence_nodes:
        walk(node, False)
    return refs


@dataclass(frozen=True, slots=True)
class ObjectRefUse:
    """One object naming inside a catalogue-typed object-reference field value."""

    name: str
    node: Node
    resource: str
    resource_type: str
    field: str
    target: str


def object_reference_uses(ctx: LintContext) -> list[ObjectRefUse]:
    """Object names referenced through catalogue-typed object-reference fields (config section)."""
    uses: list[ObjectRefUse] = []
    for assignment in ctx.config_field_assignments:
        if len(assignment.segments) != 1:
            continue  # only single-segment fields carry a flat catalogue spec
        resource_type = ctx.resource_type(assignment.resource)
        if resource_type is None:
            continue  # an undeclared root is the reference rules' concern, not this collector's
        spec = ctx.catalog.field(resource_type, assignment.segments[0])
        if spec is None or spec.type not in ("object", "object_array") or not spec.ref_target:
            continue
        for value_node in _object_value_nodes(assignment.value_node):
            root = reference_root(value_node)
            name = node_text(root)
            if name in _BOOLEANS:
                continue
            uses.append(
                ObjectRefUse(
                    name=name,
                    node=root,
                    resource=assignment.resource,
                    resource_type=resource_type,
                    field=assignment.segments[0],
                    target=spec.ref_target,
                )
            )
    return uses


def _object_value_nodes(value: Node) -> list[Node]:
    """The identifier / member-reference nodes naming objects in an object-field value.

    A scalar object field is one reference; an ``object_array`` field is a brace-list ``{a, b}`` of
    them. Non-reference values (a number, a quoted string) are not object namings — left to the
    type rules — so they are skipped here.
    """
    if value.type in ("identifier", "member_expression"):
        return [value]
    if value.type == "list":
        return [
            child
            for child in value.named_children
            if child.type in ("identifier", "member_expression")
        ]
    return []
