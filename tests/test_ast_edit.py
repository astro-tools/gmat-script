"""The mutation API: literal emission, field / resource / command edits, and the lossless guarantee.

Unit coverage of :mod:`gmat_script.ast.literals` and :mod:`gmat_script.ast.edit` plus the mutators
on :class:`~gmat_script.Script`, on small hand-written scripts. The corpus-scale "untouched bytes
stay byte-for-byte" check is :func:`test_edit_is_localised_on_corpus` at the end.
"""

from __future__ import annotations

import difflib
from pathlib import Path

import pytest

from gmat_script import MutationError, ObjectRef, RawValue, Script, parse
from gmat_script.ast import Value, coerce_value, emit_value
from gmat_script.ast.edit import _Edit, detect_newline, line_span, splice

# --- literal emission -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (7000, "7000"),
        (0, "0"),
        (-90000, "-90000"),
        (True, "true"),
        (False, "false"),
        (850.0, "850.0"),
        (0.125, "0.125"),
        (1e70, "1e+70"),
        ("hello world", "'hello world'"),
        ("", "''"),
        (ObjectRef("Earth"), "Earth"),
        (ObjectRef("Sat.SMA"), "Sat.SMA"),
        (RawValue("sqrt(x)"), "sqrt(x)"),
        ([ObjectRef("Earth"), ObjectRef("Luna")], "{Earth, Luna}"),
        ([], "{}"),
        ([ObjectRef("Sun"), [ObjectRef("Earth")]], "{Sun, {Earth}}"),  # nested → nested braces
        ([[1, 2], [3, 4]], "[1 2; 3 4]"),  # all-list → matrix
        ([[1.0, 0.0], [0.0, 1.0]], "[1.0 0.0; 0.0 1.0]"),
    ],
)
def test_emit_value(value: Value, text: str) -> None:
    assert emit_value(value) == text


def test_emit_value_round_trips_through_the_parser() -> None:
    # Emitting a value then parsing it back coerces to the same value (unambiguous forms).
    values: tuple[Value, ...] = (
        7000,
        850.0,
        True,
        "a date",
        ObjectRef("Earth"),
        [ObjectRef("A"), ObjectRef("B")],
    )
    for value in values:
        assignment = parse(f"v = {emit_value(value)}\n").root_node.named_children[0]
        right = assignment.child_by_field_name("right")
        assert right is not None
        assert coerce_value(right) == value


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_emit_value_rejects_non_finite_floats(value: float) -> None:
    with pytest.raises(ValueError, match="non-finite"):
        emit_value(value)


@pytest.mark.parametrize("value", ["it's", "two\nlines", "carriage\rreturn"])
def test_emit_value_rejects_unrepresentable_strings(value: str) -> None:
    with pytest.raises(ValueError, match="single quote or a newline"):
        emit_value(value)


def test_emit_value_rejects_unknown_type() -> None:
    with pytest.raises(TypeError, match="cannot emit"):
        emit_value({"not": "a value"})  # type: ignore[arg-type]


# --- the splice engine ----------------------------------------------------------------------------


def test_splice_applies_disjoint_edits() -> None:
    source = b"abcdef"
    result = splice(source, [_Edit(0, 1, b"X"), _Edit(4, 6, b"YZ")])
    assert result == b"Xbcd" + b"YZ"


def test_splice_rejects_overlapping_edits() -> None:
    with pytest.raises(MutationError, match="overlapping"):
        splice(b"abcdef", [_Edit(0, 3, b""), _Edit(2, 4, b"")])


def test_splice_allows_touching_edits() -> None:
    assert splice(b"abcd", [_Edit(0, 2, b"X"), _Edit(2, 4, b"Y")]) == b"XY"


@pytest.mark.parametrize(
    ("source", "start", "end", "expected"),
    [
        (b"one\ntwo\nthree\n", 4, 7, (4, 8)),  # the middle line, trailing \n included
        (b"one\ntwo\nthree\n", 0, 3, (0, 4)),  # the first line
        (b"one\ntwo\nlast", 8, 12, (8, 12)),  # last line, no trailing newline → end of source
        (b"a\r\nb\r\n", 0, 1, (0, 3)),  # CRLF: the \r stays with the line, \n ends the span
    ],
)
def test_line_span(source: bytes, start: int, end: int, expected: tuple[int, int]) -> None:
    assert line_span(source, start, end) == expected


