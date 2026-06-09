"""The language features, as pure functions over source text — the testable core of the server.

Each function takes a script's current text (plus a cursor position where relevant) and returns
``lsprotocol`` types, reusing the library's existing layers rather than reimplementing them:
diagnostics come from the linter and the parser's syntax errors, hover and completion from the field
catalogue, and definition / references / document-symbol from the tree-sitter queries. The server
(``server.py``) is a thin pygls shell over these; keeping the logic here means it is unit-testable
without a running protocol connection, and that the ≥90% coverage bar is met by ordinary tests.

Everything is best-effort on a broken parse — the tree-sitter error recovery still yields a usable
tree (D7) — so an in-progress edit degrades gracefully instead of raising.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from lsprotocol import types as lsp

from ..ast.base import node_text
from ..ast.script import Script
from ..catalog import load_catalog
from ..format import format as format_source
from ..lint import Severity, lint
from ..lint.references import reference_root
from ..parser import parse
from . import queries
from .conversions import LineIndex

if TYPE_CHECKING:
    from tree_sitter import Node

    from ..catalog import Catalog, FieldSpec
    from ..parser import Tree

_DIAGNOSTIC_SOURCE = "gmat-script"

_SEVERITY: dict[Severity, lsp.DiagnosticSeverity] = {
    Severity.ERROR: lsp.DiagnosticSeverity.Error,
    Severity.WARNING: lsp.DiagnosticSeverity.Warning,
    Severity.INFO: lsp.DiagnosticSeverity.Information,
}

# A trailing ``resource.partial`` field-access at the cursor (a completion context). The optional
# ``=`` look-ahead is excluded so a value position falls through to ``_VALUE_CONTEXT`` instead.
_FIELD_CONTEXT = re.compile(r"(?P<object>[A-Za-z_]\w*)\s*\.\s*\w*$")
# A trailing ``resource.field = …`` value position at the cursor (enum / object-reference values).
_VALUE_CONTEXT = re.compile(r"(?P<object>[A-Za-z_]\w*)\s*\.\s*(?P<field>\w+)\s*=\s*[^=]*$")


# ----------------------------------------------------------------------------
# diagnostics


def diagnostics_for(source: str) -> list[lsp.Diagnostic]:
    """Diagnostics for *source*: the linter's findings, or its syntax errors if the parse is broken.

    The linter reduces a script with syntax errors to ``syntax-error`` diagnostics alone (D7),
    so this returns live syntax feedback on a half-typed buffer and structural findings on a clean
    one.
    """
    lines = LineIndex(source)
    return [
        lsp.Diagnostic(
            range=lines.range_from_internal(finding.start, finding.end),
            message=finding.message,
            severity=_SEVERITY[finding.severity],
            code=finding.rule,
            source=_DIAGNOSTIC_SOURCE,
        )
        for finding in lint(source)
    ]


# ----------------------------------------------------------------------------
# shared per-request analysis


@dataclass(frozen=True, slots=True)
class _Analysis:
    """Everything the tree-driven features share for one request, computed once."""

    tree: Tree
    script: Script
    lines: LineIndex
    catalog: Catalog

    @property
    def types_by_name(self) -> dict[str, str]:
        """Each declared resource name mapped to its GMAT type (for hover / completion)."""
        return {name: resource.type for name, resource in self.script.resources.items()}


def _analyze(source: str) -> _Analysis:
    """Parse *source* and assemble the shared per-request analysis (tolerates a broken parse)."""
    tree = parse(source)
    return _Analysis(tree, Script(tree), LineIndex(source), load_catalog())


def _identifier_at(analysis: _Analysis, position: lsp.Position) -> Node | None:
    """The ``identifier`` token under *position*, or ``None`` if the cursor is not on one.

    Tries the point itself, then the byte just before it, so a cursor resting on an identifier's
    trailing edge (where the smallest node is the following token) still resolves to the identifier.
    """
    row, column = analysis.lines.point_from_position(position)
    root = analysis.tree.root_node
    candidates = [(row, column)] + ([(row, column - 1)] if column > 0 else [])
    for point in candidates:
        node = root.descendant_for_point_range(point, point)
        if node is not None and node.type == "identifier":
            return node
    return None


# ----------------------------------------------------------------------------
# hover


def hover_at(source: str, position: lsp.Position) -> lsp.Hover | None:
    """Hover documentation for the identifier under the cursor.

    Resolves, in order: a ``resource.field`` property (the catalogue field doc), a ``Create`` type
    name (the resource-type summary), and a declared resource name (its type). ``None`` if the
    cursor is not on a recognised identifier.
    """
    analysis = _analyze(source)
    node = _identifier_at(analysis, position)
    if node is None:
        return None
    markdown = (
        _field_doc(analysis, node) or _type_doc(analysis, node) or _resource_doc(analysis, node)
    )
    if markdown is None:
        return None
    return lsp.Hover(
        contents=lsp.MarkupContent(kind=lsp.MarkupKind.Markdown, value=markdown),
        range=analysis.lines.range_of_node(node),
    )


def _field_doc(analysis: _Analysis, node: Node) -> str | None:
    """Catalogue documentation when *node* is the ``property`` of a ``resource.field`` reference."""
    parent = node.parent
    if parent is None or parent.type != "member_expression":
        return None
    property_node = parent.child_by_field_name("property")
    if property_node is None or property_node.id != node.id:
        return None
    object_name = node_text(reference_root(parent))
    type_name = analysis.types_by_name.get(object_name)
    if type_name is None:
        return None
    spec = analysis.catalog.field(type_name, node_text(node))
    if spec is None:
        return None
    return _render_field(type_name, spec)


def _type_doc(analysis: _Analysis, node: Node) -> str | None:
    """A resource-type summary when *node* is the ``type`` of a ``Create`` command."""
    parent = node.parent
    if parent is None or parent.type != "create_command":
        return None
    type_node = parent.child_by_field_name("type")
    if type_node is None or type_node.id != node.id:
        return None
    name = node_text(node)
    if not analysis.catalog.has_type(name):
        return None
    field_count = len(analysis.catalog.fields(name))
    return f"**{name}** — GMAT resource type\n\n{field_count} catalogued field(s)."


def _resource_doc(analysis: _Analysis, node: Node) -> str | None:
    """A one-line summary when *node* names a declared resource."""
    name = node_text(node)
    type_name = analysis.types_by_name.get(name)
    if type_name is None:
        return None
    return f"**{name}** — `{type_name}`"


def _render_field(type_name: str, spec: FieldSpec) -> str:
    """Markdown hover body for a catalogue field spec."""
    unit = f" ({spec.unit})" if spec.unit else ""
    lines = [f"**{type_name}.{spec.name}** — `{spec.type}`{unit}"]
    details: list[str] = []
    if spec.default is not None:
        details.append(f"Default: `{spec.default}`")
    if spec.allowed:
        details.append("Allowed: " + ", ".join(f"`{value}`" for value in spec.allowed))
    if spec.ref_target:
        details.append(f"References a `{spec.ref_target}`.")
    if spec.read_only:
        details.append("_Read-only._")
    if details:
        lines.append("")
        lines.extend(details)
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# definition / references


def definition_ranges(source: str, position: lsp.Position) -> list[lsp.Range]:
    """Ranges of the definition(s) of the resource / symbol named under the cursor (same file)."""
    analysis = _analyze(source)
    node = _identifier_at(analysis, position)
    if node is None:
        return []
    name = node_text(node)
    return [
        analysis.lines.range_of_node(definition)
        for definition in queries.definition_nodes(analysis.tree.root_node)
        if node_text(definition) == name
    ]


def reference_ranges(
    source: str, position: lsp.Position, *, include_declaration: bool
) -> list[lsp.Range]:
    """Ranges of every reference to the name under the cursor, in source order.

    With *include_declaration* false, occurrences that are the symbol's own declaration name are
    dropped (the query captures a declaration name as both a definition and a reference).
    """
    analysis = _analyze(source)
    node = _identifier_at(analysis, position)
    if node is None:
        return []
    name = node_text(node)
    root = analysis.tree.root_node
    matches = [use for use in queries.reference_nodes(root) if node_text(use) == name]
    if not include_declaration:
        declaration_ids = {
            definition.id
            for definition in queries.definition_nodes(root)
            if node_text(definition) == name
        }
        matches = [use for use in matches if use.id not in declaration_ids]
    ordered = sorted(matches, key=lambda use: use.start_byte)
    return [analysis.lines.range_of_node(use) for use in ordered]


# ----------------------------------------------------------------------------
# document symbols


def document_symbols(source: str) -> list[lsp.DocumentSymbol]:
    """The document outline: each ``Create``'d resource and GmatFunction header, in source order."""
    analysis = _analyze(source)
    symbols: list[lsp.DocumentSymbol] = []
    for tag in queries.symbol_tags(analysis.tree.root_node):
        kind = lsp.SymbolKind.Class if tag.kind == "class" else lsp.SymbolKind.Function
        symbols.append(
            lsp.DocumentSymbol(
                name=tag.name,
                kind=kind,
                range=analysis.lines.range_of_node(tag.definition_node),
                selection_range=analysis.lines.range_of_node(tag.name_node),
                detail=_symbol_detail(tag),
            )
        )
    return symbols


