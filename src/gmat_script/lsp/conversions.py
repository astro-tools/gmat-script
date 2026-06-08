"""Position conversions between gmat-script's internal model and the LSP wire format.

The library counts positions two ways: the tree-sitter CST uses 0-indexed ``(row, byte_column)``
points (``Node.start_point`` / ``end_point``), and the parser and linter surface 1-indexed
``(line, column)`` :class:`~gmat_script.Position` records whose ``column`` is a byte offset (D8).
The Language Server Protocol uses a third convention: 0-indexed lines with 0-indexed UTF-16
character offsets. This module is the single place those map to one another, so every LSP response
speaks the protocol's units exactly — including on the multi-byte characters where a byte column and
a UTF-16 offset disagree.

:class:`LineIndex` splits a source into its line byte-spans once and converts both ways: CST
points and internal positions out to an :class:`lsprotocol.types.Range`, and an incoming LSP
:class:`~lsprotocol.types.Position` back to the ``(row, byte_column)`` point tree-sitter's
``descendant_for_point_range`` expects. It is total — an out-of-range line or column clamps rather
than raising — so a stale or malformed client position never crashes a handler.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lsprotocol import types as lsp

if TYPE_CHECKING:
    from tree_sitter import Node

    from ..parser import Position


def _utf16_units(text: str) -> int:
    """The number of UTF-16 code units *text* encodes to — the LSP character unit.

    A Basic-Multilingual-Plane character is one unit; an astral-plane one is a surrogate pair (two).
    Encoding to UTF-16 and halving the byte count counts both without a per-character branch.
    """
    return len(text.encode("utf-16-le")) // 2


class LineIndex:
    """A reusable per-source converter between CST / internal positions and LSP positions."""

    __slots__ = ("_lines",)

    def __init__(self, source: str) -> None:
        # One entry per line, split on LF; a CRLF line keeps its trailing '\r'. tree-sitter counts
        # rows by '\n' and includes the '\r' in the line's bytes, so the byte columns line up.
        self._lines: list[bytes] = source.encode("utf-8").split(b"\n")

    def _line_bytes(self, row: int) -> bytes:
        """The raw bytes of line *row* (LF-split), or empty for an out-of-range row."""
        if 0 <= row < len(self._lines):
            return self._lines[row]
        return b""

    def position_from_point(self, row: int, byte_column: int) -> lsp.Position:
        """Convert a 0-indexed tree-sitter ``(row, byte_column)`` point to an LSP position."""
        prefix = self._line_bytes(row)[:byte_column]
        return lsp.Position(line=row, character=_utf16_units(prefix.decode("utf-8", "replace")))

    def position_from_internal(self, position: Position) -> lsp.Position:
        """Convert a 1-indexed internal :class:`~gmat_script.Position` (byte column) to LSP."""
        return self.position_from_point(position.line - 1, position.column - 1)

    def range_of_node(self, node: Node) -> lsp.Range:
        """The LSP range spanning *node*, from its start point to its end point."""
        return lsp.Range(
            start=self.position_from_point(node.start_point.row, node.start_point.column),
            end=self.position_from_point(node.end_point.row, node.end_point.column),
        )

    def range_from_internal(self, start: Position, end: Position) -> lsp.Range:
        """The LSP range between two 1-indexed internal positions (a linter diagnostic span)."""
        return lsp.Range(
            start=self.position_from_internal(start),
            end=self.position_from_internal(end),
        )

    def end_position(self) -> lsp.Position:
        """The LSP position one past the last character of the source (a whole-document end)."""
        row = len(self._lines) - 1
        return self.position_from_point(row, len(self._line_bytes(row)))

    def point_from_position(self, position: lsp.Position) -> tuple[int, int]:
        """Convert an incoming LSP position to a 0-indexed ``(row, byte_column)`` point.

        The inverse of :meth:`position_from_point`: walk the line's characters, accumulating UTF-16
        units until the requested character offset is reached, then return the byte offset there. A
        character offset past the line's end clamps to the line's end.
        """
        row = position.line
        line = self._line_bytes(row).decode("utf-8", "replace")
        utf16 = 0
        byte_column = 0
        for char in line:
            if utf16 >= position.character:
                break
            utf16 += 1 if ord(char) <= 0xFFFF else 2
            byte_column += len(char.encode("utf-8"))
        return row, byte_column

    def prefix_before(self, position: lsp.Position) -> str:
        """The text on *position*'s line from the line start up to the cursor.

        The completion logic reads this to decide context (a trailing ``resource.`` field access, a
        ``resource.field =`` value position, or a bare identifier).
        """
        row, byte_column = self.point_from_position(position)
        return self._line_bytes(row)[:byte_column].decode("utf-8", "replace")
