"""The rule registry and the select / ignore resolution the engine and CLI use.

A :class:`Rule` pairs a kebab-case code with the function that checks it. Rules are individually
toggleable: :func:`resolve_rules` applies a ``select`` allow-list and ``ignore`` deny-list, raising
on an unknown code so a typo in a CLI flag fails loudly instead of silently doing nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

    from .context import LintContext
    from .diagnostics import Diagnostic

__all__ = ["Rule", "resolve_rules"]


@dataclass(frozen=True)
class Rule:
    """A lint rule: its code, a one-line summary, and the check that yields its diagnostics."""

    code: str
    summary: str
    check: Callable[[LintContext], Iterable[Diagnostic]]


def resolve_rules(
    rules: Sequence[Rule],
    select: Iterable[str] | None = None,
    ignore: Iterable[str] | None = None,
) -> list[Rule]:
    """The rules to run after applying *select* (allow-list) then *ignore* (deny-list).

    With *select* ``None`` every rule is eligible; an explicit *select* keeps only those codes.
    *ignore* then removes codes. Both are validated against the known codes — an unknown code raises
    :class:`ValueError` (the CLI surfaces it) rather than passing silently.
    """
    known = {rule.code for rule in rules}
    select_set = _validate(select, known, "select") if select is not None else None
    ignore_set = _validate(ignore, known, "ignore") if ignore is not None else set()
    chosen = []
    for rule in rules:
        if select_set is not None and rule.code not in select_set:
            continue
        if rule.code in ignore_set:
            continue
        chosen.append(rule)
    return chosen


def _validate(codes: Iterable[str], known: set[str], flag: str) -> set[str]:
    """Return *codes* as a set, raising :class:`ValueError` on any code not in *known*."""
    requested = set(codes)
    unknown = sorted(requested - known)
    if unknown:
        raise ValueError(f"unknown {flag} rule code(s): {', '.join(unknown)}")
    return requested