def _symbol_detail(tag: queries.SymbolTag) -> str | None:
    """The resource's GMAT type for a class tag (its ``Create`` type); ``None`` for a function."""
    if tag.kind != "class":
        return None
    type_node = tag.definition_node.child_by_field_name("type")
    return node_text(type_node) if type_node is not None else None


# ----------------------------------------------------------------------------
# completion


def completions_at(source: str, position: lsp.Position) -> list[lsp.CompletionItem]:
    """Completions at the cursor: enum / reference values, field names, or resource names.

    The context is read from the text before the cursor on its line: ``resource.field =`` offers the
    field's enum values (or candidate resources for an object-reference field), ``resource.`` offers
    that resource type's field names, and anything else offers the declared resource names.
    """
    analysis = _analyze(source)
    prefix = analysis.lines.prefix_before(position)

    value = _VALUE_CONTEXT.search(prefix)
    if value is not None:
        return _value_completions(analysis, value.group("object"), value.group("field"))

    field = _FIELD_CONTEXT.search(prefix)
    if field is not None:
        type_name = analysis.types_by_name.get(field.group("object"))
        return _field_completions(analysis, type_name) if type_name else []

    return _resource_completions(analysis)


def _value_completions(
    analysis: _Analysis, object_name: str, field: str
) -> list[lsp.CompletionItem]:
    """Completions for a ``resource.field =`` value: enum members, else candidate references."""
    type_name = analysis.types_by_name.get(object_name)
    if type_name is None:
        return _resource_completions(analysis)
    enum = analysis.catalog.enum_values(type_name, field)
    if enum:
        return [
            lsp.CompletionItem(label=value, kind=lsp.CompletionItemKind.EnumMember)
            for value in enum
        ]
    target = analysis.catalog.ref_target(type_name, field)
    return _resource_completions(analysis, target)


