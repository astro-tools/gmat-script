"""Corpus parse-coverage — the v0.1 acceptance shape: every fixture parses with zero ERROR nodes.

Wired-up stub. The placeholder fixtures under ``tests/data/corpus/`` stand in for the stock GMAT
sample corpus until the grammar covers it; they only contain grammar-compatible content so the
parse path — and this CI job — is exercised for real rather than left empty.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_CORPUS_DIR = Path(__file__).parent / "data" / "corpus"
_FIXTURES = sorted(_CORPUS_DIR.glob("*.script")) + sorted(_CORPUS_DIR.glob("*.gmf"))


@pytest.mark.corpus
@pytest.mark.parametrize("fixture", _FIXTURES, ids=[p.name for p in _FIXTURES])
def test_fixture_parses_without_errors(fixture: Path) -> None:
    from tree_sitter import Language, Parser

    from gmat_script._grammar import language

    parser = Parser(Language(language()))
    tree = parser.parse(fixture.read_bytes())
    assert not tree.root_node.has_error, f"{fixture.name} produced ERROR nodes"
