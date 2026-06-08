"""The linter entry point: parse (if needed), run the rules, suppress, and sort.

:func:`lint` accepts source text, a parsed :class:`~gmat_script.Tree`, or a typed
:class:`~gmat_script.Script`, and returns the findings as a sorted list of
:class:`~gmat_script.lint.diagnostics.Diagnostic`. A script with *syntax* errors short-circuits to
those errors alone (rule code ``syntax-error``): the typed model is unreliable on a broken parse, so
the structural rules do not run — fix the syntax first, as the ``parse`` gate reports it (D7).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..ast.script import Script
from ..catalog import load_catalog
from ..parser import Tree, parse
from .context import LintContext
from .diagnostics import Diagnostic, Severity
from .registry import resolve_rules
from .rules import RULES
from .suppression import filter_diagnostics, parse_suppressions

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = ["lint"]

LintInput = str | Tree | Script


def lint(
    target: LintInput,
    *,
    select: Iterable[str] | None = None,
    ignore: Iterable[str] | None = None,
    target_version: str | None = None,
) -> list[Diagnostic]:
    """Lint *target* and return its diagnostics in source order.

    :param target: GMAT script source text, a parsed :class:`~gmat_script.Tree`, or a
        :class:`~gmat_script.Script` overlay.
    :param select: if given, run only these rule codes (an allow-list).
    :param ignore: rule codes to skip (a deny-list applied after *select*).
    :param target_version: GMAT catalogue version to lint against; defaults to the newest shipped
        catalogue (D11).
    :returns: the findings, sorted by position then rule code; empty if the script is clean.
    :raises ValueError: if *select* / *ignore* names an unknown rule code.
    """
    script, tree, source = _resolve_input(target)
    if tree.has_errors:
        return _syntax_diagnostics(tree)
    if script is None:
        script = Script(tree)

    context = LintContext(script, tree, load_catalog(target_version))
    diagnostics: list[Diagnostic] = []
    for rule in resolve_rules(RULES, select, ignore):
        diagnostics.extend(rule.check(context))

    diagnostics = filter_diagnostics(diagnostics, parse_suppressions(source))
    diagnostics.sort(key=lambda diagnostic: diagnostic.sort_key())
    return diagnostics


def _resolve_input(target: LintInput) -> tuple[Script | None, Tree, str]:
    """Normalise the input to ``(script_or_None, tree, source_text)``."""
    if isinstance(target, Script):
        return target, target.tree, target.to_source()
    if isinstance(target, Tree):
        return None, target, target.text
    if isinstance(target, str):
        return None, parse(target), target
    raise TypeError(f"lint() expects str, Tree, or Script, not {type(target).__name__}")


def _syntax_diagnostics(tree: Tree) -> list[Diagnostic]:
    """Map the parse tree's syntax errors to ``syntax-error`` diagnostics (always reported)."""
    return [
        Diagnostic("syntax-error", Severity.ERROR, error.message, error.start, error.end)
        for error in tree.errors
    ]
