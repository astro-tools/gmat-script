"""GMAT mission script grammar for tree-sitter.

This package is the self-contained, standalone form of the grammar binding (for consumers that
want the grammar without the gmat-script Python library). The gmat-script library does not import
it; it vendors the same compiled grammar into its own wheel. See docs/design/decisions.md (D1/D12).
"""

from ._binding import language

__all__ = ["language"]
