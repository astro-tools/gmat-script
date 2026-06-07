"""Corpus acceptance harness and the byte-exact identity invariant (D6 / D7).

Every fixture under ``tests/data/corpus/`` — the hand-written lexical fixtures plus the full stock
GMAT R2026a sample corpus committed under ``gmat-r2026a/`` (162 ``.script`` + 9 ``.gmf``; see that
directory's ``PROVENANCE.md`` / ``LICENSE``) — must parse with zero ``ERROR``/``MISSING`` nodes (D7)
and re-emit byte-for-byte: concatenating every leaf token together with the interstitial layout
between them must reproduce the source exactly (D6). The stock corpus is the grammar's acceptance
oracle (#2).

``test_corpus_inventory`` asserts the stock corpus's exact file counts so a missing or truncated
checkout fails loudly instead of collecting zero parametrised cases and passing vacuously.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from gmat_script import parse

if TYPE_CHECKING:
    from collections.abc import Iterator

    from tree_sitter import Node

_CORPUS_DIR = Path(__file__).parent / "data" / "corpus"
_STOCK_DIR = _CORPUS_DIR / "gmat-r2026a"

# Expected stock-corpus file counts (see gmat-r2026a/PROVENANCE.md). Asserted by
# test_corpus_inventory so an incomplete corpus fails the build rather than silently shrinking the
# parametrised suite.
_EXPECTED_STOCK_SCRIPTS = 162
_EXPECTED_STOCK_GMF = 9

_FIXTURES = sorted([*_CORPUS_DIR.rglob("*.script"), *_CORPUS_DIR.rglob("*.gmf")])
_IDS = [str(p.relative_to(_CORPUS_DIR)) for p in _FIXTURES]


def _iter_leaves(node: Node) -> Iterator[Node]:
    """Yield every leaf token (named and anonymous) under *node*, in source order."""
    if node.child_count == 0:
        yield node
        return
    for child in node.children:
        yield from _iter_leaves(child)


def _reconstruct(root: Node, source: bytes) -> bytes:
    """Stitch leaf tokens back together with the interstitial layout (whitespace, comments, `...`).

    The leaves carry the tokens; the bytes between consecutive leaves are the layout tree-sitter
    keeps as between-token text. Concatenating them in source order must reproduce the input (D6).
    """
    out = bytearray()
    cursor = 0
    for leaf in _iter_leaves(root):
        out += source[cursor : leaf.start_byte]  # interstitial layout before this token
        out += source[leaf.start_byte : leaf.end_byte]  # the token itself
        cursor = leaf.end_byte
    out += source[cursor:]  # trailing layout after the last token
    return bytes(out)


def test_corpus_inventory() -> None:
    """The committed stock corpus is present and complete — the truncation guard."""
    scripts = list(_STOCK_DIR.rglob("*.script"))
    gmf = list(_STOCK_DIR.rglob("*.gmf"))
    assert len(scripts) == _EXPECTED_STOCK_SCRIPTS, (
        f"expected {_EXPECTED_STOCK_SCRIPTS} stock .script files, found {len(scripts)}"
    )
    assert len(gmf) == _EXPECTED_STOCK_GMF, (
        f"expected {_EXPECTED_STOCK_GMF} stock .gmf files, found {len(gmf)}"
    )


@pytest.mark.corpus
@pytest.mark.parametrize("fixture", _FIXTURES, ids=_IDS)
def test_fixture_parses_without_errors(fixture: Path) -> None:
    tree = parse(fixture.read_bytes().decode("utf-8"))
    if tree.has_errors:
        first = tree.errors[0]
        pytest.fail(
            f"{fixture.name}: {len(tree.errors)} ERROR/MISSING node(s); "
            f"first {first.type} at line {first.start.line}, column {first.start.column}"
        )


@pytest.mark.corpus
@pytest.mark.parametrize("fixture", _FIXTURES, ids=_IDS)
def test_fixture_roundtrips_byte_for_byte(fixture: Path) -> None:
    source = fixture.read_bytes()
    tree = parse(source.decode("utf-8"))
    assert _reconstruct(tree.root_node, source) == source, f"{fixture.name} did not round-trip"
