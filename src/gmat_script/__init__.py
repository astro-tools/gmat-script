"""gmat-script — parse, format, lint, and edit GMAT mission scripts from Python.

The whole stack operates on script *text*; nothing here requires a GMAT install. ``parse`` is the
v0.1 entry point; the formatter and linter are re-exported here as they land. See the design
decisions under ``docs/design/`` for the contract this package implements.
"""

from __future__ import annotations

from .parser import ErrorNode, Position, Tree, parse

__all__ = ["ErrorNode", "Position", "Tree", "parse"]
__version__ = "0.1.1"
