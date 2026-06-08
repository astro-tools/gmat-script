"""Static, structural linting for GMAT mission scripts — the validation layer over parse+catalogue.

:func:`lint` runs a toggleable set of structural rules over the typed AST
(:class:`~gmat_script.Script`) and the field catalogue (:class:`~gmat_script.Catalog`), returning
typed :class:`Diagnostic` findings (rule code, :class:`Severity`, 1-indexed source range, message).
It checks *structure* — unknown types and fields, type / enum / reference-target contradictions,
duplicate names, and unused / undeclared / out-of-order references — never engine semantics
(convergence, physical validity), which are a downstream dry-run concern. Inline
``% gmat-script: disable[-line]`` comments suppress findings. The same rules back the
``gmat-script lint`` CLI.
"""

from __future__ import annotations

from .diagnostics import Diagnostic, Severity
from .engine import lint
from .registry import Rule
from .rules import RULES

__all__ = ["RULES", "Diagnostic", "Rule", "Severity", "lint"]