def test_detect_newline() -> None:
    assert detect_newline("a\r\nb\n") == "\r\n"  # any CRLF wins
    assert detect_newline("a\nb\n") == "\n"
    assert detect_newline("no newline") == "\n"


# --- field edits ----------------------------------------------------------------------------------

_CONFIG = """\
Create Spacecraft Sat
Create Variable x y z
GMAT Sat.SMA = 7000
Sat.DryMass = 850.0
Sat.SMA = 8000
BeginMissionSequence
Propagate DefaultProp(Sat)
"""


def test_set_existing_field_rewrites_in_place() -> None:
    script = Script.parse(_CONFIG)
    script.set_field("Sat", "SMA", 9000)
    assert script.resources["Sat"]["SMA"] == 9000
    # Last-winning assignment edited; the earlier `Sat.SMA = 7000` and every other line untouched.
    assert "GMAT Sat.SMA = 7000\n" in script.to_source()
    assert "Sat.SMA = 9000\n" in script.to_source()
    assert "Sat.SMA = 8000" not in script.to_source()
    assert not script.has_errors


def test_set_new_field_appends_after_last_assignment() -> None:
    script = Script.parse(_CONFIG)
    script.set_field("Sat", "ECC", 0.01)
    assert script.resources["Sat"]["ECC"] == 0.01
    lines = script.to_source().splitlines()
    # Appended right after the resource's last existing assignment, still in the config section.
    assert lines[lines.index("Sat.SMA = 8000") + 1] == "Sat.ECC = 0.01"
    assert lines.index("Sat.ECC = 0.01") < lines.index("BeginMissionSequence")


def test_set_new_field_on_resource_without_assignments_appends_after_create() -> None:
    script = Script.parse("Create Spacecraft Sat\nBeginMissionSequence\nStop\n")
    script.set_field("Sat", "SMA", 7000)
    lines = script.to_source().splitlines()
    assert lines[lines.index("Create Spacecraft Sat") + 1] == "Sat.SMA = 7000"


def test_set_field_via_operator_subscript() -> None:
    script = Script.parse(_CONFIG)
    script.spacecraft["Sat"]["SMA"] = 7000
    script.spacecraft["Sat"]["Tanks"] = [ObjectRef("ChemicalTank1")]
    assert script.resources["Sat"]["SMA"] == 7000
    assert script.resources["Sat"]["Tanks"] == [ObjectRef("ChemicalTank1")]
    assert "Sat.Tanks = {ChemicalTank1}\n" in script.to_source()


def test_mutablemapping_helpers_route_through_edits() -> None:
    script = Script.parse(_CONFIG)
    sat = script.resources["Sat"]
    sat.update({"SMA": 6800, "INC": 28.5})
    assert sat["SMA"] == 6800
    assert sat["INC"] == 28.5
    assert sat.pop("DryMass") == 850.0
    assert "DryMass" not in sat


def test_delete_field_removes_every_assignment_to_it() -> None:
    script = Script.parse(_CONFIG)
    del script.spacecraft["Sat"]["SMA"]
    assert "SMA" not in script.resources["Sat"]
    text = script.to_source()
    assert "Sat.SMA" not in text  # both `= 7000` and `= 8000` lines gone
    assert "Sat.DryMass = 850.0\n" in text  # the untouched field stays
    assert not script.has_errors


def test_delete_missing_field_raises_keyerror() -> None:
    script = Script.parse(_CONFIG)
    with pytest.raises(KeyError):
        del script.spacecraft["Sat"]["NoSuchField"]


def test_set_field_on_unknown_resource_raises_keyerror() -> None:
    script = Script.parse(_CONFIG)
    with pytest.raises(KeyError):
        script.set_field("Ghost", "SMA", 1)


