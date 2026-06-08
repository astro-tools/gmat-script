"""Typed AST overlay over the v0.1 CST — typed nodes + dict-like access (issue #12).

This package layers a typed, read-only object model over the concrete syntax tree returned by
:func:`gmat_script.parse`. The entry point is :class:`Script`; it presents a parsed script as typed
:class:`Resource` objects with dict-like field access and an ordered, typed
:attr:`~Script.mission_sequence`. Field and operand values are coerced structurally
(:func:`coerce_value`) into the :data:`Value` union — :class:`ObjectRef` for references and
:class:`RawValue` for unstructured / computed forms.

Reads are a lossless *view*: a :class:`Script` re-emits an unmodified script byte-for-byte (D6).
It is also mutable — fields are set through a :class:`Resource`
(``script.spacecraft["Sat"]["SMA"] = 7000``) and resources / commands through :class:`Script`
methods, each edit splicing the source and re-parsing (:func:`emit_value` formats written literals,
shared with the canonical formatter). A corrupting edit raises :class:`MutationError`.
"""

from __future__ import annotations

from .commands import (
    Assignment,
    Command,
    ForStatement,
    FunctionCall,
    GenericCommand,
    IfStatement,
    OptimizeStatement,
    ScriptBlock,
    TargetStatement,
    WhileStatement,
    build_command,
)
from .edit import MutationError
from .literals import emit_value
from .resource import Resource, split_reference
from .script import Script
from .values import Array, ObjectRef, RawValue, Value, coerce_value

__all__ = [
    "Array",
    "Assignment",
    "Command",
    "ForStatement",
    "FunctionCall",
    "GenericCommand",
    "IfStatement",
    "MutationError",
    "ObjectRef",
    "OptimizeStatement",
    "RawValue",
    "Resource",
    "Script",
    "ScriptBlock",
    "TargetStatement",
    "Value",
    "WhileStatement",
    "build_command",
    "coerce_value",
    "emit_value",
    "split_reference",
]
