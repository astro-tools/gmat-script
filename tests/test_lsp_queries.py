"""Tests for the LSP tree-sitter query helpers (:mod:`gmat_script.lsp.queries`)."""

from __future__ import annotations

from gmat_script.ast.base import node_text
from gmat_script.lsp import queries
from gmat_script.parser import parse

_SCRIPT = """Create Spacecraft Sat
Create ForceModel FM
Sat.SMA = 7000

BeginMissionSequence
Propagate Prop(Sat)
"""

# A GmatFunction header — the function-definition tag (D10).
_FUNCTION = "function [dr, dv] = RICdelta(rv1, rv2)\n"


def test_definition_nodes_are_create_names() -> None:
    names = [node_text(node) for node in queries.definition_nodes(parse(_SCRIPT).root_node)]
    assert names == ["Sat", "FM"]


def test_reference_nodes_capture_every_identifier_use() -> None:
    names = [node_text(node) for node in queries.reference_nodes(parse(_SCRIPT).root_node)]
    # The generous reference capture includes type names and command keywords, and a resource used
    # several times appears once per use.
    assert names.count("Sat") >= 2
    assert "Propagate" in names and "Spacecraft" in names


def test_symbol_tags_resources_are_class_tags_in_source_order() -> None:
    tags = queries.symbol_tags(parse(_SCRIPT).root_node)
    assert [(tag.kind, tag.name) for tag in tags] == [("class", "Sat"), ("class", "FM")]
    # The name node is the resource name; the definition node spans the whole Create.
    assert node_text(tags[0].name_node) == "Sat"
    assert node_text(tags[0].definition_node).startswith("Create Spacecraft")


def test_symbol_tags_include_function_definitions() -> None:
    tags = queries.symbol_tags(parse(_FUNCTION).root_node)
    assert ("function", "RICdelta") in [(tag.kind, tag.name) for tag in tags]


def test_load_query_is_cached() -> None:
    # The compiled query is memoised, so repeated loads return the same object.
    assert queries._load_query("locals.scm") is queries._load_query("locals.scm")
