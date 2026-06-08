"""Unit and golden tests for the canonical formatter.

The golden cases lock the exact canonical output for fixed, deliberately-messy inputs (the
``tests/data/format/*.in.*`` → ``*.out.*`` pairs, byte-pinned via ``.gitattributes``); the unit
tests pin each individual rule and the error / input-type surface.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gmat_script import Script, format, parse

_GOLDEN_DIR = Path(__file__).parent / "data" / "format"
_GOLDEN_INPUTS = sorted(_GOLDEN_DIR.glob("*.in.*"))
_GOLDEN_IDS = [path.name.replace(".in.", ".") for path in _GOLDEN_INPUTS]


def _golden_output(inp: Path) -> Path:
    return inp.with_name(inp.name.replace(".in.", ".out."))


# -- golden snapshots -----------------------------------------------------------------------------


@pytest.mark.parametrize("inp", _GOLDEN_INPUTS, ids=_GOLDEN_IDS)
def test_golden_output_matches(inp: Path) -> None:
    source = inp.read_bytes().decode("utf-8")
    expected = _golden_output(inp).read_bytes().decode("utf-8")
    assert format(source) == expected


# -- input forms and errors -----------------------------------------------------------------------


def test_accepts_str_tree_and_script_identically() -> None:
    source = "Create Spacecraft Sat\nSat.SMA=7000\n"
    expected = format(source)
    assert expected == "Create Spacecraft Sat\nSat.SMA = 7000\n"
    assert format(parse(source)) == expected
    assert format(Script.parse(source)) == expected


def test_unknown_style_raises() -> None:
    with pytest.raises(ValueError, match="unknown style"):
        format("Create Spacecraft Sat\n", style="compact")


def test_syntax_error_raises() -> None:
    tree = parse("Create Variable x\nx = = 5\n")  # malformed RHS → ERROR node
    assert tree.has_errors
    with pytest.raises(ValueError, match="syntax errors"):
        format(tree)


def test_non_script_input_raises_type_error() -> None:
    with pytest.raises(TypeError, match="expected str, Tree, or Script"):
        format(42)  # type: ignore[arg-type]


def test_empty_source_formats_to_empty_string() -> None:
    assert format("") == ""
    assert format("   \n\n") == ""


# -- whitespace and the auto-fixes ----------------------------------------------------------------


def test_drops_gmat_prefix_and_trailing_semicolon() -> None:
    assert format("Create Variable x\nGMAT x = 5 ;\n") == "Create Variable x\nx = 5\n"


def test_single_space_around_equals_and_operators() -> None:
    source = "Create Variable x\nBeginMissionSequence\nx=a+b*c\n"
    assert format(source).endswith("x = a + b * c\n")


def test_folds_line_continuation() -> None:
    source = "Create Spacecraft Sat\nSat.Tanks = {A, ...\n   B, C}\n"
    assert format(source) == "Create Spacecraft Sat\nSat.Tanks = {A, B, C}\n"


def test_trailing_whitespace_removed_including_unquoted_value() -> None:
    source = "Create Spacecraft Sat\nSat.FileName = ../a/b.txt   \n"
    assert format(source) == "Create Spacecraft Sat\nSat.FileName = ../a/b.txt\n"


# -- blank-line conventions -----------------------------------------------------------------------


def test_create_glued_to_fields_with_blank_between_resources() -> None:
    source = "Create Spacecraft A\nA.SMA = 1\n\n\nCreate Spacecraft B\nB.SMA = 2\n"
    assert format(source) == "Create Spacecraft A\nA.SMA = 1\n\nCreate Spacecraft B\nB.SMA = 2\n"


def test_blank_line_before_begin_mission_sequence_and_after() -> None:
    source = "Create Spacecraft Sat\nBeginMissionSequence\nStop\n"
    assert format(source) == "Create Spacecraft Sat\n\nBeginMissionSequence\n\nStop\n"


def test_mission_sequence_blank_lines_preserved_and_collapsed() -> None:
    source = "BeginMissionSequence\nStop\n\n\n\nStop\n"
    assert format(source) == "BeginMissionSequence\n\nStop\n\nStop\n"


def test_config_only_file_without_marker() -> None:
    source = "Create Spacecraft Sat\nSat.SMA = 7000\n"
    assert format(source) == source


def test_marker_with_empty_sequence() -> None:
    source = "Create Spacecraft Sat\nBeginMissionSequence\n"
    assert format(source) == "Create Spacecraft Sat\n\nBeginMissionSequence\n"


# -- comments -------------------------------------------------------------------------------------


def test_leading_comment_glued_to_statement() -> None:
    source = "% banner\n\nCreate Spacecraft Sat\n"
    assert format(source) == "% banner\nCreate Spacecraft Sat\n"


def test_blank_within_comment_run_preserved() -> None:
    source = "% header\n\n% banner\nCreate Spacecraft Sat\n"
    assert format(source) == "% header\n\n% banner\nCreate Spacecraft Sat\n"


def test_trailing_comment_kept_with_terminator() -> None:
    # A trailing comment only exists in the tree when a ';' terminates the statement; the formatter
    # keeps that ';' so the comment survives the next re-parse too.
    source = "Create Spacecraft Sat;  % the sat\n"
    formatted = format(source)
    assert formatted == "Create Spacecraft Sat; % the sat\n"
    assert "% the sat" in parse(formatted).text
    assert not parse(formatted).has_errors


def test_trailing_comment_then_blank_in_sequence() -> None:
    source = "BeginMissionSequence\nStop;  % first\n\nStop\n"
    assert format(source) == "BeginMissionSequence\n\nStop; % first\n\nStop\n"


def test_orphan_trailing_comments_at_end_of_file() -> None:
    source = "Create Spacecraft Sat\nSat.SMA = 1\n% trailing note\n"
    assert format(source) == "Create Spacecraft Sat\nSat.SMA = 1\n% trailing note\n"


def test_comment_inside_a_value_keeps_statement_verbatim() -> None:
    source = "Create Spacecraft Sat\nSat.Tanks = {A, % primary\n   B}\n"
    formatted = format(source)
    # folding would eat the comment, so the statement is re-emitted verbatim and round-trips
    assert "% primary" in parse(formatted).text
    assert not parse(formatted).has_errors
    assert format(formatted) == formatted


# -- blocks ---------------------------------------------------------------------------------------


def test_block_body_indented_four_spaces() -> None:
    source = "BeginMissionSequence\nIf x > 1\nStop\nEndIf\n"
    assert format(source) == "BeginMissionSequence\n\nIf x > 1\n    Stop\nEndIf\n"


def test_if_else_indentation() -> None:
    source = "BeginMissionSequence\nIf x > 1\nStop\nElse\nStop\nEndIf\n"
    expected = "BeginMissionSequence\n\nIf x > 1\n    Stop\nElse\n    Stop\nEndIf\n"
    assert format(source) == expected


def test_nested_blocks_indent_compounds() -> None:
    source = "BeginMissionSequence\nFor i = 1:3\nIf x > 1\nStop\nEndIf\nEndFor\n"
    expected = (
        "BeginMissionSequence\n\nFor i = 1:3\n    If x > 1\n        Stop\n    EndIf\nEndFor\n"
    )
    assert format(source) == expected


def test_trailing_comment_on_block_header() -> None:
    source = "BeginMissionSequence\nIf x > 1;  % guard\nStop\nEndIf\n"
    formatted = format(source)
    assert "If x > 1; % guard" in formatted
    assert "% guard" in parse(formatted).text


def test_trailing_comment_on_else() -> None:
    source = "BeginMissionSequence\nIf x > 1\nStop\nElse;  % otherwise\nStop\nEndIf\n"
    formatted = format(source)
    assert "Else; % otherwise" in formatted
    assert "% otherwise" in parse(formatted).text


def test_for_range_with_step() -> None:
    source = "BeginMissionSequence\nFor i = 1 : 2 : 10\nStop\nEndFor\n"
    assert "For i = 1:2:10\n" in format(source)


def test_function_definition_without_parameter_list() -> None:
    # D10: a .gmf header may carry no parameter list (best-effort).
    source = "function [s] = GetStates\nBeginMissionSequence\nStop\n"
    assert format(source).startswith("function [s] = GetStates\n")


# -- BeginScript (opaque body) --------------------------------------------------------------------


def test_begin_script_body_preserved_verbatim() -> None:
    source = "BeginMissionSequence\nBeginScript 'init'\n   x = 1;\n   y = 2;\nEndScript\n"
    formatted = format(source)
    assert "BeginScript 'init'" in formatted
    assert "   x = 1;" in formatted  # body indentation untouched
    assert "   y = 2;" in formatted
    assert format(formatted) == formatted


# -- newline preservation -------------------------------------------------------------------------


def test_crlf_source_emits_crlf() -> None:
    source = "Create Spacecraft Sat\r\nSat.SMA=7000\r\n"
    formatted = format(source)
    assert formatted == "Create Spacecraft Sat\r\nSat.SMA = 7000\r\n"
    assert "\r\r" not in formatted


def test_lf_source_emits_lf() -> None:
    formatted = format("Create Spacecraft Sat\nSat.SMA=7000\n")
    assert "\r" not in formatted
