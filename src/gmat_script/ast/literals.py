"""Emit a structural Python value back to its canonical GMAT source literal.

The inverse of :mod:`gmat_script.ast.values`' coercion: given a
:data:`~gmat_script.ast.values.Value`, :func:`emit_value` produces the GMAT source text for it. The
mutation layer uses it to format the
literal it writes when a field or operand is set; the formatter shares the same helpers so the two
layers emit values identically.

Emission is *canonical*, not round-trip-faithful to a specific source spelling: a Python value maps
to one chosen GMAT form, so re-emitting a coerced value need not reproduce the original bytes (the
edited span is re-emitted in canonical form — the lossless guarantee covers only *untouched* text,
D6). Two coercion forms are deliberately collapsed:

- a flat :class:`list` emits as a brace-list ``{a, b}`` — the common field form (``Tanks = {Tank}``)
  — not a square-bracket array; pass a :class:`~gmat_script.ast.values.RawValue` for an exact
  ``[1 2 3]`` spelling;
- a list whose every element is itself a list emits as a 2-D matrix ``[r; r]`` (the ``[…;…]`` form,
  D13), so a coerced matrix round-trips.

:class:`~gmat_script.ast.values.RawValue` and :class:`~gmat_script.ast.values.ObjectRef` emit their
text verbatim, so they are the escape hatch for any form with no structural Python reduction.
"""

from __future__ import annotations

import math

from .values import ObjectRef, RawValue, Value

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
        return value.name
    if isinstance(value, RawValue):
        return value.text
    if isinstance(value, list):
        return _emit_list(value)
    raise TypeError(f"cannot emit a value of type {type(value).__name__!r}")


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
    """A non-empty all-list value as a ``[…;…]`` matrix; anything else as a ``{…}`` brace-list."""
    if value and all(isinstance(element, list) for element in value):
        rows = "; ".join(
            " ".join(emit_value(cell) for cell in row) for row in value if isinstance(row, list)
        )
        return f"[{rows}]"
    return "{" + ", ".join(emit_value(element) for element in value) + "}"
