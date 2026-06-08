"""gmat-script — parse, format, lint, and edit GMAT mission scripts from Python.

The whole stack operates on script *text*; nothing here requires a GMAT install. ``parse`` is the
entry point returning the concrete syntax tree; :class:`Script` is the typed overlay over it (typed
resources, dict-like field access, an ordered mission sequence) and the mutation root — editing a
field, resource, or command splices the source and re-parses, raising :class:`MutationError` on a
corrupting edit. The formatter and linter are re-exported here as they land. See the design
decisions under ``docs/design/`` for the contract this package implements.
"""

from __future__ import annotations

from .ast import Array, MutationError, ObjectRef, RawValue, Script
from .format import format
from .parser import ErrorNode, Position, Tree, parse

__all__ = [
    "Array",
    "ErrorNode",
    "MutationError",
    "ObjectRef",
    "Position",
    "RawValue",
    "Script",
    "Tree",
    "format",
    "parse",
]
__version__ = "0.1.1"
