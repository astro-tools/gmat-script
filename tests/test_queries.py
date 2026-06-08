"""The tree-sitter query layer: highlights / locals / tags load against the compiled grammar and
capture the right nodes (D1 / D3).

The three query files ship in ``tree-sitter-gmat/queries/`` and are packed with the npm grammar;
they are the shared layer behind editor highlighting, go-to-definition / find-references, and the
document-symbol outline. These tests assert the definition-of-done:

* all three load against the *vendored, compiled* grammar (the same language the wheel ships);
* highlight captures land on the expected nodes (keywords, types, fields, names, literals, …);
* resource definition / reference resolution works via ``locals.scm`` — a name's definition is at
  its ``Create`` and each use resolves to it;
* ``tags.scm`` exposes resource and command symbols.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from tree_sitter import Language, Query, QueryCursor

from gmat_script._grammar import language
from gmat_script.ast.base import node_text
from gmat_script.parser import parse

if TYPE_CHECKING:
    from tree_sitter import Node

_QUERIES_DIR = Path(__file__).parent.parent / "tree-sitter-gmat" / "queries"
_QUERY_FILES = ("highlights.scm", "locals.scm", "tags.scm")


def _gmat_language() -> Language:
    """The vendored, compiled GMAT grammar — the language the queries must load against."""
    return Language(language())


def _load_query(name: str) -> Query:
    source = (_QUERIES_DIR / name).read_text(encoding="utf-8")
    return Query(_gmat_language(), source)


def _captures(name: str, source: str) -> dict[str, list[Node]]:
    """Run query *name* over parsed *source* and return its capture-name → nodes mapping."""
    cursor = QueryCursor(_load_query(name))
    return cursor.captures(parse(source).root_node)


def _matches(name: str, source: str) -> list[dict[str, list[Node]]]:
    """Run query *name* over parsed *source*, returning per-match capture maps.

    Unlike :func:`_captures`, this groups each match's captures together, so a wrapper capture
    (``@definition.class``) and the ``@name`` inside it stay associated.
    """
    cursor = QueryCursor(_load_query(name))
    return [match for _, match in cursor.matches(parse(source).root_node)]


def _names_for(matches: list[dict[str, list[Node]]], capture: str) -> set[str]:
    """The ``@name`` texts of every match that carries *capture* (e.g. ``definition.class``)."""
    return {
        node_text(name) for match in matches if capture in match for name in match.get("name", [])
    }


def _texts(captures: dict[str, list[Node]]) -> dict[str, list[str]]:
    return {name: [node_text(node) for node in nodes] for name, nodes in captures.items()}


# --------------------------------------------------------------------------------------------------
# Every query loads against the compiled grammar (DoD: "queries load ... without error").
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", _QUERY_FILES)
def test_query_loads_against_compiled_grammar(name: str) -> None:
    # Query() validates every node type, field, and anonymous token against the grammar and raises
    # QueryError on an unknown one, so constructing and running it is the load assertion; a
    # non-empty result confirms the patterns match the grammar's real node set.
    assert _captures(name, _HIGHLIGHT_FIXTURE)


# --------------------------------------------------------------------------------------------------
# highlights.scm
# --------------------------------------------------------------------------------------------------

_HIGHLIGHT_FIXTURE = """% a leading comment
#Include 'helpers.script'
Create Spacecraft Sat
Create Variable count
BeginMissionSequence
GMAT Sat.SMA = 7000.5
Propagate 'Step one' Prop(Sat) {Sat.ElapsedSecs = 60}
If Sat.TA > 90
   Stop