def test_delete_field_leaves_non_field_writes_to_the_resource() -> None:
    script = Script.parse(
        "Create Array A[2, 2]\nA.Size = 3\nA(1, 1) = 5\nBeginMissionSequence\nStop\n"
    )
    del script.resources["A"]["Size"]
    text = script.to_source()
    assert "A.Size" not in text
    assert "A(1, 1) = 5\n" in text  # the array-element write is not a field — left untouched


def test_resource_to_source_and_byte_range_track_the_live_declaration() -> None:
    script = Script.parse(_CONFIG)
    sat = script.resources["Sat"]
    assert sat.to_source() == "Create Spacecraft Sat"
    start, end = sat.byte_range
    assert script.to_source().encode("utf-8")[start:end] == b"Create Spacecraft Sat"


def test_held_resource_handle_is_a_live_cursor() -> None:
    script = Script.parse(_CONFIG)
    sat = script.resources["Sat"]
    script.set_field("Sat", "SMA", 1234)
    assert sat["SMA"] == 1234  # the handle reflects an edit made after it was taken


# --- resource edits -------------------------------------------------------------------------------


def test_add_resource_with_fields() -> None:
    script = Script.parse(_CONFIG)
    script.add_resource("ImpulsiveBurn", "Burn", {"Element1": 0.5, "Axes": ObjectRef("VNB")})
    assert script.resources["Burn"].type == "ImpulsiveBurn"
    assert script.resources["Burn"]["Element1"] == 0.5
    lines = script.to_source().splitlines()
    assert "Create ImpulsiveBurn Burn" in lines
    assert lines.index("Create ImpulsiveBurn Burn") < lines.index("BeginMissionSequence")


def test_add_resource_without_marker_appends_at_eof() -> None:
    script = Script.parse("Create Spacecraft Sat\n")
    script.add_resource("ForceModel", "FM")
    assert "FM" in script.resources
    assert script.to_source().endswith("Create ForceModel FM\n")


def test_add_duplicate_resource_raises() -> None:
    script = Script.parse(_CONFIG)
    with pytest.raises(MutationError, match="already exists"):
        script.add_resource("Spacecraft", "Sat")


def test_remove_single_name_resource_drops_create_and_assignments() -> None:
    script = Script.parse(_CONFIG)
    script.remove_resource("Sat")
    assert "Sat" not in script.resources
    text = script.to_source()
    assert "Create Spacecraft Sat" not in text
    assert "Sat.SMA" not in text and "Sat.DryMass" not in text
    assert "Create Variable x y z\n" in text  # the other declaration is untouched


def test_remove_name_from_multi_name_declaration() -> None:
    script = Script.parse(_CONFIG)
    script.remove_resource("y")  # middle name of `Create Variable x y z`
    assert set(script.resources) == {"Sat", "x", "z"}
    assert "Create Variable x z\n" in script.to_source()


def test_remove_first_name_from_multi_name_declaration() -> None:
    script = Script.parse(_CONFIG)
    script.remove_resource("x")
    assert "Create Variable y z\n" in script.to_source()


def test_rename_resource_rewrites_references_and_declaration() -> None:
    script = Script.parse(_CONFIG)
    script.rename_resource("Sat", "MainSat")
    text = script.to_source()
    assert "Create Spacecraft MainSat\n" in text
    assert "MainSat.SMA = 7000" in text  # GMAT keyword preserved, root rewritten
    assert "Propagate DefaultProp(MainSat)\n" in text  # command operand rewritten
    assert "Sat" not in text.replace("MainSat", "")  # no stray `Sat` left


def test_rename_resource_without_references_changes_only_the_declaration() -> None:
    script = Script.parse(_CONFIG)
    script.rename_resource("Sat", "MainSat", update_references=False)
    text = script.to_source()
    assert "Create Spacecraft MainSat\n" in text
    assert "Sat.SMA = 7000" in text  # the assignment reference is left pointing at the old name
    assert "Propagate DefaultProp(Sat)\n" in text


