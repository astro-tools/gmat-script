"""Parse GMAT mission scripts into a concrete syntax tree.

Scaffold stub. The public :func:`parse` entry point is defined here so the package's surface and
import path are stable; the tree-sitter grammar load and the returned tree wrapper are wired once
the grammar is in place, at which point this module gains the real implementation. The compiled
grammar it loads is vendored under :mod:`gmat_script._grammar` (see the design decisions).
"""

from __future__ import annotations


def parse(source: str) -> object:
    """Parse GMAT script *source* and return its syntax tree.

    Not implemented yet: the grammar is being built up before this is wired to load it. The
    signature and import path are stable now so downstream code can depend on them.

    :param source: the script text to parse.
    :raises NotImplementedError: always, until the grammar load is wired in.
    """
    raise NotImplementedError(
        "parse() is not implemented yet — the grammar is being built up before it is wired in."
    )
