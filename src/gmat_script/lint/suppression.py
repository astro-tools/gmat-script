"""Inline suppression directives — ``% gmat-script: disable[-line]`` — parsed from the source text.

Two forms (the issue's "inline suppression"):

* ``% gmat-script: disable-line=<rule>[,<rule>...]`` — suppress the listed rules on the *physical
  line the comment sits on* (so a trailing comment suppresses its own code line).
* ``% gmat-script: disable=<rule>[,<rule>...]`` — suppress the rules from the directive's line
  to the end of the file (placed at the top, that is the whole file).

Omitting ``=<rules>`` suppresses *all* rules for that scope. Directives are found by scanning lines,
not by walking the tree: a trailing comment is not exposed as a CST node, and GMAT strings cannot
contain ``%`` (D3), so the first ``%`` on a line unambiguously begins a comment.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .diagnostics import Diagnostic

__all__ = ["Suppressions", "filter_diagnostics", "parse_suppressions"]

# ``% gmat-script: disable-line=a,b`` / ``disable=a`` / bare ``disable`` — disable-line first so the
# longer keyword wins the alternation. The rule list (group 2) is an optional ``=`` clause.
_DIRECTIVE = re.compile(
    r"%\s*gmat-script:\s*(disable-line|disable)\b\s*(?:=\s*([A-Za-z0-9_,\s-]+))?"
)

# A sentinel rule set meaning "all rules" (a directive with no ``=<rules>`` clause). Compared by
# identity so it never collides with a real (kebab-case) rule code.
_ALL: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class Suppressions:
    """Parsed suppression scopes: per-line directives and line→EOF ranges (``_ALL`` = all rules)."""

    line: dict[int, frozenset[str]] = field(default_factory=dict)
    ranges: list[tuple[int, frozenset[str]]] = field(default_factory=list)

    def suppresses(self, rule: str, line: int) -> bool:
        """Whether *rule* at 1-indexed *line* is suppressed by any directive."""
        scope = self.line.get(line)
        if scope is not None and (scope is _ALL or rule in scope):
            return True
        return any(
            start <= line and (codes is _ALL or rule in codes) for start, codes in self.ranges
        )


def _parse_codes(raw: str | None) -> frozenset[str]:
    """The rule set from a directive's ``=<rules>`` clause; ``_ALL`` when the clause is absent."""
    if raw is None:
        return _ALL
    codes = frozenset(token.strip() for token in raw.split(",") if token.strip())
    return codes if codes else _ALL


def parse_suppressions(source: str) -> Suppressions:
    """Scan *source* for ``% gmat-script: disable[-line]`` directives into a ``Suppressions``."""
    line_scopes: dict[int, frozenset[str]] = {}
    ranges: list[tuple[int, frozenset[str]]] = []
    # Split on "\n" only so line numbers match tree-sitter's row count (which counts "\n"); a
    # trailing "\r" from a CRLF line stays in the text and the directive regex tolerates it. A line
    # holds at most one directive — everything after the first "%" is one comment — so each scope is
    # recorded once.
    for index, text in enumerate(source.split("\n"), start=1):
        match = _DIRECTIVE.search(text)
        if match is None:
            continue
        codes = _parse_codes(match.group(2))
        if match.group(1) == "disable-line":
            line_scopes[index] = codes
        else:
            ranges.append((index, codes))
    return Suppressions(line=line_scopes, ranges=ranges)


def filter_diagnostics(
    diagnostics: Iterable[Diagnostic], suppressions: Suppressions
) -> list[Diagnostic]:
    """Drop the diagnostics a directive suppresses, keeping the rest in their original order."""
    return [d for d in diagnostics if not suppressions.suppresses(d.rule, d.line)]
