"""The typed AST overlay (issue #12): value coercion, resources, and typed mission commands.

Unit coverage of :mod:`gmat_script.ast` on small, hand-written scripts — the broad corpus check
lives in ``test_ast_corpus.py``.
"""

from __future__ import annotations

import pytest

from gmat_script import Array, ObjectRef, RawValue, Script, parse
from gmat_script.ast import (
    Assignment,
    Command,
    ForStatement,
    FunctionCall,
    GenericCommand,
    IfStatement,
    OptimizeStatement,
    Resource,
    ScriptBlock,
    TargetStatement,
    Value,
    WhileStatement,
    build_command,
    coerce_value,
    split_reference,
)

# --- value coercion -------------------------------------------------------------------------------


def _coerce_rhs(rhs: str) -> Value:
    """Parse ``v = <rhs>`` and coerce the right-hand side value node."""
    assignment = parse(f"v = {rhs}\n").root_node.named_children[0]
    right = assignment.child_by_field_name("right")
    assert right is not None
    return coerce_value(right)


@pytest.mark.parametrize(
    ("rhs", "expected"),
    [
        ("7000", 7000),
        ("0", 0),
        ("850.0", 850.0),
        ("1.25e-1", 0.125),
        ("1e+070", 1e70),  # zero-padded exponent (D3)
        (".5", 0.5),
        ("'hello world'", "hello world"),
        ("true", True),
        ("false", False),
        ("Earth", ObjectRef("Earth")),
        ("Sat.SMA", ObjectRef("Sat.SMA")),
        ("FM.GravityField.Earth.PotentialFile", ObjectRef("FM.GravityField.Earth.PotentialFile")),
        ("-90000", -90000),
        ("+5", 5),
        ("-3.5", -3.5),
        ("{Earth, Luna}", [ObjectRef("Earth"), ObjectRef("Luna")]),
        ("{}", []),
        ("{Sun, {Earth, Luna}}", [ObjectRef("Sun"), [ObjectRef("Earth"), ObjectRef("Luna")]]),
        ("{{1, 2}, {3, 4}}", [[1, 2], [3, 4]]),  # a brace-list of brace-lists is nested lists
        ("[1 2 3]", Array((1, 2, 3))),  # a [...] array is an Array, distinct from a {...} list
        ("[]", Array(())),
        ("[-1 2; 3 -4]", Array((Array((-1, 2)), Array((3, -4))))),  # 2-D matrix, signed elements
    ],
)
def test_coerce_value_structural(rhs: str, expected: Value) -> None:
    assert _coerce_rhs(rhs) == expected


@pytest.mark.parametrize(
    ("rhs", "raw"),
    [
        ("19 Aug 2015 00:00:00.000", "19 Aug 2015 00:00:00.000"),  # unquoted date (`:` signature)
        ("../data/JGM2.cof", "../data/JGM2.cof"),  # unquoted path (`/` signature)
        ("sqrt(x)", "sqrt(x)"),  # call expression
        ("(a + b)", "(a + b)"),  # parenthesised
        ("a + b", "a + b"),  # binary expression
        ("-Element1", "-Element1"),  # unary on a non-number
        ("-true", "-true"),  # unary on a bool — stays raw, never an int
        ("''", "''"),  # the doubled-quote artifact is an unquoted value, not an empty string (D13)
    ],
)
def test_coerce_value_raw_fallback(rhs: str, raw: str) -> None:
    value = _coerce_rhs(rhs)
    assert isinstance(value, RawValue)
    assert value.text == raw


def test_coerce_value_number_types() -> None:
    assert isinstance(_coerce_rhs("7000"), int)
    assert isinstance(_coerce_rhs("7000.0"), float)


# --- split_reference ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ref", "root", "segments"),
    [
        ("Sat", "Sat", []),
        ("Sat.SMA", "Sat", ["SMA"]),
        ("FM.GravityField.Earth.PotentialFile", "FM", ["GravityField", "Earth", "PotentialFile"]),
        ("A(1, 1)", "A", []),  # array-indexed target — root only, no field path
    ],
)
def test_split_reference(ref: str, root: str, segments: list[str]) -> None:
    left = parse(f"{ref} = 1\n").root_node.named_children[0].child_by_field_name("left")
    assert left is not None
    assert split_reference(left) == (root, segments)


