"""Emit a structural Python value back to its canonical GMAT source literal.

The inverse of :mod:`gmat_script.ast.values`' coercion: given a
:data:`~gmat_script.ast.values.Value`, :func:`emit_value` produces the GMAT source text for it. The
mutation layer uses it to format the
literal it writes when a field or operand is set; the formatter shares the same helpers so the two
layers emit values identically.

Emission is *canonical*, not round-trip-faithful to a specific source spelling: a Python value maps
to one chosen GMAT form, so re-emitting a coerced value need not reproduce the original bytes (the
edited span is re-emitted in canonical form — the lossless guarantee covers only *untouched* text,
D6). The two GMAT collection forms are type-distinguished so each round-trips:

- a :class:`list` emits as a brace-list ``{a, b}`` — the common field form (``Tanks = {Tank}``);
- an :class:`~gmat_script.ast.values.Array` emits as a square-bracket array ``[a b]`` (1-D), or a
  2-D matrix ``[r; r]`` when its every element is itself an :class:`Array` row (the ``[…;…]`` form,
  D13).

:class:`~gmat_script.ast.values.RawValue` and :class:`~gmat_script.ast.values.ObjectRef` emit their
text verbatim, so they are the escape hatch for any form with no structural Python reduction.
"""

from __future__ import annotations

import math

from .values import Array, ObjectRef, RawValue, Value

__all__ = ["emit_value"]


def emit_value(value: Value) -> str:
    """Emit *value* as canonical GMAT source text (see the module docstring for the conventions).

    :raises ValueError: for a non-finite float (``nan`` / ``inf`` have no GMAT literal) or a string
        carrying a character GMAT strings cannot hold (a single quote or a newline — there are no
        escapes, D3).
    :raises TypeError: for a value outside the :data:`~gmat_script.ast.values.Value` union.
    """
    # ``bool`` is a subclass of ``int`` — test it first so ``True`` emits ``true``, not ``1``.
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _emit_float(value)
    if isinstance(value, str):
        return _emit_string(value)
    if isinstance(value, ObjectRef):
        return _bare_text(value.name, "object reference")
    if isinstance(value, RawValue):
        return _bare_text(value.text, "raw value")
    if isinstance(value, Array):
        return _emit_array(value)
    if isinstance(value, list):
        return _emit_list(value)
    raise TypeError(f"cannot emit a value of type {type(value).__name__!r}")


def _bare_text(text: str, kind: str) -> str:
    """An :class:`ObjectRef` / :class:`RawValue`'s verbatim text, rejecting the forms that corrupt
    the script without tripping the re-parse guard: an empty / whitespace-only value (it leaves a
    dangling ``=`` that swallows the following line as its right-hand side) or one carrying a
    newline (it splices in extra statements that are themselves valid GMAT)."""
    if not text.strip():
        raise ValueError(f"cannot emit an empty {kind}")
    if "\n" in text or "\r" in text:
        raise ValueError(f"{kind} {text!r} cannot contain a newline")
    return text


def _emit_float(value: float) -> str:
    """A finite float as its shortest round-tripping decimal (``850.0``, ``0.125``, ``1e+70``)."""
    if not math.isfinite(value):
        raise ValueError("cannot emit a non-finite float (nan / inf have no GMAT literal)")
    return repr(value)


def _emit_string(value: str) -> str:
    """A string as a single-quoted GMAT literal; reject the characters a literal cannot carry."""
    if "'" in value or "\n" in value or "\r" in value:
        raise ValueError("a GMAT string literal cannot contain a single quote or a newline")
    return f"'{value}'"


def _emit_list(value: list[Value]) -> str:
    """A brace-list ``{a, b}`` — the comma-separated ``{…}`` form (nested lists nest as braces)."""
    return "{" + ", ".join(emit_value(element) for element in value) + "}"


def _emit_array(value: Array) -> str:
    """A square-bracket array: ``[a b]`` (1-D), or a ``[r; r]`` matrix when every element is an
    :class:`Array` row."""
    elements = value.elements
    if elements and all(isinstance(element, Array) for element in elements):
        rows = "; ".join(
            " ".join(emit_value(cell) for cell in row.elements)
            for row in elements
            if isinstance(row, Array)
        )
        return f"[{rows}]"
    return "[" + " ".join(emit_value(element) for element in elements) + "]"
