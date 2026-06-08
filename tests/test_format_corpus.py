"""The canonical formatter against the full stock corpus.

Formatting every fixture must hold the four contract invariants on real GMAT scripts, not just
hand-written snippets: the output parses cleanly, is byte-for-byte idempotent, preserves every
comment, and is *structurally* equal to the input — no resource, field, or command added, dropped,
reordered, or altered (D14). The structural check (:func:`_signature`) is independent of the
formatter, so it is a genuine oracle rather than a restatement of the implementation.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tree_sitter import Node

from gmat_script import Script, format, parse

_CORPUS_DIR = Path(__file__).parent / "data" / "corpus"
_FIXTURES = sorted([*_CORPUS_DIR.rglob("*.script"), *_CORPUS_DIR.rglob("*.gmf")])
_IDS = [str(path.relative_to(_CORPUS_DIR)) for path in _FIXTURES]


def _signature(node: Node) -> object:
    """A layout-independent structure signature: named node types plus leaf text, with comments and
    anonymous tokens excluded. Invariant to the formatter's whitespace / ``GMAT`` / ``;``
    auto-fixes, but sensitive to any added, dropped, reordered, or altered resource, field, or
    command."""
    if node.type == "comment":
        return None
    children = [sig for child in node.named_children if (sig := _signature(child)) is not None]
    if children:
        return (node.type, tuple(children))
    text = node.text.decode("utf-8") if node.text is not None else ""
    if node.type == "unquoted_value":
        text = text.rstrip()  # the formatter strips the rest-of-line value's trailing whitespace
    elif node.type == "script_body":
        text = text.replace("\r\n", "\n").replace("\r", "\n")  # opaque body: EOL is normalised
    return (node.type, text)


def _comments(node: Node) -> list[str]:
    """Every comment's text (trailing whitespace stripped), in tree order."""
    found: list[str] = []
    stack = [node]
    while stack:
        current = stack.pop()
        if current.type == "comment" and current.text is not None:
            found.append(current.text.decode("utf-8").rstrip())
        stack.extend(current.children)
    return sorted(found)


def _read(fixture: Path) -> str:
    return fixture.read_bytes().decode("utf-8")


@pytest.mark.corpus
@pytest.mark.parametrize("fixture", _FIXTURES, ids=_IDS)
def test_format_output_parses_cleanly(fixture: Path) -> None:
    assert not parse(format(_read(fixture))).has_errors


@pytest.mark.corpus
@pytest.mark.parametrize("fixture", _FIXTURES, ids=_IDS)
def test_format_is_idempotent(fixture: Path) -> None:
    once = format(_read(fixture))
    assert format(once) == once


@pytest.mark.corpus
@pytest.mark.parametrize("fixture", _FIXTURES, ids=_IDS)
def test_format_preserves_structure(fixture: Path) -> None:
    source = _read(fixture)
    assert _signature(parse(source).root_node) == _signature(parse(format(source)).root_node)


@pytest.mark.corpus
@pytest.mark.parametrize("fixture", _FIXTURES, ids=_IDS)
def test_format_preserves_comments(fixture: Path) -> None:
    source = _read(fixture)
    assert _comments(parse(source).root_node) == _comments(parse(format(source)).root_node)


@pytest.mark.corpus
@pytest.mark.parametrize("fixture", _FIXTURES, ids=_IDS)
def test_format_accepts_tree_and_script_equivalently(fixture: Path) -> None:
    """A pre-parsed :class:`Tree` / :class:`Script` formats identically to the raw text."""
    source = _read(fixture)
    expected = format(source)
    assert format(parse(source)) == expected
    assert format(Script.parse(source)) == expected


@pytest.mark.corpus
def test_format_changes_something_across_the_corpus() -> None:
    """Sanity floor: canonicalisation is not a no-op — at least some fixtures are rewritten."""
    assert any(format(_read(fixture)) != _read(fixture) for fixture in _FIXTURES)