# --- resources ------------------------------------------------------------------------------------

_CONFIG = """\
Create Spacecraft Sat
Create ForceModel FM
Create Variable x y z
Create Array A[3, 3]
GMAT Sat.SMA = 7000
Sat.DryMass = 850.0
Sat.SMA = 8000
FM.GravityField.Earth.PotentialFile = '../data/JGM2.cof'
Sat.Tanks = {ChemicalTank1}
x = 5
A(1, 1) = 4
"""


def test_resources_by_name_and_type() -> None:
    script = Script.parse(_CONFIG)
    assert set(script.resources) == {"Sat", "FM", "x", "y", "z", "A"}
    assert set(script.resources_by_type) == {"Spacecraft", "ForceModel", "Variable", "Array"}
    assert script.resources["Sat"] is script.resources_by_type["Spacecraft"]["Sat"]


def test_duplicate_name_under_one_type_is_listed_once() -> None:
    # Two declarations of the same name (the linter's problem, not the grammar's) collapse to one
    # entry in the by-type index rather than appearing twice.
    source = "Create Spacecraft Sat\nCreate Spacecraft Sat\nBeginMissionSequence\nStop\n"
    script = Script.parse(source)
    assert list(script.resources_by_type["Spacecraft"]) == ["Sat"]


def test_type_sugar_attribute() -> None:
    script = Script.parse(_CONFIG)
    assert list(script.spacecraft) == ["Sat"]
    assert script.spacecraft["Sat"]["SMA"] == 8000  # last write wins
    assert list(script.variable) == ["x", "y", "z"]


def test_type_sugar_unknown_and_private_raise() -> None:
    script = Script.parse(_CONFIG)
    with pytest.raises(AttributeError):
        _ = script.groundstation  # a type not present in this script
    with pytest.raises(AttributeError):
        _ = script._not_a_type  # private names never resolve as type sugar


def test_resource_field_access() -> None:
    sat = Script.parse(_CONFIG).resources["Sat"]
    assert sat.name == "Sat"
    assert sat.type == "Spacecraft"
    assert sat["SMA"] == 8000
    assert sat["DryMass"] == 850.0
    assert sat["Tanks"] == [ObjectRef("ChemicalTank1")]
    assert "SMA" in sat
    assert sat.get("missing") is None
    assert dict(sat.items()) == {
        "SMA": 8000,
        "DryMass": 850.0,
        "Tanks": [ObjectRef("ChemicalTank1")],
    }
    with pytest.raises(KeyError):
        _ = sat["NoSuchField"]


def test_nested_field_path_is_the_dotted_suffix() -> None:
    fm = Script.parse(_CONFIG).resources["FM"]
    assert fm["GravityField.Earth.PotentialFile"] == "../data/JGM2.cof"


def test_bare_name_and_array_index_writes_are_not_fields() -> None:
    script = Script.parse(_CONFIG)
    x = script.resources["x"]
    assert len(x) == 0  # `x = 5` is a whole-object write, not a field
    assert len(x.assignments) == 1
    a = script.resources["A"]
    assert len(a) == 0  # `A(1, 1) = 4` is an element write, not a field
    assert len(a.assignments) == 1


def test_resource_declaration_and_array_dimensions() -> None:
    script = Script.parse(_CONFIG)
    a = script.resources["A"]
    assert a.declaration is a.node
    assert a.declaration.type == "create_command"
    assert a.array_dimensions == (3, 3)
    assert script.resources["Sat"].array_dimensions is None


def test_multi_name_declaration_shares_one_create() -> None:
    script = Script.parse(_CONFIG)
    assert script.resources["x"].declaration is script.resources["y"].declaration
    assert repr(script.resources["x"]).startswith("Resource('x'")


def test_assignment_to_undeclared_resource_is_orphaned() -> None:
    # `Ghost.X = 1` names no Create'd resource — it attaches to nothing and does not crash building.
    script = Script.parse("Create Spacecraft Sat\nGhost.X = 1\n")
    assert "Ghost" not in script.resources
    assert len(script.resources["Sat"]) == 0