EndIf
"""


def test_highlights_capture_each_category() -> None:
    texts = _texts(_captures("highlights.scm", _HIGHLIGHT_FIXTURE))

    # Keywords: the structural words only — resource types and command heads are *not* keywords.
    for kw in ("#Include", "Create", "GMAT", "BeginMissionSequence", "If", "EndIf"):
        assert kw in texts["keyword"], f"{kw!r} should be a keyword"

    # Resource types in a Create declaration — exactly the two type positions.
    assert sorted(texts["type"]) == ["Spacecraft", "Variable"]

    # Command heads highlight as functions (Propagate, Stop), not plain variables.
    for head in ("Propagate", "Stop"):
        assert head in texts["function"]

    # Dotted field / property access.
    for field in ("SMA", "ElapsedSecs", "TA"):
        assert field in texts["property"]

    # Resource / variable names fall through to the catch-all.
    for name in ("Sat", "count"):
        assert name in texts["variable"]

    assert "% a leading comment" in texts["comment"]
    assert "'helpers.script'" in texts["string"]
    assert "'Step one'" in texts["label"]
    assert "7000.5" in texts["number"] and "60" in texts["number"]
    assert "=" in texts["operator"] and ">" in texts["operator"]
    assert "{" in texts["punctuation.bracket"] and "(" in texts["punctuation.bracket"]


def test_command_label_is_not_a_plain_string() -> None:
    texts = _texts(_captures("highlights.scm", _HIGHLIGHT_FIXTURE))
    # The mission-step label is a @label, distinct from the #Include path @string.
    assert "'Step one'" in texts["label"]
    assert "'Step one'" not in texts.get("string", [])


# --------------------------------------------------------------------------------------------------
# locals.scm — definition / reference resolution
# --------------------------------------------------------------------------------------------------

_LOCALS_FIXTURE = """Create Spacecraft Sat
Create ForceModel FM

BeginMissionSequence
GMAT Sat.SMA = 7000
Sat.Coord = FM
Propagate Prop(Sat)
"""


def _resolve_locals(source: str) -> tuple[dict[str, Node], list[Node]]:
    """Mirror the locals model: a node captured as a definition is not also counted a reference.

    Returns ``(definitions_by_name, references)`` where *references* excludes the definition nodes
    (the trailing catch-all ``(identifier) @local.reference`` matches them too, but the earlier,
    more specific ``@local.definition`` pattern wins — the first-match precedence a host applies).
    """
    captures = _captures("locals.scm", source)
    definition_nodes = captures.get("local.definition", [])
    definition_ranges = {node.byte_range for node in definition_nodes}
    definitions = {node_text(node): node for node in definition_nodes}
    references = [
        node
        for node in captures.get("local.reference", [])
        if node.byte_range not in definition_ranges
    ]
    return definitions, references


def test_locals_marks_create_as_the_definition() -> None:
    definitions, _ = _resolve_locals(_LOCALS_FIXTURE)

    assert set(definitions) == {"Sat", "FM"}
    # Each definition node is the name in its Create declaration.
    for node in definitions.values():
        assert node.parent is not None
        assert node.parent.type == "create_command"


def test_locals_resolves_each_use_to_its_definition() -> None:
    definitions, references = _resolve_locals(_LOCALS_FIXTURE)

    # Find-references for Sat: Sat.SMA, Sat.Coord, and Prop(Sat) — three uses, none of them the
    # declaration itself.
    sat_uses = [node for node in references if node_text(node) == "Sat"]
    assert len(sat_uses) == 3

    # FM is used once, as the right-hand side of Sat.Coord = FM.
    assert sum(node_text(node) == "FM" for node in references) == 1

    # Go-to-definition: every reference whose name is a declared resource resolves to that Create.
    for use in sat_uses:
        target = definitions[node_text(use)]
        assert target.parent is not None and target.parent.type == "create_command"
        assert target.start_byte < use.start_byte  # the declaration precedes the use here


def test_locals_does_not_treat_field_names_as_resource_definitions() -> None:
    # SMA / Coord are member properties, never declared with Create, so they define nothing.
    definitions, _ = _resolve_locals(_LOCALS_FIXTURE)
    assert "SMA" not in definitions
    assert "Coord" not in definitions


# --------------------------------------------------------------------------------------------------
# tags.scm — symbol outline / navigation
# --------------------------------------------------------------------------------------------------

_TAGS_FIXTURE = """Create Spacecraft Sat
Create ForceModel FM

BeginMissionSequence
Propagate Prop(Sat)
Maneuver TOI
[range] = ComputeRange(Sat)
[now] = Python.time.time()
"""

_GMF_FIXTURE = "function [out] = helper(a, b)\n"


def test_tags_define_resources() -> None:
    matches = _matches("tags.scm", _TAGS_FIXTURE)
    assert _names_for(matches, "definition.class") == {"Sat", "FM"}


def test_tags_reference_commands_and_calls() -> None:
    matches = _matches("tags.scm", _TAGS_FIXTURE)
    # Generic mission commands plus the output-binding calls (bare and dotted-through-call).
    expected = {"Propagate", "Maneuver", "ComputeRange", "time"}
    assert expected <= _names_for(matches, "reference.call")


def test_tags_define_gmat_functions() -> None:
    matches = _matches("tags.scm", _GMF_FIXTURE)
    assert _names_for(matches, "definition.function") == {"helper"}
