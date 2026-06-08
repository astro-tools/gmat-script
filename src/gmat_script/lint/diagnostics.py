"""The diagnostic data the linter produces — a typed finding with a source range.

A :class:`Diagnostic` is *data*, never an exception: every rule yields zero or more of them and the
engine collects, suppresses, and sorts them (mirrors the parser's ``ErrorNode`` contract, D7). Each
carries the rule code that raised it, a :class:`Severity`, a 1-indexed ``Position``
range into the source (compiler convention, D8), and a short human message.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from ..parser import Position

if TYPE_CHECKING:
    from tree_sitter import Node

__all__ = ["Diagnostic", "Severity", "node_range"]


class Severity(str, Enum):
    """A diagnostic's severity. A ``str`` enum so it serialises to its value verbatim in JSON."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """One linter finding: a rule code, a severity, a message, and a 1-indexed source range."""

    rule: str
    severity: Severity
    message: str
    start: Position
    end: Position

    @property
    def line(self) -> int:
        """The 1-indexed start line — the physical line suppression and reporting key off."""
        return self.start.line

    def sort_key(self) -> tuple[int, int, str]:
        """Order diagnostics by position, then rule code, for a stable report."""
        return (self.start.line, self.start.column, self.rule)


def node_range(node: Node) -> tuple[Position, Position]:
    """The ``(start, end)`` 1-indexed :class:`~gmat_script.Position` pair of a CST *node* (D8).

    tree-sitter points are 0-indexed (row, byte-column); the linter reports 1-indexed line/column to
    match :func:`gmat_script.parse`'s ``ErrorNode`` positions and the ``parse`` CLI.
    """
    start, end = node.start_point, node.end_point
    return (
        Position(line=start.row + 1, column=start.column + 1),
        Position(line=end.row + 1, column=end.column + 1),
    )
