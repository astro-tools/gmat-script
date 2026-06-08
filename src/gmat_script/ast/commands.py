"""Typed mission-sequence command nodes.

Each statement after ``BeginMissionSequence`` is viewed through a typed :class:`Command` selected by
:func:`build_command` from its CST node type: the generic keyword commands (:class:`GenericCommand`
— ``Propagate``, ``Maneuver``, ``Vary``, …), assignments (:class:`Assignment`), output-binding
function calls (:class:`FunctionCall`), the control-flow blocks (:class:`IfStatement`,
:class:`ForStatement`, :class:`WhileStatement`), the solver blocks (:class:`TargetStatement`,
:class:`OptimizeStatement`), and the opaque :class:`ScriptBlock`. Block bodies are themselves
sequences of typed commands, built recursively. Operands are coerced through
:mod:`gmat_script.ast.values`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import BLOCK_HEADER_FIELDS, AstNode, node_text
from .values import ObjectRef, RawValue, Value, coerce_value

if TYPE_CHECKING:
    from tree_sitter import Node

__all__ = [
    "Assignment",
    "Command",
    "ForStatement",
    "FunctionCall",
    "GenericCommand",
    "IfStatement",
    "OptimizeStatement",
    "ScriptBlock",
    "TargetStatement",
    "WhileStatement",
    "build_command",
]


def _unquote_label(node: Node | None) -> str | None:
    """A ``command_label`` node's text without its surrounding single quotes; ``None`` if absent."""
    if node is None:
        return None
    return node_text(node)[1:-1]


class Command(AstNode):
    """Base for a mission-sequence statement — a typed view over one CST command node.

    The concrete subclass is chosen by :func:`build_command`; the base itself is the fallback for
    any statement the overlay does not specialise (it still exposes :attr:`keyword`, :attr:`label`,
    source provenance, and byte-exact :meth:`~.base.AstNode.to_source`).
    """

    __slots__ = ()

    @property
    def keyword(self) -> str:
        """The leading keyword identifying this command (``Propagate``, ``If``, ``Target``, …)."""
        first = self._node.children[0] if self._node.child_count else None
        if first is not None and not first.is_named:
            return node_text(first)
        name = self._node.child_by_field_name("name")
        if name is not None:
            return node_text(name)
        return self._node.type

    @property
    def label(self) -> str | None:
        """The optional single-quoted command label (``'…'``) without quotes; ``None`` if absent."""
        return _unquote_label(self._node.child_by_field_name("label"))


class GenericCommand(Command):
    """A generic mission command — ``Propagate``, ``Maneuver``, ``Vary``, ``Report``, ``Stop``, and
    any unrecognised keyword (D3). Its head is :attr:`name`; its operands are :attr:`arguments`."""

    __slots__ = ()

    @property
    def name(self) -> str:
        """The command head — the keyword, or a bare-call reference (``Obj.SetModelParameter``)."""
        name = self._node.child_by_field_name("name")
        return node_text(name) if name is not None else self.keyword

    @property
    def arguments(self) -> tuple[Value, ...]:
        """The command's operands, coerced — everything after the head and the optional label."""
        skip = {
            field.id
            for field in (
                self._node.child_by_field_name("name"),
                self._node.child_by_field_name("label"),
            )
            if field is not None
        }
        return tuple(
            coerce_value(child) for child in self._node.named_children if child.id not in skip
        )


class Assignment(Command):
    """A mission-sequence assignment ``[GMAT] [label] <target> = <value>`` — a computed write."""

    __slots__ = ()

    @property
    def target(self) -> ObjectRef:
        """The left-hand side as an :class:`~.values.ObjectRef` (the assigned reference / path)."""
        left = self._node.child_by_field_name("left")
        return ObjectRef(node_text(left) if left is not None else "")

    @property
    def value(self) -> Value:
        """The right-hand side, coerced (often a :class:`~.values.RawValue` — sequence RHSs
        compute)."""
        right = self._node.child_by_field_name("right")
        return coerce_value(right) if right is not None else RawValue("")


class FunctionCall(Command):
    """An output-binding function call ``[out, …] = name(args)`` (D4)."""

    __slots__ = ()

    @property
    def outputs(self) -> tuple[str, ...]:
        """The bound output names, in order (empty for ``[] = …``)."""
        outputs = self._node.child_by_field_name("outputs")
        if outputs is None:  # pragma: no cover - the grammar requires the bracket output list
            return ()
        return tuple(
            node_text(child) for child in outputs.named_children if child.type == "identifier"
        )

    @property
    def function(self) -> str:
        """The callee name — dotted external calls keep their full path (``Python.mod.Fn``)."""
        function = self._node.child_by_field_name("function")
        if function is None:  # pragma: no cover - the grammar requires the callee reference
            return ""
        if function.type == "call_expression":
            callee = function.child_by_field_name("function")
            return node_text(callee) if callee is not None else node_text(function)
        return node_text(function)

    @property
    def arguments(self) -> tuple[Value, ...]:
        """The call arguments, coerced — empty when the call form carries no ``(…)``."""
        function = self._node.child_by_field_name("function")
        if function is None or function.type != "call_expression":
            return ()
        argument_list = function.child_by_field_name("arguments")
        if argument_list is None:  # pragma: no cover - a call always has an argument list
            return ()
        return tuple(coerce_value(child) for child in argument_list.named_children)