def _field_completions(analysis: _Analysis, type_name: str) -> list[lsp.CompletionItem]:
    """The catalogued field names of *type_name* as completion items."""
    items: list[lsp.CompletionItem] = []
    for field in analysis.catalog.fields(type_name):
        spec = analysis.catalog.field(type_name, field)
        items.append(
            lsp.CompletionItem(
                label=field,
                kind=lsp.CompletionItemKind.Field,
                detail=spec.type if spec is not None else None,
            )
        )
    return items


def _resource_completions(
    analysis: _Analysis, target_type: str | None = None
) -> list[lsp.CompletionItem]:
    """Declared resource names as completion items, optionally filtered to a target GMAT type.

    The match prefers the catalogue's alias resolution, falling back to an exact type-name match so
    a reference whose target type the catalogue does not carry (an estimation / plugin type) still
    narrows correctly instead of degrading to every resource.
    """
    wanted = analysis.catalog.resolve(target_type) if target_type else None
    items: list[lsp.CompletionItem] = []
    for name, resource in analysis.script.resources.items():
        if target_type is not None and not _type_matches(
            analysis, resource.type, target_type, wanted
        ):
            continue
        items.append(
            lsp.CompletionItem(
                label=name, kind=lsp.CompletionItemKind.Variable, detail=resource.type
            )
        )
    return items


def _type_matches(analysis: _Analysis, resource_type: str, target: str, wanted: str | None) -> bool:
    """Whether *resource_type* satisfies a *target* GMAT type (canonical match, else exact name)."""
    resolved = analysis.catalog.resolve(resource_type)
    if wanted is not None and resolved is not None:
        return resolved == wanted
    return resource_type == target


# ----------------------------------------------------------------------------
# formatting


def format_edits(source: str) -> list[lsp.TextEdit]:
    """A whole-document edit re-emitting *source* canonically, or none if it is already canonical.

    The formatter is whole-document and refuses a script with syntax errors (D14); a buffer it
    cannot format — a syntax error, or an expression nested deep enough to exhaust the recursion
    limit — or one already canonical yields no edit, so this is also the range-formatting result.
    """
    try:
        formatted = format_source(source)
    except (ValueError, TypeError, RecursionError):
        return []
    if formatted == source:
        return []
    lines = LineIndex(source)
    whole = lsp.Range(start=lsp.Position(line=0, character=0), end=lines.end_position())
    return [lsp.TextEdit(range=whole, new_text=formatted)]
