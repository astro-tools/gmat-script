"""The v0.3 lint rule set — nine structural checks over the typed AST and the field catalogue.

Each rule is a small generator of :class:`~gmat_script.lint.diagnostics.Diagnostic`; the
:class:`Rule` wrappers in :data:`RULES` make them individually toggleable. The checks are purely
*structural* (declarations, fields, references) — no engine semantics — and are tuned for zero false
positives on the R2026a stock corpus, degrading gracefully (no finding) wherever
the catalogue lacks data for a type (plugin resources, nested sub-object field paths).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ..ast.values import Array, ObjectRef, RawValue, coerce_value
from .diagnostics import Diagnostic, Severity, node_range
from .known import GMAT_BUILTINS, KNOWN_PLUGIN_TYPES
from .references import object_reference_uses
from .registry import Rule

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ..ast.values import Value
    from ..catalog import FieldSpec
    from .context import FieldAssignment, LintContext

__all__ = ["RULES"]


# -- shared helpers --------------------------------------------------------------------------------


def _flat_config_fields(ctx: LintContext) -> Iterator[tuple[FieldAssignment, str]]:
    """Configuration field assignments with a single segment on a *catalogued* resource type.

    Nested sub-object paths (``FM.GravityField.Earth.Degree``) and resources of an uncatalogued type
    (plugins) are skipped — neither has a flat catalogue spec to check against.
    """
    for assignment in ctx.config_field_assignments:
        if len(assignment.segments) != 1:
            continue
        resource_type = ctx.resource_type(assignment.resource)
        if resource_type is None or not ctx.catalog.has_type(resource_type):
            continue
        yield assignment, resource_type


def _value_kind(value: Value) -> str:
    """A coarse value-shape tag for ``type-mismatch`` (bool is tested before int, its subclass)."""
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "number"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, ObjectRef):
        return "reference"
    if isinstance(value, RawValue):
        return "expression"
    if isinstance(value, Array):
        return "array"
    return "list"


_KIND_DESCRIPTION = {
    "bool": "a boolean",
    "number": "a number",
    "string": "a quoted string",
    "array": "an array",
    "list": "a brace-list",
}


# -- declaration / field rules ---------------------------------------------------------------------


def _unknown_resource_type(ctx: LintContext) -> Iterator[Diagnostic]:
    for decl in ctx.declarations:
        if ctx.catalog.has_type(decl.type) or decl.type in KNOWN_PLUGIN_TYPES:
            continue
        start, end = node_range(decl.type_node)
        yield Diagnostic(
            "unknown-resource-type",
            Severity.ERROR,
            f"unknown resource type {decl.type!r}",
            start,
            end,
        )


def _unknown_field(ctx: LintContext) -> Iterator[Diagnostic]:
    for assignment, resource_type in _flat_config_fields(ctx):
        field = assignment.segments[0]
        if ctx.catalog.field(resource_type, field) is not None:
            continue
        start, end = node_range(assignment.field_node)
        yield Diagnostic(
            "unknown-field",
            Severity.WARNING,
            f"unknown field {field!r} on {resource_type} {assignment.resource!r}",
            start,
            end,
        )


def _duplicate_name(ctx: LintContext) -> Iterator[Diagnostic]:
    seen: dict[str, int] = {}
    for decl in ctx.declarations:
        first_line = seen.get(decl.name)
        if first_line is not None:
            start, end = node_range(decl.name_node)
            yield Diagnostic(
                "duplicate-name",
                Severity.ERROR,
                f"resource {decl.name!r} is already declared (first at line {first_line})",
                start,
                end,
            )
        else:
            seen[decl.name] = decl.name_node.start_point.row + 1


# -- value rules -----------------------------------------------------------------------------------


def _type_problem(spec: FieldSpec, value: Value) -> str | None:
    """A conservative, high-confidence type contradiction message, or ``None``.

    Only unambiguous cases are flagged — a number/string/bool/collection where the catalogue type
    plainly forbids it. References and raw expressions are always accepted (they may resolve to a
    parameter or compute), and ambiguous field types (enums, strings, colours, arrays, epochs) are
    left to other rules or not checked, to hold the zero-false-positive bar.
    """
    kind = _value_kind(value)
    described = _KIND_DESCRIPTION.get(kind)
    if described is None:  # reference / expression — never a confident mismatch
        return None
    if spec.type in ("real", "integer") and kind in ("string", "bool", "array", "list"):
        return f"field {spec.name!r} expects a number, got {described}"
    if spec.type == "bool" and kind in ("number", "string", "array", "list"):
        return f"field {spec.name!r} expects true or false, got {described}"
    if spec.type in ("object", "object_array") and kind in ("number", "bool"):
        return f"field {spec.name!r} expects an object reference, got {described}"
    return None


def _type_mismatch(ctx: LintContext) -> Iterator[Diagnostic]:
    for assignment, resource_type in _flat_config_fields(ctx):
        spec = ctx.catalog.field(resource_type, assignment.segments[0])
        if spec is None:
            continue
        message = _type_problem(spec, coerce_value(assignment.value_node))
        if message is None:
            continue
        start, end = node_range(assignment.value_node)
        yield Diagnostic("type-mismatch", Severity.WARNING, message, start, end)


def _enum_violation(ctx: LintContext) -> Iterator[Diagnostic]:
    for assignment, resource_type in _flat_config_fields(ctx):
        spec = ctx.catalog.field(resource_type, assignment.segments[0])
        if spec is None or spec.type != "enum" or not spec.allowed:
            continue
        value = coerce_value(assignment.value_node)
        if isinstance(value, ObjectRef):
            token = value.name
        elif isinstance(value, str):
            token = value
        else:
            continue  # numbers / expressions / collections are not enum tokens to check
        if token in spec.allowed:
            continue
        start, end = node_range(assignment.value_node)
        yield Diagnostic(
            "enum-violation",
            Severity.WARNING,
            f"{token!r} is not a valid {spec.name!r} value (allowed: {', '.join(spec.allowed)})",
            start,
            end,
        )


# -- relationship rules ----------------------------------------------------------------------------


_SELF_ACTIVE_CATEGORIES = frozenset({"Subscriber"})


def _unused_resource(ctx: LintContext) -> Iterator[Diagnostic]:
    references = ctx.value_references()
    for decl in ctx.declarations:
        if decl.name in references:
            continue
        spec = ctx.catalog.type_spec(decl.type)
        # Plugin / unknown types and self-active subscribers (which take effect without being
        # referenced) are never flagged; an opaque BeginScript block may use the name as raw text.
        if spec is None or spec.category in _SELF_ACTIVE_CATEGORIES:
            continue
        if any(_word_present(decl.name, text) for text in ctx.script_block_texts):
            continue
        start, end = node_range(decl.name_node)
        yield Diagnostic(
            "unused-resource",
            Severity.INFO,
            f"resource {decl.name!r} is created but never referenced",
            start,
            end,
        )


def _word_present(name: str, text: str) -> bool:
    """Whether *name* appears as a whole word in *text* (for BeginScript raw-text use detection)."""
    return re.search(rf"\b{re.escape(name)}\b", text) is not None


def _resolved_reference(ctx: LintContext, name: str) -> bool:
    """Whether *name* names something valid without a ``Create`` — builtin, type, or plugin type."""
    return (
        name in ctx.declared_names
        or name in GMAT_BUILTINS
        or name in KNOWN_PLUGIN_TYPES
        or ctx.catalog.has_type(name)
    )


def _undeclared_reference(ctx: LintContext) -> Iterator[Diagnostic]:
    for use in object_reference_uses(ctx):
        if _resolved_reference(ctx, use.name):
            continue
        start, end = node_range(use.node)
        yield Diagnostic(
            "undeclared-reference",
            Severity.ERROR,
            f"reference to undeclared resource {use.name!r} in {use.resource}.{use.field}",
            start,
            end,
        )


def _ref_target_mismatch(ctx: LintContext) -> Iterator[Diagnostic]:
    for use in object_reference_uses(ctx):
        actual = ctx.resource_type(use.name)
        if actual is None:
            continue  # undeclared (its own rule) or a builtin / type keyword
        if _target_compatible(ctx, actual, use.target):
            continue
        start, end = node_range(use.node)
        yield Diagnostic(
            "ref-target-mismatch",
            Severity.WARNING,
            f"{use.resource}.{use.field} expects a {use.target}, but {use.name!r} is a {actual}",
            start,
            end,
        )


# Object-reference targets are often *supertypes* (an abstract GMAT base) several concrete types
# satisfy — the catalogue stores only the concrete leaf type a resource is created as. A target
# is satisfied by an exact name, an alias-equal name, a type whose object-type *category* equals the
# target, or a concrete type listed for that supertype below. These supertype groupings are the ones
# the R2026a stock corpus exercises (validated to zero false positives); ``Parameter`` is handled
# separately as the universal "any object can supply a parameter" target.
_TARGET_SUBTYPES: dict[str, frozenset[str]] = {
    "FuelTank": frozenset({"ChemicalTank", "ElectricTank"}),
    "Thruster": frozenset({"ChemicalThruster", "ElectricThruster"}),
    "PowerSystem": frozenset({"SolarPowerSystem", "NuclearPowerSystem"}),
    "MeasurementModel": frozenset({"TrackingFileSet"}),
    "SpacePoint": frozenset(
        {
            "Spacecraft",
            "CelestialBody",
            "CalculatedPoint",
            "Barycenter",
            "LibrationPoint",
            "Formation",
        }
    ),
    # Estimator / simulator ``Propagator`` fields accept a spacecraft (corpus-observed).
    "PropSetup": frozenset({"Spacecraft"}),
}


def _target_compatible(ctx: LintContext, actual_type: str, target: str) -> bool:
    """Whether a resource of *actual_type* satisfies an object-reference *target* type."""
    if target == "Parameter":
        return True  # any object can own / supply a parameter (a plot's variable, a report column)
    if actual_type == target:
        return True
    actual_canonical = ctx.catalog.resolve(actual_type)
    target_canonical = ctx.catalog.resolve(target)
    if actual_canonical is not None and actual_canonical == target_canonical:
        return True  # alias-equal, e.g. Propagator ↔ PropSetup
    spec = ctx.catalog.type_spec(actual_type)
    if spec is None:
        return True  # unknown actual type (e.g. a plugin) — cannot judge, so never flag
    if spec.category == target:
        return (
            True  # the target names the actual type's object-type category (SpacePoint, Hardware…)
        )
    accepted = _TARGET_SUBTYPES.get(target)
    return accepted is not None and (actual_type in accepted or spec.category in accepted)


RULES: tuple[Rule, ...] = (
    Rule(
        "unknown-resource-type", "A Create of a type GMAT does not define.", _unknown_resource_type
    ),
    Rule(
        "undeclared-reference",
        "An object reference to a resource never created.",
        _undeclared_reference,
    ),
    Rule("unknown-field", "A field not in the catalogue for its resource type.", _unknown_field),
    Rule(
        "type-mismatch",
        "A value whose type contradicts the field's catalogue type.",
        _type_mismatch,
    ),
    Rule("enum-violation", "A value outside a field's allowed enumeration.", _enum_violation),
    Rule(
        "ref-target-mismatch",
        "An object-reference field pointing at the wrong type.",
        _ref_target_mismatch,
    ),
    Rule("duplicate-name", "Two resources created with the same name.", _duplicate_name),
    Rule("unused-resource", "A created resource never referenced.", _unused_resource),
)
