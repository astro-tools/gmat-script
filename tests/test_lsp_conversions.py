"""Tests for the LSP position conversions (:mod:`gmat_script.lsp.conversions`).

The conversions are the one place byte offsets, internal 1-indexed positions, and LSP 0-indexed
UTF-16 positions meet, so they are exercised directly — including the multi-byte and astral-plane
cases where a byte column and a UTF-16 character offset diverge, and the CRLF / out-of-range edges
where a naive implementation would crash or miscount.
"""

from __future__ import annotations

import pytest
from lsprotocol import types as lsp

from gmat_script.lsp.conversions import LineIndex, _utf16_units
from gmat_script.parser import Position, parse

# A line mixing a 2-byte/1-unit char (é), a 4-byte/2-unit astral char (😀), and an ASCII char.
_MIXED = "é😀x"


@pytest.mark.parametrize(
    ("text", "units"),
    [("", 0), ("abc", 3), ("é", 1), ("😀", 2), (_MIXED, 4)],
)
def test_utf16_units(text: str, units: int) -> None:
    assert _utf16_units(text) == units


def test_position_from_point_ascii() -> None:
    index = LineIndex("Create Spacecraft Sat\nSat.SMA = 7000\n")
    assert index.position_from_point(1, 4) == lsp.Position(line=1, character=4)


def test_position_from_point_multibyte_and_astral() -> None:
    index = LineIndex(_MIXED)
    # Byte columns fall on character boundaries: after é (2 bytes), after é+😀 (6 bytes), after x.
    assert index.position_from_point(0, 0) == lsp.Position(line=0, character=0)
    assert index.position_from_point(0, 2) == lsp.Position(line=0, character=1)
    assert index.position_from_point(0, 6) == lsp.Position(line=0, character=3)
    assert index.position_from_point(0, 7) == lsp.Position(line=0, character=4)


def test_position_from_point_out_of_range_row_clamps() -> None:
    index = LineIndex("one line\n")
    # A row past the end yields an empty line, character 0 — never an IndexError.
    assert index.position_from_point(99, 5) == lsp.Position(line=99, character=0)


def test_position_from_internal_is_one_indexed() -> None:
    index = LineIndex("abcdef\n")
    # Internal Position is 1-indexed line + 1-indexed byte column; LSP is 0-indexed.
    assert index.position_from_internal(Position(line=1, column=1)) == lsp.Position(0, 0)
    assert index.position_from_internal(Position(line=1, column=4)) == lsp.Position(0, 3)


def test_crlf_line_split_keeps_columns_aligned() -> None:
    index = LineIndex("ab\r\ncd\r\n")
    # tree-sitter keeps the trailing '\r' in the line, so a column past 'b' counts it.
    assert index.position_from_point(0, 1) == lsp.Position(line=0, character=1)
    assert index.position_from_point(1, 2) == lsp.Position(line=1, character=2)


def test_range_of_node_spans_the_token() -> None:
    source = "Create Spacecraft Sat\n"
    index = LineIndex(source)
    sat = parse(source).root_node.descendant_for_point_range((0, 18), (0, 18))
    assert sat is not None and sat.type == "identifier"
    found = index.range_of_node(sat)
    assert found == lsp.Range(start=lsp.Position(0, 18), end=lsp.Position(0, 21))


def test_range_from_internal() -> None:
    index = LineIndex("abcdef\n")
    found = index.range_from_internal(Position(1, 2), Position(1, 5))
    assert found == lsp.Range(start=lsp.Position(0, 1), end=lsp.Position(0, 4))


def test_end_position() -> None:
    assert LineIndex("abc\ndef").end_position() == lsp.Position(line=1, character=3)
    # A trailing newline makes the final (empty) line the document end.
    assert LineIndex("abc\n").end_position() == lsp.Position(line=1, character=0)


@pytest.mark.parametrize("character", [0, 1, 3, 4])
def test_point_from_position_round_trips(character: int) -> None:
    index = LineIndex(_MIXED)
    row, byte_column = index.point_from_position(lsp.Position(line=0, character=character))
    assert row == 0
    # Converting the resulting point back yields the original character offset.
    assert index.position_from_point(0, byte_column).character == character


def test_point_from_position_clamps_past_line_end() -> None:
    index = LineIndex("abc\n")
    # A character offset beyond the line clamps to the line's byte length.
    assert index.point_from_position(lsp.Position(line=0, character=99)) == (0, 3)


def test_prefix_before() -> None:
    index = LineIndex("Create Spacecraft Sat\nSat.SMA = 7000\n")
    assert index.prefix_before(lsp.Position(line=1, character=4)) == "Sat."
    assert index.prefix_before(lsp.Position(line=1, character=0)) == ""
