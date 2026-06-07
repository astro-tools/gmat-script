"""The :func:`parse` entry point: grammar load, byte-exact re-emission (D6), error access (D7)."""

from __future__ import annotations

import pytest

from gmat_script import ErrorNode, Position, Tree, parse

# A well-formed script exercising both sections (configuration + mission sequence).
_CLEAN = "Create Spacecraft Sat\nSat.SMA = 7000\nBeginMissionSequence\nPropagate Prop(Sat);\n"

# An unterminated If — the grammar recovers with a localised ERROR node rather than raising (D7).
_MALFORMED = "BeginMissionSequence\nManeuver Burn(Sat);\nIf Sat.TA > 90\n   Propagate Prop(Sat);\n"


def test_parse_returns_a_tree() -> None:
    tree = parse(_CLEAN)
    assert isinstance(tree, Tree)
    assert tree.root_node.type == "source_file"


def test_clean_script_has_no_errors() -> None:
    tree = parse(_CLEAN)
    assert tree.has_errors is False
    assert tree.errors == []


@pytest.mark.parametrize(
    "source",
    [
        "",  # empty
        "\n\n\n",  # blank lines only — no tokens at all
        "  % leading comment\nCreate Spacecraft Sat\n",  # leading layout + comment
        "Create Spacecraft Sat   \n\n   ",  # trailing whitespace, no final newline
        "Create Spacecraft Sat\r\nSat.SMA = 7000\r\n",  # CRLF preserved (no normalisation)
        "Sat.Epoch = 19 Aug 2015\n% café au lait ☕\n",  # non-ASCII in comment/value
        _CLEAN,
        _MALFORMED,  # re-emission must hold on malformed input too
    ],
)
def test_roundtrip_is_byte_exact(source: str) -> None:
    tree = parse(source)
    assert tree.text == source
    assert tree.to_source() == source
    assert tree.to_source().encode("utf-8") == source.encode("utf-8")


def test_crlf_is_not_normalised() -> None:
    tree = parse("a = 1\r\nb = 2\r\n")
    assert "\r\n" in tree.to_source()


def test_malformed_input_does_not_raise_and_reports_errors() -> None:
    tree = parse(_MALFORMED)
    assert tree.has_errors is True
    assert tree.errors  # non-empty
    error = tree.errors[0]
    assert isinstance(error, ErrorNode)
    assert error.type == "ERROR"
    assert error.message


def test_error_positions_are_one_indexed() -> None:
    # The `@@@` garbage sits on the third line; tree-sitter reports it 0-indexed at row 2, column 0,
    # and the wrapper converts to the 1-indexed line 3, column 1 (D8).
    tree = parse("Create Spacecraft Sat\nBeginMissionSequence\n@@@\n")
    assert tree.has_errors is True
    error = tree.errors[0]
    assert isinstance(error.start, Position)
    assert (error.start.line, error.start.column) == (3, 1)
    assert error.end.line >= error.start.line


def test_errors_are_computed_once_and_cached() -> None:
    tree = parse(_CLEAN)
    assert tree.errors is tree.errors  # same object — not recomputed on each access


def test_root_node_is_exposed_for_downstream_layers() -> None:
    # The raw node is what the v0.2 typed-AST overlay and the parse CLI build on.
    tree = parse(_CLEAN)
    assert tree.root_node.type == "source_file"
    assert tree.root_node.child_count > 0
