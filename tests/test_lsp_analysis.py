"""Tests for the language features (:mod:`gmat_script.lsp.analysis`).

These exercise the pure feature functions directly — the server (``test_lsp_server.py``) is a thin
shell over them. Coverage of the catalogue-driven paths uses fields whose reflection carries
the relevant data (``BatchEstimator`` has both an enum field and an object-reference field), and a
synthetic :class:`~gmat_script.FieldSpec` covers the hover-rendering branches deterministically.
Every feature is also checked against a malformed buffer to confirm it degrades rather than raises.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from lsprotocol import types as lsp

from gmat_script.catalog import FieldSpec
from gmat_script.lsp import analysis

_SCRIPT = """Create Spacecraft Sat
Sat.SMA = 7000
Create ForceModel FM

BeginMissionSequence
Propagate Prop(Sat)
"""


def pos(line: int, character: int) -> lsp.Position:
    return lsp.Position(line=line, character=character)


def markdown(hover: lsp.Hover | None) -> str:
    """The markdown body of a hover, asserting it is present and a ``MarkupContent``."""
    assert hover is not None
    assert isinstance(hover.contents, lsp.MarkupContent)
    return hover.contents.value


# ----------------------------------------------------------------------------
# diagnostics


def test_diagnostics_reports_lint_findings() -> None:
    # FM is created but never referenced — the linter's info-level unused-resource rule.
    diagnostics = analysis.diagnostics_for(_SCRIPT)
    unused = [d for d in diagnostics if d.code == "unused-resource"]
    assert len(unused) == 1
    finding = unused[0]
    assert finding.severity == lsp.DiagnosticSeverity.Information
    assert finding.source == "gmat-script"
    assert finding.range.start.line == 2  # the `Create ForceModel FM` line (0-indexed)


def test_diagnostics_reports_syntax_errors() -> None:
    diagnostics = analysis.diagnostics_for("Create Spacecraft\nSat.SMA = = =\n")
    assert any(d.code == "syntax-error" for d in diagnostics)
    assert all(d.severity == lsp.DiagnosticSeverity.Error for d in diagnostics)


def test_diagnostics_clean_script_is_empty() -> None:
    clean = "Create Spacecraft Sat\nSat.SMA = 7000\n\nBeginMissionSequence\nPropagate Prop(Sat)\n"
    assert analysis.diagnostics_for(clean) == []


# ----------------------------------------------------------------------------
# hover


def test_hover_on_field_uses_catalogue() -> None:
    hover = analysis.hover_at(_SCRIPT, pos(1, 5))  # on `SMA` in `Sat.SMA`
    assert hover is not None and hover.range is not None
    assert "Spacecraft.SMA" in markdown(hover)
    assert hover.range.start == pos(1, 4)


def test_hover_on_resource_name() -> None:
    hover = analysis.hover_at(_SCRIPT, pos(0, 19))  # on `Sat` in the Create
    assert markdown(hover) == "**Sat** — `Spacecraft`"


def test_hover_on_create_type() -> None:
    hover = analysis.hover_at(_SCRIPT, pos(0, 8))  # on `Spacecraft`
    assert "GMAT resource type" in markdown(hover)


def test_hover_on_object_of_member_falls_through_to_resource() -> None:
    # The cursor is on `Sat` (the object) of `Sat.SMA`, not the field — so the field doc is skipped
    # and the resource summary is shown instead.
    hover = analysis.hover_at(_SCRIPT, pos(1, 1))
    assert markdown(hover) == "**Sat** — `Spacecraft`"


def test_hover_on_unknown_field_is_none() -> None:
    assert analysis.hover_at("Create Spacecraft Sat\nSat.Bogus = 1\n", pos(1, 6)) is None


def test_hover_on_uncatalogued_type_is_none() -> None:
    # A plugin type absent from the default catalogue (D15) has no type summary.
    assert analysis.hover_at("Create OpenFramesView ofv\n", pos(0, 10)) is None


def test_hover_on_field_of_undeclared_resource_is_none() -> None:
    assert analysis.hover_at("Foo.SMA = 7000\n", pos(0, 5)) is None


def test_hover_off_identifier_is_none() -> None:
    assert analysis.hover_at(_SCRIPT, pos(1, 8)) is None  # on the `=` / whitespace


def test_hover_trailing_edge_of_identifier_resolves() -> None:
    # Cursor at the end of `Sat` (column past the last char) still resolves to the identifier.
    assert "Sat" in markdown(analysis.hover_at(_SCRIPT, pos(0, 21)))


def test_render_field_includes_all_detail_lines() -> None:
    spec = FieldSpec(
        name="Axes",
        type="enum",
        gmat_type="Enumeration",
        read_only=True,
        allowed=("MJ2000Eq", "Fixed"),
        ref_target="CoordinateSystem",
        default="MJ2000Eq",
        unit="deg",
    )
    rendered = analysis._render_field("ImpulsiveBurn", spec)
    assert "**ImpulsiveBurn.Axes** — `enum` (deg)" in rendered
    assert "Default: `MJ2000Eq`" in rendered
    assert "`MJ2000Eq`, `Fixed`" in rendered
    assert "References a `CoordinateSystem`." in rendered
    assert "_Read-only._" in rendered


def test_render_field_minimal_has_no_detail_block() -> None:
    spec = FieldSpec(name="SMA", type="real", gmat_type="Real", read_only=False)
    assert analysis._render_field("Spacecraft", spec) == "**Spacecraft.SMA** — `real`"


# ----------------------------------------------------------------------------
# definition / references


def test_definition_from_usage() -> None:
    line = _SCRIPT.splitlines()[5]
    column = line.index("Sat", line.index("Prop"))
    ranges = analysis.definition_ranges(_SCRIPT, pos(5, column + 1))
    assert len(ranges) == 1
    assert ranges[0] == lsp.Range(start=pos(0, 18), end=pos(0, 21))


def test_definition_off_identifier_is_empty() -> None:
    assert analysis.definition_ranges(_SCRIPT, pos(1, 8)) == []


def test_definition_of_unknown_name_is_empty() -> None:
    # `Prop` is referenced but never created, so it has no definition.
    line = _SCRIPT.splitlines()[5]
    ranges = analysis.definition_ranges(_SCRIPT, pos(5, line.index("Prop") + 1))
    assert ranges == []


def test_references_include_and_exclude_declaration() -> None:
    with_decl = analysis.reference_ranges(_SCRIPT, pos(0, 19), include_declaration=True)
    without_decl = analysis.reference_ranges(_SCRIPT, pos(0, 19), include_declaration=False)
    # The declaration occurrence (the Create name) is the one dropped.
    assert lsp.Range(start=pos(0, 18), end=pos(0, 21)) in with_decl
    assert lsp.Range(start=pos(0, 18), end=pos(0, 21)) not in without_decl
    assert len(with_decl) == len(without_decl) + 1
    # Results are in source order.
    starts = [r.start for r in with_decl]
    assert starts == sorted(starts, key=lambda p: (p.line, p.character))


def test_references_off_identifier_is_empty() -> None:
    assert analysis.reference_ranges(_SCRIPT, pos(1, 8), include_declaration=True) == []


# ----------------------------------------------------------------------------
# document symbols


def test_document_symbols_outline() -> None:
    symbols = analysis.document_symbols(_SCRIPT)
    assert [(s.name, s.kind, s.detail) for s in symbols] == [
        ("Sat", lsp.SymbolKind.Class, "Spacecraft"),
        ("FM", lsp.SymbolKind.Class, "ForceModel"),
    ]
    # The selection range is the name; the full range spans the Create.
    assert symbols[0].selection_range.start == pos(0, 18)
    assert symbols[0].range.start == pos(0, 0)


def test_document_symbols_function() -> None:
    symbols = analysis.document_symbols("function [q] = Quat(a)\n")
    assert (symbols[0].name, symbols[0].kind, symbols[0].detail) == (
        "Quat",
        lsp.SymbolKind.Function,
        None,
    )


# ----------------------------------------------------------------------------
# completion


def test_completion_resource_names_in_bare_position() -> None:
    items = {item.label: item for item in analysis.completions_at(_SCRIPT, pos(5, 0))}
    assert set(items) == {"Sat", "FM"}
    assert items["Sat"].kind == lsp.CompletionItemKind.Variable
    assert items["Sat"].detail == "Spacecraft"


def test_completion_field_names_after_dot() -> None:
    items = analysis.completions_at("Create Spacecraft Sat\nSat.\n", pos(1, 4))
    labels = {item.label for item in items}
    assert {"SMA", "ECC", "INC"} <= labels
    assert all(item.kind == lsp.CompletionItemKind.Field for item in items)


def test_completion_field_context_with_undeclared_object_is_empty() -> None:
    assert analysis.completions_at("Foo.\n", pos(0, 4)) == []


def test_completion_enum_values_in_value_position() -> None:
    source = "Create BatchEstimator BE\nBE.ReportStyle = \n"
    items = analysis.completions_at(source, pos(1, len("BE.ReportStyle = ")))
    assert [item.label for item in items] == ["Normal", "Concise", "Verbose", "Debug"]
    assert all(item.kind == lsp.CompletionItemKind.EnumMember for item in items)


def test_completion_object_reference_narrows_to_target_type() -> None:
    source = (
        "Create BatchEstimator BE\n"
        "Create TrackingFileSet tfs\n"
        "Create MeasurementModel mm\n"
        "BE.Measurements = \n"
    )
    items = analysis.completions_at(source, pos(3, len("BE.Measurements = ")))
    assert [item.label for item in items] == ["mm"]


def test_completion_object_reference_matches_via_alias_resolution() -> None:
    # BE.Propagator references a PropSetup; `Create Propagator` builds a PropSetup (an alias), so
    # the candidate narrows by canonical resolution, not exact spelling.
    source = (
        "Create BatchEstimator BE\n"
        "Create Propagator prop\n"
        "Create Spacecraft Sat\n"
        "BE.Propagator = \n"
    )
    items = analysis.completions_at(source, pos(3, len("BE.Propagator = ")))
    assert [item.label for item in items] == ["prop"]


def test_completion_value_position_without_enum_or_ref_offers_resources() -> None:
    # SMA is a plain real field: a value position there falls back to candidate resource names.
    source = "Create Spacecraft Sat\nCreate Variable v\nSat.SMA = \n"
    labels = {item.label for item in analysis.completions_at(source, pos(2, len("Sat.SMA = ")))}
    assert labels == {"Sat", "v"}


def test_completion_value_position_with_undeclared_object_offers_resources() -> None:
    source = "Create Spacecraft Sat\nFoo.Bar = \n"
    labels = {item.label for item in analysis.completions_at(source, pos(1, len("Foo.Bar = ")))}
    assert labels == {"Sat"}


# ----------------------------------------------------------------------------
# formatting


def test_format_edits_reformats() -> None:
    edits = analysis.format_edits("GMAT Sat.SMA=7000;\n")
    assert len(edits) == 1
    assert edits[0].new_text == "Sat.SMA = 7000\n"
    assert edits[0].range.start == pos(0, 0)


def test_format_edits_already_canonical_is_empty() -> None:
    assert analysis.format_edits("Sat.SMA = 7000\n") == []


def test_format_edits_syntax_error_is_empty() -> None:
    assert analysis.format_edits("Create = = =\n") == []


def test_format_edits_deeply_nested_is_empty() -> None:
    # A pathologically deep expression parses cleanly but recurses the formatter past the recursion
    # limit; format_edits must absorb the RecursionError and yield no edit, not propagate it.
    source = "x = " + "(" * 1000 + "1" + ")" * 1000 + "\n"
    assert analysis.format_edits(source) == []


# ----------------------------------------------------------------------------
# robustness: malformed input never raises


_MALFORMED = "Create Spacecraft\nSat.SMA = = =\nPropagate {{{\n"


@pytest.mark.parametrize(
    "call",
    [
        lambda: analysis.diagnostics_for(_MALFORMED),
        lambda: analysis.hover_at(_MALFORMED, pos(1, 2)),
        lambda: analysis.definition_ranges(_MALFORMED, pos(1, 2)),
        lambda: analysis.reference_ranges(_MALFORMED, pos(1, 2), include_declaration=True),
        lambda: analysis.document_symbols(_MALFORMED),
        lambda: analysis.completions_at(_MALFORMED, pos(1, 2)),
        lambda: analysis.format_edits(_MALFORMED),
    ],
)
def test_features_never_raise_on_malformed_input(call: Callable[[], object]) -> None:
    call()  # must not raise; the return value is feature-specific and asserted elsewhere
