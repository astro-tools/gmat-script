"""Corpus parse-coverage and the byte-exact identity invariant (D6).

Every fixture under ``tests/data/corpus/`` must parse with zero ``ERROR``/``MISSING`` nodes, and
concatenating its leaf tokens together with the interstitial layout between them must reproduce the
source byte-for-byte. The fixtures are hand-written configuration sections covering the lexical core
and configuration grammar (#4); the full stock GMAT sample corpus is wired in a later milestone.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

    from tree_sitter import Node

_CORPUS_DIR = Path(__file__).parent / "data" / "corpus"
_FIXTURES = sorted(_CORPUS_DIR.glob("*.script")) + sorted(_CORPUS_DIR.glob("*.gmf"))


def _iter_leaves(node: Node) -> Iterator[Node]:
    """Yield every leaf token (named and anonymous) under *node*, in source order."""
    if node.child_count == 0:
        yield node
        return
    for child in node.children:
        yield from _iter_leaves(child)


def _reconstruct(tree_root: Node, source: bytes) -> bytes:
    """Stitch leaf tokens back together with the interstitial layout (whitespace, comments, `...`).

    The leaves carry the tokens; the bytes between consecutive leaves are the layout tree-sitter
    keeps as between-token text. Concatenating them in source order must reproduce the input (D6).
    """
    out = bytearray()
    cursor = 0
    for leaf in _iter_leaves(tree_root):
        out += source[cursor : leaf.start_byte]  # interstitial layout before this token
        out += source[leaf.start_byte : leaf.end_byte]  # the token itself
        cursor = leaf.end_byte
    out += source[cursor:]  # trailing layout after the last token
    return bytes(out)


def _has_missing(node: Node) -> bool:
    if node.is_missing:
        return True
    return any(_has_missing(child) for child in node.children)


@pytest.mark.corpus
@pytest.mark.parametrize("fixture", _FIXTURES, ids=[p.name for p in _FIXTURES])
def test_fixture_parses_without_errors(fixture: Path) -> None:
    from tree_sitter import Language, Parser

    from gmat_script._grammar import language

    parser = Parser(Language(language()))
    tree = parser.parse(fixture.read_bytes())
    assert not tree.root_node.has_error, f"{fixture.name} produced ERROR nodes"
    assert not _has_missing(tree.root_node), f"{fixture.name} produced MISSING nodes"


@pytest.mark.corpus
@pytest.mark.parametrize("fixture", _FIXTURES, ids=[p.name for p in _FIXTURES])
def test_fixture_roundtrips_byte_for_byte(fixture: Path) -> None:
    from tree_sitter import Language, Parser

    from gmat_script._grammar import language

    source = fixture.read_bytes()
    parser = Parser(Language(language()))
    tree = parser.parse(source)
    assert _reconstruct(tree.root_node, source) == source, f"{fixture.name} did not round-trip"
