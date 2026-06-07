"""The vendored, compiled tree-sitter-gmat grammar.

The ``_binding`` extension module is compiled from the grammar's ``parser.c`` + Python binding at
wheel-build time by the project's build hook and shipped *inside* the wheel, so loading the grammar
needs no C or Node toolchain at install time. :func:`language` returns the grammar's language
capsule, which the ``tree-sitter`` runtime wraps with ``tree_sitter.Language(...)``. See the design
decisions (D2 / D9 / D12).
"""

from __future__ import annotations

from ._binding import language

__all__ = ["language"]
