"""Typed AST overlay over the v0.1 CST — typed nodes + dict-like access (issue #12).

This package layers a typed, read-only object model over the concrete syntax tree returned by
:func:`gmat_script.parse`. The entry point is :class:`Script`; it presents a parsed script as typed
:class:`Resource` objects with dict-like field access and an ordered, typed
:attr:`~Script.mission_sequence`. Field and operand values are coerced structurally
(:func:`coerce_value`) into the :data:`Value` union — :class:`ObjectRef` for references and
:class:`RawValue` for unstructured / computed forms.

The overlay is a *view*: it holds no state beyond the wrapped tree, so it can never desync from the
CST, and re-emitting an unmodified script is byte-for-byte exact (D5 / D6). It is read-only —
mutation is the v0.2 mutation API (#13), and the canonical formatter is #14.
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
from .resource import Resource, split_reference
from .script import Script
from .values import ObjectRef, RawValue, Value, coerce_value

__all__ = [
    "Assignment",
    "Command",
    "ForStatement",
    "FunctionCall",
    "GenericCommand",
    "IfStatement",
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
    "split_reference",
]