def test_rename_does_not_touch_a_coincidental_field_name() -> None:
    script = Script.parse(
        "Create Spacecraft Sat\nCreate Spacecraft Other\n"
        "Other.Sat = 1\nBeginMissionSequence\nStop\n"
    )
    script.rename_resource("Sat", "Renamed")
    text = script.to_source()
    assert "Create Spacecraft Renamed\n" in text
    assert "Other.Sat = 1\n" in text  # `Sat` here is a field name on Other, not the object


def test_rename_skips_the_create_type_token() -> None:
    # A resource whose name equals a GMAT type: only the name token is rewritten, not the types.
    script = Script.parse(
        "Create Spacecraft Spacecraft\nCreate Spacecraft Other\nBeginMissionSequence\nStop\n"
    )
    script.rename_resource("Spacecraft", "Sc")
    text = script.to_source()
    assert "Create Spacecraft Sc\n" in text  # the second token (name) changed
    assert "Create Spacecraft Other\n" in text  # the other declaration's type token is intact
    assert set(script.resources) == {"Sc", "Other"}


def test_rename_to_existing_name_raises() -> None:
    script = Script.parse(_CONFIG)
    with pytest.raises(MutationError, match="already exists"):
        script.rename_resource("Sat", "x")


def test_resource_handle_invalidates_after_removal() -> None:
    script = Script.parse(_CONFIG)
    sat = script.resources["Sat"]
    script.remove_resource("Sat")
    with pytest.raises(KeyError):
        _ = sat["SMA"]


# --- command edits --------------------------------------------------------------------------------

_MISSION = """\
Create Spacecraft Sat
BeginMissionSequence
Propagate DefaultProp(Sat)
Maneuver Burn(Sat)
Report rf Sat.X
Stop
"""


def _keywords(script: Script) -> list[str]:
    return [command.keyword for command in script.mission_sequence]


def test_insert_command_before_index() -> None:
    script = Script.parse(_MISSION)
    script.insert_command(0, "Toggle rf On")
    assert _keywords(script) == ["Toggle", "Propagate", "Maneuver", "Report", "Stop"]


def test_insert_command_at_end() -> None:
    script = Script.parse(_MISSION)
    script.insert_command(len(script.mission_sequence), "Toggle rf Off")
    assert _keywords(script)[-1] == "Toggle"


def test_insert_command_into_empty_sequence() -> None:
    script = Script.parse("Create Spacecraft Sat\nBeginMissionSequence\n")
    script.insert_command(0, "Stop")
    assert _keywords(script) == ["Stop"]


def test_insert_command_without_a_mission_sequence_raises() -> None:
    script = Script.parse("Create Spacecraft Sat\n")
    with pytest.raises(MutationError, match="no mission sequence"):
        script.insert_command(0, "Stop")


def test_insert_command_out_of_range_raises() -> None:
    script = Script.parse(_MISSION)
    with pytest.raises(IndexError):
        script.insert_command(99, "Stop")


def test_remove_command() -> None:
    script = Script.parse(_MISSION)
    script.remove_command(1)  # the Maneuver
    assert _keywords(script) == ["Propagate", "Report", "Stop"]


def test_remove_command_out_of_range_raises() -> None:
    script = Script.parse(_MISSION)
    with pytest.raises(IndexError):
        script.remove_command(99)


def test_replace_command_edits_operands_in_place() -> None:
    script = Script.parse(_MISSION)
    script.replace_command(0, "Propagate BackProp DefaultProp(Sat)")
    assert "Propagate BackProp DefaultProp(Sat)\n" in script.to_source()
    assert _keywords(script) == ["Propagate", "Maneuver", "Report", "Stop"]


def test_replace_command_out_of_range_raises() -> None:
    script = Script.parse(_MISSION)
    with pytest.raises(IndexError):
        script.replace_command(99, "Stop")


