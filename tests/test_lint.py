"""The static linter: the rule set, the engine, inline suppression, and the ``lint`` CLI.

The seeded-error suite under ``tests/data/lint/`` carries one deliberately-broken script per rule;
``test_seeded_script_trips_exactly_its_rule`` asserts each trips that rule and nothing else, with a
1-indexed position. The rest exercises the engine's inputs and short-circuits, each rule's edges,
the suppression directives, and the CLI's output and exit-code contract.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from gmat_script import Script, cli, lint, parse
from gmat_script.catalog import FieldSpec, load_catalog
from gmat_script.lint import RULES, Diagnostic, Severity
from gmat_script.lint.context import LintContext
from gmat_script.lint.diagnostics import node_range
from gmat_script.lint.registry import resolve_rules
from gmat_script.lint.rules import _target_compatible, _type_problem, _value_kind
from gmat_script.lint.suppression import parse_suppressions

if TYPE_CHECKING:
    from gmat_script.ast.values import Value

_LINT_DATA = Path(__file__).parent / "data" / "lint"

# Expected severity for each seeded rule (the rule code is the fixture's file stem).
_SEEDED_SEVERITY = {
    "unknown-resource-type": Severity.ERROR,
    "undeclared-reference": Severity.ERROR,
    "duplicate-name": Severity.ERROR,
    "unknown-field": Severity.WARNING,
    "type-mismatch": Severity.WARNING,
    "enum-violation": Severity.WARNING,
    "ref-target-mismatch": Severity.WARNING,
    "unused-resource": Severity.INFO,
}

_SEEDED = sorted(_LINT_DATA.glob("*.script"))
_SEEDED_IDS = [p.stem for p in _SEEDED]


def _write(tmp_path: Path, name: str, content: str) -> str:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8", newline="")
    return str(path)


def _stdin(text: str) -> io.TextIOWrapper:
    return io.TextIOWrapper(io.BytesIO(text.encode("utf-8")), encoding="utf-8", newline="")


# --- the seeded-error suite -------------------------------------------------------------------


def test_seeded_suite_covers_every_emitting_rule() -> None:
    """There is exactly one seeded script per rule that can emit a finding (the coverage guard)."""
    assert {p.stem for p in _SEEDED} == {rule.code for rule in RULES}


@pytest.mark.parametrize("fixture", _SEEDED, ids=_SEEDED_IDS)
def test_seeded_script_trips_exactly_its_rule(fixture: Path) -> None:
    rule = fixture.stem
    diagnostics = lint(fixture.read_text(encoding="utf-8"))
    assert sorted({d.rule for d in diagnostics}) == [rule], (
        f"{fixture.name} should trip only {rule!r}"
    )
    diagnostic = next(d for d in diagnostics if d.rule == rule)
    assert diagnostic.severity is _SEEDED_SEVERITY[rule]
    assert diagnostic.start.line >= 1
    assert diagnostic.start.column >= 1
    assert diagnostic.message


# --- the engine -------------------------------------------------------------------------------


def test_clean_script_has_no_diagnostics() -> None:
    assert lint("Create Spacecraft Sat\nBeginMissionSequence\nPropagate Sat\n") == []


def test_lint_accepts_text_tree_and_script_inputs() -> None:
    source = "Create Spcecraft Sat\nBeginMissionSequence\nPropagate Sat\n"
    from_text = lint(source)
    from_tree = lint(parse(source))
    from_script = lint(Script(parse(source)))
    assert [d.rule for d in from_text] == ["unknown-resource-type"]
    assert from_tree == from_text
    assert from_script == from_text


def test_lint_rejects_other_input_types() -> None:
    with pytest.raises(TypeError):
        lint(123)  # type: ignore[arg-type]


def test_syntax_error_short_circuits_to_syntax_error_diagnostics() -> None:
    # An unterminated If recovers to an ERROR node; the structural rules must not run on it.
    diagnostics = lint("BeginMissionSequence\nIf Sat.TA > 90\nPropagate Sat\n")
    assert diagnostics
    assert {d.rule for d in diagnostics} == {"syntax-error"}
    assert all(d.severity is Severity.ERROR for d in diagnostics)


def test_diagnostics_are_sorted_by_position() -> None:
    source = (
        "Create Spacecraft Sat\nSat.Bogus = 1\nCreate Nope X\nBeginMissionSequence\nPropagate Sat\n"
    )
    diagnostics = lint(source)
    positions = [(d.start.line, d.start.column) for d in diagnostics]
    assert positions == sorted(positions)


def test_select_and_ignore_toggle_rules() -> None:
    source = "Create Nope X\nCreate Variable spare\nBeginMissionSequence\nPropagate X\n"
    only = lint(source, select=["unknown-resource-type"])
    assert {d.rule for d in only} == {"unknown-resource-type"}
    without = lint(source, ignore=["unused-resource"])
    assert "unused-resource" not in {d.rule for d in without}


def test_unknown_rule_code_raises() -> None:
    with pytest.raises(ValueError, match="unknown select rule code"):
        lint("Create Spacecraft Sat\n", select=["no-such-rule"])
    with pytest.raises(ValueError, match="unknown ignore rule code"):
        lint("Create Spacecraft Sat\n", ignore=["no-such-rule"])


# --- suppression ------------------------------------------------------------------------------


def test_disable_line_suppresses_only_its_line() -> None:
    source = (
        "Create Nope A  % gmat-script: disable-line=unknown-resource-type\n"
        "Create Nope B\n"
        "BeginMissionSequence\n"
        "Propagate A\n"
    )
    rules = {(d.rule, d.start.line) for d in lint(source)}
    assert ("unknown-resource-type", 1) not in rules
    assert ("unknown-resource-type", 2) in rules


def test_bare_disable_line_suppresses_all_rules_on_the_line() -> None:
    source = (
        "Create Spacecraft Sat\n"
        "Sat.Bogus = 1  % gmat-script: disable-line\n"
        "BeginMissionSequence\nPropagate Sat\n"
    )
    assert lint(source) == []


def test_disable_suppresses_from_its_line_to_end_of_file() -> None:
    source = (
        "Create Spacecraft Sat\n"
        "% gmat-script: disable=unknown-field\n"
        "Sat.Bogus = 1\n"
        "BeginMissionSequence\n"
        "Propagate Sat\n"
    )
    assert "unknown-field" not in {d.rule for d in lint(source)}


def test_disable_above_the_directive_is_not_suppressed() -> None:
    source = (
        "Create Spacecraft Sat\n"
        "Sat.Bogus = 1\n"
        "% gmat-script: disable=unknown-field\n"
        "BeginMissionSequence\n"
        "Propagate Sat\n"
    )
    assert "unknown-field" in {d.rule for d in lint(source)}


def test_parse_suppressions_scopes_per_line_and_bare_means_all() -> None:
    suppressions = parse_suppressions(
        "x  % gmat-script: disable-line=a\ny  % gmat-script: disable-line=b\n"
        "z  % gmat-script: disable-line\n"
    )
    assert suppressions.suppresses("a", 1)
    assert not suppressions.suppresses("b", 1)
    assert suppressions.suppresses("anything", 3)  # bare disable-line covers every rule


# --- per-rule edges ---------------------------------------------------------------------------


def test_unknown_field_skips_nested_paths_and_plugin_types() -> None:
    source = (
        "Create ForceModel FM\n"
        "FM.GravityField.Earth.Degree = 4\n"  # nested sub-object path: not validated
        "Create OpenFramesView View\n"
        "View.Anything = 1\n"  # plugin type absent from the catalogue: degrade, no finding
        "BeginMissionSequence\n"
        "Propagate FM\n"
    )
    assert "unknown-field" not in {d.rule for d in lint(source)}


def test_enum_violation_accepts_string_value_and_ignores_non_tokens() -> None:
    quoted = "Create ImpulsiveBurn B\nB.Axes = 'Sideways'\nBeginMissionSequence\nManeuver B\n"
    assert "enum-violation" in {d.rule for d in lint(quoted)}
    numeric = "Create ImpulsiveBurn B\nB.Axes = 5\nBeginMissionSequence\nManeuver B\n"
    assert "enum-violation" not in {d.rule for d in lint(numeric)}


def test_unused_resource_excuses_subscribers_and_begin_script_use() -> None:
    subscriber = "Create ReportFile RF\nBeginMissionSequence\nPropagate Anything\n"
    assert "unused-resource" not in {d.rule for d in lint(subscriber)}
    in_script = "Create Variable used\nBeginMissionSequence\nBeginScript\n   used = 1\nEndScript\n"
    assert "unused-resource" not in {d.rule for d in lint(in_script)}


def test_undeclared_reference_resolves_builtins_and_type_keywords() -> None:
    # Earth (builtin), ObjectReferenced (a catalogue axis type) — neither is an undeclared resource.
    source = (
        "Create CoordinateSystem CS\n"
        "CS.Origin = Earth\n"
        "CS.Axes = ObjectReferenced\n"
        "BeginMissionSequence\n"
        "Propagate CS\n"
    )
    assert "undeclared-reference" not in {d.rule for d in lint(source)}


def test_object_field_boolean_value_is_not_a_reference() -> None:
    # ``true`` in an object field is a value mistake, not an undeclared resource reference.
    source = "Create Spacecraft Sat\nSat.Tanks = true\nBeginMissionSequence\nPropagate Sat\n"
    rules = {d.rule for d in lint(source)}
    assert "undeclared-reference" not in rules
    assert "ref-target-mismatch" not in rules
    assert "type-mismatch" in rules  # object_array <- bool is a clear contradiction


def test_reference_root_descends_through_calls_and_members() -> None:
    from gmat_script.lint.references import reference_root

    tree = parse("BeginMissionSequence\nx = A(1, 1)\n")

    def find(node: object, kind: str) -> object:
        if node.type == kind:  # type: ignore[attr-defined]
            return node
        for child in node.children:  # type: ignore[attr-defined]
            found = find(child, kind)
            if found is not None:
                return found
        return None

    call = find(tree.root_node, "call_expression")
    assert call is not None
    assert reference_root(call).text.decode() == "A"  # type: ignore[arg-type,union-attr]


def test_value_kind_covers_each_shape() -> None:
    from gmat_script.ast.values import Array, ObjectRef, RawValue

    cases: list[tuple[Value, str]] = [
        (True, "bool"),
        (3, "number"),
        (1.5, "number"),
        ("s", "string"),
        (ObjectRef("X"), "reference"),
        (RawValue("a+b"), "expression"),
        (Array(()), "array"),
        ([], "list"),
    ]
    for value, kind in cases:
        assert _value_kind(value) == kind


def test_type_problem_flags_clear_contradictions_only() -> None:
    real = FieldSpec(name="SMA", type="real", gmat_type="Real", read_only=False)
    boolean = FieldSpec(name="On", type="bool", gmat_type="Boolean", read_only=False)
    obj = FieldSpec(name="FM", type="object", gmat_type="Object", read_only=False, ref_target="X")
    assert _type_problem(real, "text") is not None
    assert _type_problem(real, True) is not None
    assert _type_problem(boolean, 5) is not None
    assert _type_problem(obj, 5) is not None
    # Accepted: a number for a real, a reference anywhere.
    from gmat_script.ast.values import ObjectRef

    assert _type_problem(real, 7000) is None
    assert _type_problem(obj, ObjectRef("Tank")) is None


def test_target_compatible_matrix() -> None:
    context = LintContext(
        Script.parse("Create Spacecraft Sat\nBeginMissionSequence\nPropagate Sat\n"),
        parse("Create Spacecraft Sat\nBeginMissionSequence\nPropagate Sat\n"),
        load_catalog(),
    )
    assert _target_compatible(context, "Spacecraft", "Parameter")  # universal target
    assert _target_compatible(context, "Spacecraft", "Spacecraft")  # exact
    assert _target_compatible(context, "Propagator", "PropSetup")  # alias-equal
    assert _target_compatible(context, "GroundStation", "SpacePoint")  # category supertype
    assert _target_compatible(context, "ChemicalTank", "FuelTank")  # curated subtype
    assert _target_compatible(context, "PluginType", "FuelTank")  # unknown actual: cannot judge
    assert not _target_compatible(context, "Spacecraft", "FuelTank")  # genuine mismatch


def test_context_indexes_declarations_fields_and_script_blocks() -> None:
    source = "Create Variable x y\nx = 1\nBeginMissionSequence\nBeginScript\n   y = 2\nEndScript\n"
    context = LintContext(Script.parse(source), parse(source), load_catalog())
    assert [d.name for d in context.declarations] == ["x", "y"]
    assert context.resource_type("x") == "Variable"
    assert context.resource_type("missing") is None
    assert any("y = 2" in text for text in context.script_block_texts)


def test_value_references_are_computed_once_and_cached() -> None:
    source = "Create Spacecraft Sat\nSat.SMA = 7000\nBeginMissionSequence\nPropagate Sat\n"
    context = LintContext(Script.parse(source), parse(source), load_catalog())
    first = context.value_references()
    # A second call returns the cached mapping, not a freshly recomputed one.
    assert context.value_references() is first


def test_config_only_script_has_no_mission_sequence() -> None:
    context = LintContext(
        Script.parse("Create Spacecraft Sat\n"),
        parse("Create Spacecraft Sat\n"),
        load_catalog(),
    )
    assert context.sequence_nodes == []
    assert context.config_nodes


def test_resolve_rules_applies_select_then_ignore() -> None:
    chosen = resolve_rules(
        RULES, select=["unknown-field", "type-mismatch"], ignore=["type-mismatch"]
    )
    assert [rule.code for rule in chosen] == ["unknown-field"]


def test_node_range_is_one_indexed() -> None:
    tree = parse("Create Spacecraft Sat\n")
    create = tree.root_node.named_children[0]
    start, _ = node_range(create)
    assert (start.line, start.column) == (1, 1)


def test_severity_serialises_to_its_value() -> None:
    assert str(Severity.ERROR) == "error"
    assert Severity.WARNING.value == "warning"


def test_diagnostic_helpers() -> None:
    from gmat_script.parser import Position

    diagnostic = Diagnostic("r", Severity.INFO, "m", Position(3, 5), Position(3, 9))
    assert diagnostic.line == 3
    assert diagnostic.sort_key() == (3, 5, "r")


# --- the CLI ----------------------------------------------------------------------------------


def test_cli_text_output_and_error_exit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _write(tmp_path, "bad.script", "Create Nope X\nBeginMissionSequence\nPropagate X\n")
    code = cli.main(["lint", path])
    captured = capsys.readouterr()
    assert code == 1
    assert "error unknown-resource-type:" in captured.out
    assert captured.out.startswith(f"{path}:1:8:")


def test_cli_warning_only_exits_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _write(
        tmp_path,
        "warn.script",
        "Create Spacecraft Sat\nSat.Bogus = 1\nBeginMissionSequence\nPropagate Sat\n",
    )
    code = cli.main(["lint", path])
    captured = capsys.readouterr()
    assert code == 0  # warnings/info do not fail the run
    assert "warning unknown-field:" in captured.out


def test_cli_clean_file_exits_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _write(
        tmp_path, "ok.script", "Create Spacecraft Sat\nBeginMissionSequence\nPropagate Sat\n"
    )
    assert cli.main(["lint", path]) == 0
    assert capsys.readouterr().out == ""


def test_cli_json_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _write(tmp_path, "bad.script", "Create Nope X\nBeginMissionSequence\nPropagate X\n")
    code = cli.main(["lint", "--json", path])
    report = json.loads(capsys.readouterr().out)
    assert code == 1
    assert report["ok"] is False
    assert report["diagnostics"][0]["rule"] == "unknown-resource-type"
    assert report["diagnostics"][0]["severity"] == "error"
    assert report["diagnostics"][0]["start"] == {"line": 1, "column": 8}


def test_cli_json_array_for_multiple_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    a = _write(tmp_path, "a.script", "Create Spacecraft Sat\nBeginMissionSequence\nPropagate Sat\n")
    b = _write(tmp_path, "b.script", "Create Nope X\nBeginMissionSequence\nPropagate X\n")
    cli.main(["lint", "--json", a, b])
    report = json.loads(capsys.readouterr().out)
    assert isinstance(report, list)
    assert [r["ok"] for r in report] == [True, False]


def test_cli_select_and_ignore(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _write(
        tmp_path,
        "x.script",
        "Create Nope X\nCreate Variable spare\nBeginMissionSequence\nPropagate X\n",
    )
    cli.main(["lint", "--select", "unknown-resource-type", path])
    assert "unused-resource" not in capsys.readouterr().out


def test_cli_unknown_rule_code_exits_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path, "x.script", "Create Spacecraft Sat\n")
    code = cli.main(["lint", "--select", "nope", path])
    assert code == 2
    assert "unknown select rule code" in capsys.readouterr().err


def test_cli_missing_file_exits_two(capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(["lint", "does-not-exist.script"])
    assert code == 2
    assert "does-not-exist.script" in capsys.readouterr().err


def test_cli_reads_stdin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", _stdin("Create Nope X\nBeginMissionSequence\nPropagate X\n"))
    code = cli.main(["lint", "-"])
    assert code == 1
    assert "<stdin>:1:8:" in capsys.readouterr().out


def test_cli_escapes_non_ascii_on_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A non-ASCII resource name must not crash or leak raw bytes onto a legacy console.
    path = _write(
        tmp_path,
        "u.script",
        "Create Spacecraft Sât\nSât.Bogus = 1\nBeginMissionSequence\nPropagate Sât\n",
    )
    cli.main(["lint", path])
    out = capsys.readouterr().out
    assert out.isascii()
