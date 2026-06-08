"""The typed AST overlay against the full stock corpus (issue #12).

Building :class:`~gmat_script.Script` over every fixture and exhaustively touching its resources,
fields, and (recursively) its mission-sequence commands must never raise and must re-emit the source
byte-for-byte — the overlay-is-a-lossless-view guarantee on real GMAT scripts, not just hand-written
snippets.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gmat_script import Script
from gmat_script.ast import (
    ForStatement,
    FunctionCall,
    GenericCommand,
    IfStatement,
    ScriptBlock,
    WhileStatement,
)
from gmat_script.ast.commands import Assignment, Command, _SolverBlock

_CORPUS_DIR = Path(__file__).parent / "data" / "corpus"
_FIXTURES = sorted([*_CORPUS_DIR.rglob("*.script"), *_CORPUS_DIR.rglob("*.gmf")])
_IDS = [str(path.relative_to(_CORPUS_DIR)) for path in _FIXTURES]


def _touch_command(command: Command) -> None:
    """Access every structured property of *command*, recursing into block bodies."""
    _ = command.keyword, command.label, command.byte_range
    if isinstance(command, GenericCommand):
        _ = command.name, command.arguments
    elif isinstance(command, Assignment):
        _ = command.target, command.value
    elif isinstance(command, FunctionCall):
        _ = command.outputs, command.function, command.arguments
    elif isinstance(command, IfStatement):
        _ = command.condition
        for child in (*command.body, *command.orelse):
            _touch_command(child)
    elif isinstance(command, ForStatement):
        _ = command.variable, command.start, command.stop, command.step
        for child in command.body:
            _touch_command(child)
    elif isinstance(command, WhileStatement):
        _ = command.condition
        for child in command.body:
            _touch_command(child)
    elif isinstance(command, _SolverBlock):
        _ = command.solver, command.options
        for child in command.body:
            _touch_command(child)
    elif isinstance(command, ScriptBlock):
        _ = command.body_text


@pytest.mark.corpus
@pytest.mark.parametrize("fixture", _FIXTURES, ids=_IDS)
def test_overlay_roundtrips_byte_for_byte(fixture: Path) -> None:
    source = fixture.read_bytes().decode("utf-8")
    assert Script.parse(source).to_source() == source


@pytest.mark.corpus
@pytest.mark.parametrize("fixture", _FIXTURES, ids=_IDS)
def test_overlay_builds_and_is_fully_traversable(fixture: Path) -> None:
    script = Script.parse(fixture.read_bytes().decode("utf-8"))
    for resource in script.resources.values():
        _ = resource.name, resource.type, resource.array_dimensions, resource.assignments
        for field in resource:
            _ = resource[field]  # force value coercion on every configured field
    for command in script.mission_sequence:
        _touch_command(command)


@pytest.mark.corpus
def test_overlay_finds_resources_and_sequences_across_the_corpus() -> None:
    """Sanity floor: the corpus collectively exercises resources and a mission sequence."""
    total_resources = 0
    total_commands = 0
    for fixture in _FIXTURES:
        script = Script.parse(fixture.read_bytes().decode("utf-8"))
        total_resources += len(script.resources)
        total_commands += len(script.mission_sequence)
    assert total_resources > 0
    assert total_commands > 0
