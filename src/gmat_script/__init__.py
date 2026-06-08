"""gmat-script — parse, format, lint, and edit GMAT mission scripts from Python.

The whole stack operates on script *text*; nothing here requires a GMAT install. ``parse`` is the
v0.1 entry point returning the concrete syntax tree; :class:`Script` is the v0.2 typed overlay over
it (typed resources, dict-like field access, an ordered mission sequence). The formatter and linter
are re-exported here as they land. See the design decisions under ``docs/design/`` for the contract
this package implements.
"""

from __future__ import annotations

from .ast import ObjectRef, RawValue, Script
from .parser import ErrorNode, Position, Tree, parse

__all__ = ["ErrorNode", "ObjectRef", "Position", "RawValue", "Script", "Tree", "parse"]
__version__ = "0.1.1"