# --- mission sequence -----------------------------------------------------------------------------

_MISSION = """\
Create Spacecraft Sat
BeginMissionSequence
Propagate 'one orbit' DefaultProp(Sat) {Sat.ElapsedSecs = 8640}
GMAT 'set ta' Sat.TA = 90
[V2, Log] = Python.IOD.ThreePositionIOD(r1, r2)
[] = RaiseApogee(burnSize)
[now] = timer
Target DC {SolveMode = Solve}
   Vary DC(Burn.V = 0.5)
   Achieve DC(Sat.SMA = 8000)
EndTarget
Optimize VF13
   Minimize cost
EndOptimize
If Sat.TA > 90
   Stop
Else
   Report rf Sat.X
EndIf
For k = 1:2:10
   Maneuver Burn(Sat)
EndFor
While Sat.ElapsedDays < 1
   Propagate DefaultProp(Sat)
EndWhile
BeginScript
   x = 1;
EndScript
"""


def _sequence() -> tuple[Command, ...]:
    return Script.parse(_MISSION).mission_sequence


def test_mission_sequence_command_types() -> None:
    types = [type(command).__name__ for command in _sequence()]
    assert types == [
        "GenericCommand",
        "Assignment",
        "FunctionCall",
        "FunctionCall",
        "FunctionCall",
        "TargetStatement",
        "OptimizeStatement",
        "IfStatement",
        "ForStatement",
        "WhileStatement",
        "ScriptBlock",
    ]


def test_generic_command_name_label_arguments() -> None:
    propagate = _sequence()[0]
    assert isinstance(propagate, GenericCommand)
    assert propagate.name == "Propagate"
    assert propagate.keyword == "Propagate"
    assert propagate.label == "one orbit"
    # operands: the propagator call and the brace option block (raw — they compute / configure).
    assert propagate.arguments == (
        RawValue("DefaultProp(Sat)"),
        [RawValue("Sat.ElapsedSecs = 8640")],
    )


def test_assignment_command() -> None:
    assignment = _sequence()[1]
    assert isinstance(assignment, Assignment)
    assert assignment.target == ObjectRef("Sat.TA")
    assert assignment.value == 90
    assert assignment.label == "set ta"


def test_function_call_variants() -> None:
    dotted, empty_outputs, no_parens = _sequence()[2], _sequence()[3], _sequence()[4]
    assert isinstance(dotted, FunctionCall)
    assert dotted.outputs == ("V2", "Log")
    assert dotted.function == "Python.IOD.ThreePositionIOD"
    assert dotted.arguments == (ObjectRef("r1"), ObjectRef("r2"))
    assert isinstance(empty_outputs, FunctionCall)
    assert empty_outputs.outputs == ()
    assert empty_outputs.function == "RaiseApogee"
    assert isinstance(no_parens, FunctionCall)
    assert no_parens.function == "timer"
    assert no_parens.arguments == ()  # a no-parens call binds no arguments


def test_target_block() -> None:
    target = _sequence()[5]
    assert isinstance(target, TargetStatement)
    assert target.solver == ObjectRef("DC")
    assert target.options == [RawValue("SolveMode = Solve")]
    assert [command.keyword for command in target.body] == ["Vary", "Achieve"]


def test_optimize_block_without_options() -> None:
    optimize = _sequence()[6]
    assert isinstance(optimize, OptimizeStatement)
    assert optimize.solver == ObjectRef("VF13")
    assert optimize.options is None
    assert [command.keyword for command in optimize.body] == ["Minimize"]


def test_if_block_with_else() -> None:
    if_statement = _sequence()[7]
    assert isinstance(if_statement, IfStatement)
    assert if_statement.condition == RawValue("Sat.TA > 90")
    assert [command.keyword for command in if_statement.body] == ["Stop"]
    assert [command.keyword for command in if_statement.orelse] == ["Report"]


def test_if_block_without_else_has_empty_orelse() -> None:
    if_statement = Script.parse(
        "BeginMissionSequence\nIf x > 1\n   Stop\nEndIf\n"
    ).mission_sequence[0]
    assert isinstance(if_statement, IfStatement)
    assert if_statement.orelse == ()


