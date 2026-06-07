#!/usr/bin/env python
"""Validate the GMAT script corpus and log its file/error counts — the CI parse-coverage gate.

Walks every ``.script`` / ``.gmf`` fixture under ``tests/data/corpus/`` (the hand-written lexical
fixtures and the committed stock GMAT R2026a corpus under ``gmat-r2026a/``), parses each through the
public :func:`gmat_script.parse` API, and prints an explicit file/error count summary so a silently
truncated corpus is impossible to miss in the CI log. Exits non-zero if any file has an
``ERROR``/``MISSING`` node, fails the byte-for-byte round-trip (D6), or if the stock corpus is
incomplete.

Run from anywhere: ``python tests/check_corpus.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from gmat_script import parse

if TYPE_CHECKING:
    from collections.abc import Iterator

    from tree_sitter import Node

_CORPUS_DIR = Path(__file__).resolve().parent / "data" / "corpus"
_STOCK_DIR = _CORPUS_DIR / "gmat-r2026a"

# Expected stock-corpus file counts (see gmat-r2026a/PROVENANCE.md) — the truncation guard.
_EXPECTED_STOCK_SCRIPTS = 162
_EXPECTED_STOCK_GMF = 9


def _iter_leaves(node: Node) -> Iterator[Node]:
    """Yield every leaf token (named and anonymous) under *node*, in source order."""
    if node.child_count == 0:
        yield node
        return
    for child in node.children:
        yield from _iter_leaves(child)


def _reconstruct(root: Node, source: bytes) -> bytes:
    """Re-emit the source by stitching leaf tokens together with the interstitial layout (D6)."""
    out = bytearray()
    cursor = 0
    for leaf in _iter_leaves(root):
        out += source[cursor : leaf.start_byte]
        out += source[leaf.start_byte : leaf.end_byte]
        cursor = leaf.end_byte
    out += source[cursor:]
    return bytes(out)


def main() -> int:
    fixtures = sorted([*_CORPUS_DIR.rglob("*.script"), *_CORPUS_DIR.rglob("*.gmf")])
    stock_scripts = sorted(_STOCK_DIR.rglob("*.script"))
    stock_gmf = sorted(_STOCK_DIR.rglob("*.gmf"))
    hand_written = len(fixtures) - len(stock_scripts) - len(stock_gmf)

    parse_errors: list[str] = []
    roundtrip_failures: list[str] = []
    for path in fixtures:
        rel = path.relative_to(_CORPUS_DIR)
        source = path.read_bytes()
        tree = parse(source.decode("utf-8"))
        if tree.has_errors:
            first = tree.errors[0]
            parse_errors.append(f"{rel} ({first.type} at line {first.start.line})")
        if _reconstruct(tree.root_node, source) != source:
            roundtrip_failures.append(str(rel))

    print(
        f"corpus: {len(stock_scripts)} .script + {len(stock_gmf)} .gmf stock "
        f"(+{hand_written} hand-written) = {len(fixtures)} files parsed"
    )
    print(f"  ERROR/MISSING nodes:    {len(parse_errors)} file(s)")
    print(f"  round-trip mismatches:  {len(roundtrip_failures)} file(s)")

    ok = True
    if len(stock_scripts) != _EXPECTED_STOCK_SCRIPTS or len(stock_gmf) != _EXPECTED_STOCK_GMF:
        print(
            f"FAIL: stock corpus incomplete — expected {_EXPECTED_STOCK_SCRIPTS} .script + "
            f"{_EXPECTED_STOCK_GMF} .gmf under gmat-r2026a/",
            file=sys.stderr,
        )
        ok = False
    for label in parse_errors:
        print(f"FAIL: ERROR/MISSING node in {label}", file=sys.stderr)
    for label in roundtrip_failures:
        print(f"FAIL: byte-for-byte round-trip mismatch in {label}", file=sys.stderr)
    if parse_errors or roundtrip_failures:
        ok = False

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
