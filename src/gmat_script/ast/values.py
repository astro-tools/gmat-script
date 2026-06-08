"""Structural coercion of CST value nodes to Python values.

Coercion is *structural* — inferred from a literal's shape, never from the field catalogue (that
semantic typing is the linter's job). It is total: every value node the grammar can place on
the right-hand side of an assignment maps to a :data:`Value`, with :class:`RawValue` as the
raw-text fallback for the forms that have no faithful Python reduction (computed expressions, GMAT's
unquoted rest-of-line values).

The mapping:

===========================  ==========================================================
CST node                     Python value
===========================  ==========================================================
``number``                   :class:`int` (integer literal) or :class:`float`
``string``                   :class:`str` (single quotes stripped; no escapes, D3)
``identifier`` ``true``/``false``  :class:`bool`
``identifier`` (other)       :class:`ObjectRef`
``member_expression``        :class:`ObjectRef` (the dotted path)
``unary_expression`` of a number  signed :class:`int` / :class:`float`
``list`` (``{…}``)           :class:`list` of coerced elements
``array_literal`` (``[…]``)  :class:`Array` (1-D elements, or :class:`Array` rows for a 2-D matrix)
everything else              :class:`RawValue` (raw source text)
===========================  ==========================================================

The brace-list ``{…}`` and the square-bracket array ``[…]`` are kept as distinct Python types — a
plain :class:`list` and an :class:`Array` — even though both hold coerced elements, because GMAT
emits them differently (``{a, b}`` vs ``[a b]``): collapsing them to one type would lose the form on
a read-modify-write round-trip.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeAlias, Union

from .base import node_text

if TYPE_CHECKING:
    from tree_sitter import Node

__all__ = ["Array", "ObjectRef", "RawValue", "Value", "coerce_value"]


@dataclass(frozen=True, slots=True)
class ObjectRef:
    """A reference to a GMAT object, or a dotted member of one — e.g. ``Earth``, ``Sat.SMA``.

    Distinguishes a bare or dotted *name* used as a value (an object reference) from a quoted
    string with the same text. Whether the referenced object actually exists is the linter's
    concern, not this layer's.
    """

    name: str


@dataclass(frozen=True, slots=True)
class RawValue:
    """The raw source text of a value with no structural Python reduction (the fallback).

    Carries GMAT's unquoted rest-of-line values (multi-word enums, unquoted paths / dates, the
    doubled-quote artifact) and computed right-hand sides (arithmetic, function calls, indexed or
    parenthesised expressions). The text is the exact source slice (D6); interpreting it further is
    left to the consumer (or the linter / catalogue).
    """

    text: str


@dataclass(frozen=True, slots=True)
class Array:
    """A square-bracket value — a 1-D array ``[a b c]`` or a 2-D matrix ``[r1; r2]`` (D13).

    Distinguishes GMAT's whitespace-separated ``[…]`` array / matrix from the comma-separated
    ``{…}`` brace-list (a plain :class:`list`): both coerce element-wise, but they emit to different
    GMAT forms, so the type must be preserved for a lossless round-trip. A 2-D matrix is an
    :class:`Array` whose every element is itself an :class:`Array` row. ``elements`` is a tuple so
    the value stays immutable and hashable, like the other value types.
    """

    elements: tuple[Value, ...]


# A coerced GMAT value. Recursive: brace-lists and arrays nest. ``Union`` (not ``|``) is required
# because the alias is evaluated at runtime and carries a forward reference to itself.
Value: TypeAlias = Union[bool, int, float, str, ObjectRef, RawValue, Array, "list[Value]"]

_BOOLEAN_LITERALS = frozenset({"true", "false"})


def coerce_value(node: Node) -> Value:
    """Coerce a CST value *node* to its structural Python :data:`Value` (see the module table)."""
    kind = node.type
    if kind == "number":
        return _coerce_number(node_text(node))
    if kind == "string":
        return _coerce_string(node_text(node))
    if kind == "identifier":
        text = node_text(node)
        if text in _BOOLEAN_LITERALS:
            return text == "true"
        return ObjectRef(text)
    if kind == "member_expression":
        return ObjectRef(node_text(node))
    if kind == "unary_expression":
        return _coerce_unary(node)
    if kind == "list":
        return [coerce_value(child) for child in node.named_children]
    if kind == "array_literal":
        return _coerce_array(node)
    # call_expression, parenthesized_expression, binary_expression, option_assignment,
    # unquoted_value, and anything unforeseen: no faithful structural reduction — keep the raw text.
    return RawValue(node_text(node))


def _coerce_number(text: str) -> int | float:
    """Integer literal → :class:`int`; anything with a fraction or exponent → :class:`float`."""
    if any(c in text for c in ".eE"):
        return float(text)
    return int(text)


def _coerce_string(text: str) -> str:
    """Strip the delimiting single quotes from a ``string`` token (no escapes to unescape, D3).

    A ``string`` token is always quoted (``'…'``, length ≥ 2), so trimming one char each side is
    safe; an empty / degenerate token from error recovery trims to ``""`` rather than raising.
    """
    return text[1:-1]


def _coerce_unary(node: Node) -> Value:
    """A leading ``+`` / ``-`` on a number applies the sign; on anything else it stays raw."""
    operand = node.child_by_field_name("operand")
    inner = coerce_value(operand) if operand is not None else None
    # ``bool`` is an ``int`` subclass — exclude it so ``-true`` (never valid) stays raw, not an int.
    if isinstance(inner, bool) or not isinstance(inner, (int, float)):
        return RawValue(node_text(node))
    operator = node.child_by_field_name("operator")
    negate = operator is not None and node_text(operator) == "-"
    return -inner if negate else inner


def _coerce_array(node: Node) -> Array:
    """A 1-D ``[…]`` literal → a flat :class:`Array`; a 2-D matrix (``;`` row separators) → an
    :class:`Array` whose elements are each a row :class:`Array`."""
    current: list[Value] = []
    rows: list[Array] = []
    is_matrix = False
    for child in node.children:
        if not child.is_named:
            if node_text(child) == ";":
                is_matrix = True
                rows.append(Array(tuple(current)))
                current = []
            continue
        current.append(coerce_value(child))
    if not is_matrix:
        return Array(tuple(current))
    rows.append(Array(tuple(current)))
    return Array(tuple(rows))