def test_for_block_range() -> None:
    for_statement = _sequence()[8]
    assert isinstance(for_statement, ForStatement)
    assert for_statement.variable == ObjectRef("k")
    assert (for_statement.start, for_statement.stop, for_statement.step) == (1, 10, 2)
    assert [command.keyword for command in for_statement.body] == ["Maneuver"]


def test_for_block_two_part_range_has_no_step() -> None:
    for_statement = Script.parse(
        "BeginMissionSequence\nFor i = 1:10\n   Stop\nEndFor\n"
    ).mission_sequence[0]
    assert isinstance(for_statement, ForStatement)
    assert (for_statement.start, for_statement.stop, for_statement.step) == (1, 10, None)


def test_while_block() -> None:
    while_statement = _sequence()[9]
    assert isinstance(while_statement, WhileStatement)
    assert while_statement.condition == RawValue("Sat.ElapsedDays < 1")
    assert [command.keyword for command in while_statement.body] == ["Propagate"]


def test_script_block_body_text() -> None:
    script_block = _sequence()[10]
    assert isinstance(script_block, ScriptBlock)
    assert "x = 1;" in script_block.body_text


def test_empty_script_block_has_empty_body() -> None:
    script_block = Script.parse("BeginMissionSequence\nBeginScript\nEndScript\n").mission_sequence[
        0
    ]
    assert isinstance(script_block, ScriptBlock)
    assert script_block.body_text == ""


def test_command_without_label() -> None:
    propagate = Script.parse("BeginMissionSequence\nPropagate DefaultProp(Sat)\n").mission_sequence[
        0
    ]
    assert propagate.label is None


def test_build_command_falls_back_to_base_for_unmapped_node() -> None:
    # The BeginMissionSequence marker is not a builder-mapped statement; it wraps as base Command.
    marker = parse("BeginMissionSequence\n").root_node.named_children[0]
    command = build_command(marker)
    assert type(command) is Command
    assert command.keyword == "begin_mission_sequence"  # a leaf marker → its node type


def test_block_keyword_is_the_leading_token() -> None:
    # A block command's keyword is its leading anonymous keyword token (``If`` / ``Target`` / …).
    if_statement = Script.parse(
        "BeginMissionSequence\nIf x > 1\n   Stop\nEndIf\n"
    ).mission_sequence[0]
    assert if_statement.keyword == "If"


def test_function_call_keyword_falls_back_to_node_type() -> None:
    call = _sequence()[2]
    assert call.keyword == "function_call_command"  # no leading keyword / name field


# --- Script root ----------------------------------------------------------------------------------


def test_script_constructed_from_tree() -> None:
    tree = parse(_CONFIG)
    script = Script(tree)
    assert script.tree is tree
    assert "Sat" in script.resources


@pytest.mark.parametrize(
    "source",
    [
        _CONFIG,
        _MISSION,
        "Create Spacecraft Sat\r\nSat.SMA = 7000\r\n",  # CRLF preserved
        "% just a comment\n\n",
        "",
    ],
)
def test_to_source_is_byte_exact(source: str) -> None:
    assert Script.parse(source).to_source() == source


def test_configuration_only_script_has_empty_mission_sequence() -> None:
    script = Script.parse("Create Spacecraft Sat\nSat.SMA = 7000\n")
    assert script.mission_sequence == ()
    assert script.resources["Sat"]["SMA"] == 7000


def test_byte_range_and_error_passthrough() -> None:
    script = Script.parse(_CONFIG)
    start, end = script.byte_range
    assert start == 0
    assert end == len(_CONFIG.encode("utf-8"))
    assert script.has_errors is False


def test_byte_range_provenance_on_a_command() -> None:
    command = Script.parse("BeginMissionSequence\nStop\n").mission_sequence[0]
    start, end = command.byte_range
    assert command.to_source() == "Stop"
    assert (start, end) == (21, 25)


def test_repr() -> None:
    assert repr(Script.parse(_MISSION)) == "Script(resources=1, mission_sequence=11)"


def test_resource_type_is_a_resource_instance() -> None:
    sat = Script.parse(_CONFIG).resources["Sat"]
    assert isinstance(sat, Resource)