@pytest.mark.parametrize(
    ("frm", "to", "expected"),
    [
        (0, 2, ["Maneuver", "Report", "Propagate", "Stop"]),
        (3, 0, ["Stop", "Propagate", "Maneuver", "Report"]),
        (0, 3, ["Maneuver", "Report", "Stop", "Propagate"]),
        (3, 1, ["Propagate", "Stop", "Maneuver", "Report"]),
    ],
)
def test_move_command(frm: int, to: int, expected: list[str]) -> None:
    script = Script.parse(_MISSION)
    script.move_command(frm, to)
    assert _keywords(script) == expected


def test_move_command_to_same_index_is_a_noop() -> None:
    script = Script.parse(_MISSION)
    before = script.to_source()
    script.move_command(1, 1)
    assert script.to_source() == before


def test_move_command_single_element_is_a_noop() -> None:
    script = Script.parse("Create Spacecraft Sat\nBeginMissionSequence\nStop\n")
    before = script.to_source()
    script.move_command(0, 0)
    assert script.to_source() == before


def test_move_command_out_of_range_raises() -> None:
    script = Script.parse(_MISSION)
    with pytest.raises(IndexError):
        script.move_command(0, 99)
    with pytest.raises(IndexError):
        script.move_command(99, 0)


# --- the validation guard -------------------------------------------------------------------------


def test_corrupting_edit_raises_and_leaves_source_unchanged() -> None:
    script = Script.parse(_MISSION)
    before = script.to_source()
    with pytest.raises(MutationError, match="unparseable"):
        script.replace_command(0, "Sat.X = ")  # an assignment with no right-hand side
    assert script.to_source() == before
    assert not script.has_errors


def test_corrupting_insert_raises() -> None:
    script = Script.parse(_MISSION)
    with pytest.raises(MutationError, match="unparseable"):
        script.insert_command(0, "If x > 1")  # opens a block that is never closed


def test_editing_a_script_with_syntax_errors_raises() -> None:
    script = Script.parse("Create Spacecraft Sat\nSat.SMA = 8000\nIf x > 1\n")
    assert script.has_errors
    with pytest.raises(MutationError, match="syntax errors"):
        script.set_field("Sat", "SMA", 7000)


def test_apply_with_no_edits_is_a_noop() -> None:
    script = Script.parse(_CONFIG)
    before = script.to_source()
    script._apply([])
    assert script.to_source() == before


def test_mutators_chain() -> None:
    script = Script.parse(_CONFIG)
    result = script.set_field("Sat", "SMA", 7000).rename_resource("Sat", "S")
    assert result is script
    assert "S" in script.resources


def test_tree_and_byte_range_track_edits() -> None:
    script = Script.parse(_CONFIG)
    script.set_field("Sat", "SMA", 12345)
    assert script.tree is script._tree
    assert script.byte_range == (0, len(script.to_source().encode("utf-8")))


# --- corpus-scale lossless guarantee --------------------------------------------------------------

_CORPUS_DIR = Path(__file__).parent / "data" / "corpus"
_CORPUS_FIXTURES = sorted(_CORPUS_DIR.rglob("*.script"))[:12]
_CORPUS_IDS = [str(path.relative_to(_CORPUS_DIR)) for path in _CORPUS_FIXTURES]


@pytest.mark.corpus
@pytest.mark.parametrize("path", _CORPUS_FIXTURES, ids=_CORPUS_IDS)
def test_edit_is_localised_on_corpus(path: Path) -> None:
    """Appending one field changes exactly one line; every other byte is preserved."""
    original = path.read_text(encoding="utf-8")
    script = Script.parse(original)
    if script.has_errors or not script.resources:
        pytest.skip("no clean resource to probe")
    name = next(iter(script.resources))
    script.set_field(name, "GmatScriptEditProbe", 1)
    edited = script.to_source()
    assert not script.has_errors
    assert script.resources[name]["GmatScriptEditProbe"] == 1

    diff = list(difflib.ndiff(original.splitlines(keepends=True), edited.splitlines(keepends=True)))
    added = [line[2:] for line in diff if line.startswith("+ ")]
    removed = [line for line in diff if line.startswith("- ")]
    assert removed == []  # nothing deleted or changed — only an insertion
    assert len(added) == 1
    assert added[0].strip() == f"{name}.GmatScriptEditProbe = 1"