def _block_body(node: Node, *, exclude: tuple[str, ...] = ()) -> tuple[Command, ...]:
    """The nested statements of a block — its named children minus the block's own fields and any
    *exclude*'d child types (e.g. an ``if`` statement's ``else_clause``)."""
    skip = {
        field.id
        for name in BLOCK_HEADER_FIELDS
        if (field := node.child_by_field_name(name)) is not None
    }
    return tuple(
        build_command(child)
        for child in node.named_children
        if child.id not in skip and child.type not in exclude
    )


class IfStatement(Command):
    """``If <condition> … [Else …] EndIf`` — a conditional block (D3)."""

    __slots__ = ()

    @property
    def condition(self) -> Value:
        """The condition expression, coerced (a comparison surfaces as a
        :class:`~.values.RawValue`)."""
        condition = self._node.child_by_field_name("condition")
        return coerce_value(condition) if condition is not None else RawValue("")

    @property
    def body(self) -> tuple[Command, ...]:
        """The statements in the ``If`` branch (before any ``Else``)."""
        return _block_body(self._node, exclude=("else_clause",))

    @property
    def orelse(self) -> tuple[Command, ...]:
        """The statements in the ``Else`` branch, or empty if there is none."""
        else_clause = next(
            (child for child in self._node.named_children if child.type == "else_clause"), None
        )
        if else_clause is None:
            return ()
        return tuple(build_command(child) for child in else_clause.named_children)


class ForStatement(Command):
    """``For <variable> = <start>:[<step>:]<stop> … EndFor`` — a counted loop (D3)."""

    __slots__ = ()

    @property
    def variable(self) -> ObjectRef:
        """The loop variable as an :class:`~.values.ObjectRef`."""
        variable = self._node.child_by_field_name("variable")
        return ObjectRef(node_text(variable) if variable is not None else "")

    def _range_part(self, field: str) -> Value | None:
        range_node = self._node.child_by_field_name("range")
        if range_node is None:  # pragma: no cover - a For always carries a range
            return None
        part = range_node.child_by_field_name(field)
        return coerce_value(part) if part is not None else None

    # GMAT colon ranges are MATLAB-style ``start:step:stop``; the grammar's positional fields are
    # ``from`` : ``to`` [: ``by``], so in the three-term form ``to`` is the *step* and ``by`` the
    # *stop*, while the two-term form is plain ``start:stop`` (no step).

    @property
    def start(self) -> Value | None:
        """The range start value."""
        return self._range_part("from")

    @property
    def stop(self) -> Value | None:
        """The range stop value — the last colon-separated term."""
        by = self._range_part("by")
        return by if by is not None else self._range_part("to")

    @property
    def step(self) -> Value | None:
        """The range step, or ``None`` for the two-term ``start:stop`` form."""
        return self._range_part("to") if self._range_part("by") is not None else None

    @property
    def body(self) -> tuple[Command, ...]:
        """The loop body statements."""
        return _block_body(self._node)


class WhileStatement(Command):
    """``While <condition> … EndWhile`` — a conditional loop (D3)."""

    __slots__ = ()

    @property
    def condition(self) -> Value:
        """The loop condition, coerced."""
        condition = self._node.child_by_field_name("condition")
        return coerce_value(condition) if condition is not None else RawValue("")

    @property
    def body(self) -> tuple[Command, ...]:
        """The loop body statements."""
        return _block_body(self._node)


class _SolverBlock(Command):
    """Shared shape of the ``Target`` / ``Optimize`` solver blocks (D3)."""

    __slots__ = ()

    @property
    def solver(self) -> ObjectRef:
        """The solver this block drives, as an :class:`~.values.ObjectRef`."""
        solver = self._node.child_by_field_name("solver")
        return ObjectRef(node_text(solver) if solver is not None else "")

    @property
    def options(self) -> Value | None:
        """The solver-mode option block ``{…}``, coerced, or ``None`` if absent."""
        options = self._node.child_by_field_name("options")
        return coerce_value(options) if options is not None else None

    @property
    def body(self) -> tuple[Command, ...]:
        """The nested commands (``Vary`` / ``Achieve`` / ``Minimize`` / …)."""
        return _block_body(self._node)


class TargetStatement(_SolverBlock):
    """``Target <solver> [{opts}] … EndTarget`` — a differential-corrector block."""

    __slots__ = ()


class OptimizeStatement(_SolverBlock):
    """``Optimize <solver> [{opts}] … EndOptimize`` — an optimiser block."""

    __slots__ = ()


class ScriptBlock(Command):
    """``BeginScript … EndScript`` — an opaque raw-text block (D4)."""

    __slots__ = ()

    @property
    def body_text(self) -> str:
        """The raw, unparsed body text between ``BeginScript`` and ``EndScript`` (empty if none)."""
        body = next(
            (child for child in self._node.named_children if child.type == "script_body"), None
        )
        return node_text(body) if body is not None else ""


_BUILDERS: dict[str, type[Command]] = {
    "command": GenericCommand,
    "assignment_command": Assignment,
    "function_call_command": FunctionCall,
    "if_statement": IfStatement,
    "for_statement": ForStatement,
    "while_statement": WhileStatement,
    "target_statement": TargetStatement,
    "optimize_statement": OptimizeStatement,
    "script_block": ScriptBlock,
}


def build_command(node: Node) -> Command:
    """Wrap a CST statement *node* in its typed :class:`Command`; the base for an unmapped type."""
    return _BUILDERS.get(node.type, Command)(node)
