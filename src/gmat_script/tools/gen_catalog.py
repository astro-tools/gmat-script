"""Generate the GMAT field catalogue from ``gmatpy`` reflection (build/CI time only).

This is the **only** GMAT-touching code in gmat-script (design decision D9). It imports ``gmatpy``,
walks GMAT's object factory and per-object parameter metadata, and writes
``gmat_script/data/fields-<version>.json`` — the version-pinned knowledge base the linter, hover
docs, and completion consume at runtime through :mod:`gmat_script.catalog` (which never imports
``gmatpy``).

Run it against a GMAT install::

    python -m gmat_script.tools.gen_catalog            # regenerate + overwrite the shipped file
    python -m gmat_script.tools.gen_catalog --check    # CI: regenerate in memory, fail on drift

GMAT is located from ``--gmat-root``, else the ``GMAT_ROOT`` environment variable (exported by the
``setup-gmat`` CI action), else a small set of platform-standard globs. The design — the enumeration
strategy, the two ``gmatpy`` segfault guards, type normalisation, alias handling, and the
default-capture policy — is recorded as design decision **D15**.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

# The shipped catalogue lives next to the runtime loader: src/gmat_script/data/.
_DATA_DIR = Path(__file__).resolve().parents[1] / "data"

# Schema version of the emitted JSON; bump when the on-disk shape changes (the loader checks it).
_SCHEMA_VERSION = 1

# Resource object-type categories to enumerate. Each maps to a ``Gmat::ObjectType`` constant on the
# ``gmat`` module; ``Moderator.GetListOfFactoryItems(code)`` lists that category's creatable type
# names. Enumerating by category (rather than the flat ``GetListOfAllFactoryItems``) is what keeps
# commands, math nodes, and report-only parameters out of the catalogue — they construct fine but
# are not script resources (D15).
_RESOURCE_CATEGORIES: tuple[str, ...] = (
    "SPACECRAFT",
    "FORMATION",
    "SPACE_POINT",
    "CELESTIAL_BODY",
    "CALCULATED_POINT",
    "BURN",
    "PROP_SETUP",
    "ODE_MODEL",
    "PHYSICAL_MODEL",
    "COORDINATE_SYSTEM",
    "AXIS_SYSTEM",
    "SUBSCRIBER",
    "SOLVER",
    "HARDWARE",
    "PARAMETER",
    "FUNCTION",
    "DATA_FILE",
    "MEASUREMENT_MODEL",
    "ERROR_MODEL",
    "EVENT_LOCATOR",
    "FIELD_OF_VIEW",
    "INTERFACE",
    "ATMOSPHERE",
    "ATTITUDE",
    "DATA_FILTER",
)

# The PARAMETER factory lists 300+ items, but only these three are script-declarable resources; the
# rest are calculated quantities accessed as ``object.Param`` (not ``Create``d). The FUNCTION
# factory lists built-in math functions next to the resource forms — keep only the declarable ones.
_PARAMETER_RESOURCES: frozenset[str] = frozenset({"Variable", "String", "Array"})
_FUNCTION_RESOURCES: frozenset[str] = frozenset({"GmatFunction", "MatlabFunction"})

# Script-facing type names that differ from the factory item name. ``Create Propagator`` builds a
# ``PropSetup``; ``ForceModel`` and ``ODEModel`` are the same class. The catalogue stores the
# factory name and records these aliases so a lookup by either spelling resolves (D15). Keys are the
# alias (script) spelling; values are the canonical factory name actually reflected.
_SCRIPT_ALIASES: dict[str, str] = {"Propagator": "PropSetup", "ODEModel": "ForceModel"}

# Normalised value types we capture a ``default`` for. Filenames are skipped (their defaults can be
# absolute install paths — both non-portable and non-deterministic across machines); arrays/matrices
# are skipped as their string form is noisy and rarely a useful default (D15).
_DEFAULTABLE: frozenset[str] = frozenset(
    {"real", "integer", "string", "bool", "enum", "on_off", "color", "object", "gmat_time"}
)

# A Spacecraft's six orbital-element fields are *dynamic*: their labels (X/Y/Z/VX/VY/VZ vs
# SMA/ECC/INC/... vs RadPer/RadApo/... etc.) depend on DisplayStateType. Reflecting a single
# default (Cartesian) instance would miss SMA/ECC/INC and the rest — the most common fields in any
# GMAT script. We cycle the display type through every documented R2026a state representation and
# merge the element labels each pass. The list is filled from the User's Guide because GMAT does not
# expose it via enum reflection (DisplayStateType's enum strings come back empty) — see D15.
_SPACECRAFT_STATE_TYPES: tuple[str, ...] = (
    "Cartesian",
    "Keplerian",
    "ModifiedKeplerian",
    "SphericalAZFPA",
    "SphericalRADEC",
    "Equinoctial",
    "AlternateEquinoctial",
    "Delaunay",
    "Planetodetic",
    "OutgoingAsymptote",
    "IncomingAsymptote",
    "BrouwerMeanShort",
    "BrouwerMeanLong",
)


def _build_type_map(gmat: Any) -> dict[int, str]:
    """Map GMAT's integer parameter type codes to the catalogue's normalised type vocabulary.

    The integer code (``GetParameterType``) is authoritative: GMAT's *string* type label
    (``GetParameterTypeString``) is sometimes a per-class custom name (``Radius``, ``Mu``,
    ``EstimateMethod``, ...) whose underlying code is still one of these. So we normalise from the
    code and keep the raw string only as a label.
    """
    pairs = {
        "REAL_TYPE": "real",
        "INTEGER_TYPE": "integer",
        "UNSIGNED_INT_TYPE": "integer",
        "STRING_TYPE": "string",
        "FILENAME_TYPE": "filename",
        "BOOLEAN_TYPE": "bool",
        "ON_OFF_TYPE": "on_off",
        "ENUMERATION_TYPE": "enum",
        "OBJECT_TYPE": "object",
        "OBJECTARRAY_TYPE": "object_array",
        "STRINGARRAY_TYPE": "string_array",
        "INTARRAY_TYPE": "integer_array",
        "UNSIGNED_INTARRAY_TYPE": "integer_array",
        "REALARRAY_TYPE": "real_array",
        "RVECTOR_TYPE": "real_array",
        "RMATRIX_TYPE": "matrix",
        "BOOLEANARRAY_TYPE": "bool_array",
        "COLOR_TYPE": "color",
        "GMATTIME_TYPE": "gmat_time",
    }
    out: dict[int, str] = {}
    for const, norm in pairs.items():
        code = getattr(gmat, const, None)
        if code is not None:
            out[int(code)] = norm
    return out


# Fallback for the handful of integer codes whose constant we do not enumerate (e.g. ``TIME_TYPE``)
# or that collide on a shared label: GMAT's ``GetParameterTypeString`` is the second-best authority
# after the code, so we key off the raw label when the code is unmapped.
_STRING_FALLBACK: dict[str, str] = {
    "Real": "real",
    "Integer": "integer",
    "UnsignedInt": "integer",
    "String": "string",
    "Filename": "filename",
    "Boolean": "bool",
    "OnOff": "on_off",
    "Enumeration": "enum",
    "Object": "object",
    "ObjectArray": "object_array",
    "StringArray": "string_array",
    "IntArray": "integer_array",
    "UnsignedIntArray": "integer_array",
    "RealArray": "real_array",
    "Rvector": "real_array",
    "Rmatrix": "matrix",
    "BooleanArray": "bool_array",
    "Color": "color",
    "Time": "real",
    "GmatTime": "gmat_time",
}


def _normalize(code: int, raw: str, type_map: dict[int, str]) -> str:
    """Normalise a GMAT parameter type: integer code first, then the raw label, else ``unknown``."""
    return type_map.get(code) or _STRING_FALLBACK.get(raw, "unknown")


def locate_gmat(arg: str | None) -> Path:
    """Resolve a GMAT install root: ``--gmat-root`` arg, then ``GMAT_ROOT``, then platform globs."""
    candidates: list[Path] = []
    if arg:
        candidates.append(Path(arg))
    env = os.environ.get("GMAT_ROOT")
    if env:
        candidates.append(Path(env))
    for pattern in ("~/gmat-*", "/opt/gmat-*", "/Applications/GMAT*", "C:/Program Files/GMAT*"):
        candidates.extend(sorted(Path(p) for p in _glob(pattern)))

    for root in candidates:
        root = root.expanduser()
        if (root / "bin" / "gmatpy").is_dir():
            return root
    raise SystemExit(
        "could not locate a GMAT install (looked at --gmat-root, $GMAT_ROOT, and standard paths); "
        "pass --gmat-root /path/to/gmat"
    )


def _glob(pattern: str) -> list[str]:
    from glob import glob

    return glob(os.path.expanduser(pattern))


def load_gmatpy(root: Path) -> Any:
    """Import ``gmatpy`` from a GMAT install without pip-installing it (build/CI only)."""
    bin_dir = root / "bin"
    sys.path.insert(0, str(bin_dir))
    # Record the root so default-capture can scrub any value carrying the install path.
    os.environ["GMAT_ROOT"] = str(root)
    import gmatpy as gmat

    startup = bin_dir / "api_startup_file.txt"
    if startup.is_file():
        gmat.Setup(str(startup))
    return gmat


def _infer_version(root: Path) -> str | None:
    """Pull a GMAT release tag (e.g. ``R2026a``) out of an install path."""
    match = re.search(r"R20\d\d[a-z]", str(root))
    return match.group(0) if match else None


def _field_default(obj: Any, name: str, ntype: str, read_only: bool, root_str: str) -> str | None:
    """A field's default, captured only where it is safe and portable.

    ``GetField`` on a *read-only* field can segfault the engine (it triggers computation on an
    uninitialised object, e.g. ``NuclearPowerSystem.TotalPowerAvailable``), so defaults come only
    from settable, scalar-ish fields. Any value carrying the install path is dropped so no local
    path leaks into the committed artifact.
    """
    if read_only or ntype not in _DEFAULTABLE:
        return None
    try:
        value = str(obj.GetField(name))
    except Exception:
        return None
    # gmatpy returns some failures as a *string* rather than raising (a conversion that needs an
    # initialised state, an unsupported body, ...); and uninitialised state slots read back as the
    # -999.999 placeholder. Neither is a real default.
    if value.startswith("API exception") or "Exception:" in value or value == "-999.999":
        return None
    if root_str and root_str in value:
        return None
    return value


def _reflect_type(obj: Any, gmat: Any, type_map: dict[int, str]) -> dict[str, dict[str, Any]]:
    """Reflect one constructed resource object into a ``{field_name: field_spec}`` mapping."""
    root_str = os.environ.get("GMAT_ROOT", "")
    fields: dict[str, dict[str, Any]] = {}
    for i in range(obj.GetParameterCount()):
        try:
            name = obj.GetParameterText(i)
            raw = obj.GetParameterTypeString(i)
            code = int(obj.GetParameterType(i))
            read_only = bool(obj.IsParameterReadOnly(i))
        except Exception:
            continue
        ntype = _normalize(code, raw, type_map)
        if ntype == "unknown":
            print(f"  ? unknown type code {code} ({raw}) on field {name}", file=sys.stderr)

        spec: dict[str, Any] = {"type": ntype, "gmat_type": raw, "read_only": read_only}

        if ntype == "enum":
            try:
                allowed = [str(v) for v in obj.GetPropertyEnumStrings(i)]
            except Exception:
                allowed = []
            if allowed:
                spec["allowed"] = allowed
        if ntype in ("object", "object_array"):
            try:
                target = gmat.GmatBase.GetObjectTypeString(obj.GetPropertyObjectType(i))
                if target:
                    spec["ref_target"] = str(target)
            except Exception:
                pass
        try:
            unit = str(obj.GetParameterUnit(i))
            if unit:
                spec["unit"] = unit
        except Exception:
            pass
        default = _field_default(obj, name, ntype, read_only, root_str)
        if default is not None:
            spec["default"] = default

        fields[name] = spec
    return fields


def _element_slots(obj: Any) -> list[int]:
    """The parameter indices whose label changes with DisplayStateType (the six element slots)."""
    count = obj.GetParameterCount()
    cartesian = [obj.GetParameterText(i) for i in range(count)]
    try:
        obj.SetField("DisplayStateType", "Keplerian")
    except Exception:
        return []
    keplerian = [obj.GetParameterText(i) for i in range(count)]
    obj.SetField("DisplayStateType", "Cartesian")
    return [i for i in range(count) if cartesian[i] != keplerian[i]]


def _reflect_resource(
    obj: Any, type_name: str, gmat: Any, type_map: dict[int, str]
) -> dict[str, dict[str, Any]]:
    """Reflect a resource, merging Spacecraft's display-type-dependent element fields."""
    fields = _reflect_type(obj, gmat, type_map)
    if type_name == "Spacecraft":
        slots = _element_slots(obj)
        element_names: set[str] = {obj.GetParameterText(i) for i in slots}
        for rep in _SPACECRAFT_STATE_TYPES[1:]:  # the default (Cartesian) pass already ran
            try:
                obj.SetField("DisplayStateType", rep)
            except Exception:
                continue
            element_names.update(obj.GetParameterText(i) for i in slots)
            for fname, spec in _reflect_type(obj, gmat, type_map).items():
                fields.setdefault(fname, spec)  # keep the first pass; add new element labels
        # Element defaults are conversions of an uninitialised placeholder state, never meaningful.
        for fname in element_names:
            fields.get(fname, {}).pop("default", None)
    return fields


def build_catalog(gmat: Any, gmat_version: str, generated: str) -> dict[str, Any]:
    """Walk the resource factories and reflect every type into the catalogue dict."""
    mod = gmat.Moderator.Instance()
    type_map = _build_type_map(gmat)

    types: dict[str, dict[str, Any]] = {}
    skipped = 0
    for cat in _RESOURCE_CATEGORIES:
        code = getattr(gmat, cat, None)
        if code is None:
            continue
        for tn in mod.GetListOfFactoryItems(code):
            name = str(tn)
            if cat == "PARAMETER" and name not in _PARAMETER_RESOURCES:
                continue
            if cat == "FUNCTION" and name not in _FUNCTION_RESOURCES:
                continue
            if name in _SCRIPT_ALIASES:  # an alias spelling — covered by its canonical type
                continue
            if name in types:
                continue
            try:
                # IMPORTANT: never gmat.Clear() while iterating — it wipes the config and segfaults
                # on the next construct. Unique names + letting GMAT own the objects is safe (D15).
                obj = gmat.Construct(name, "gscat_" + name.replace("-", "_"))
            except Exception:
                skipped += 1
                continue
            try:
                category = str(gmat.GmatBase.GetObjectTypeString(code))
            except Exception:
                category = cat
            fields = _reflect_resource(obj, name, gmat, type_map)
            types[name] = {"category": category, "fields": fields}

    aliases = {alias: canon for alias, canon in _SCRIPT_ALIASES.items() if canon in types}
    field_count = sum(len(t["fields"]) for t in types.values())
    if skipped:
        print(f"  ({skipped} factory items skipped: construct failed)", file=sys.stderr)

    return {
        "schema_version": _SCHEMA_VERSION,
        "gmat_version": gmat_version,
        "generated": generated,
        "generator": "gmat_script.tools.gen_catalog",
        "type_count": len(types),
        "field_count": field_count,
        "aliases": aliases,
        "types": types,
    }


def render(data: dict[str, Any]) -> str:
    """Serialise the catalogue deterministically (sorted keys, ASCII, trailing newline)."""
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def _without_volatile(data: dict[str, Any]) -> dict[str, Any]:
    """A copy without the provenance fields that change every run (so drift checks are stable)."""
    return {k: v for k, v in data.items() if k != "generated"}


def check_drift(committed: Path, fresh: dict[str, Any]) -> bool:
    """True if the freshly generated catalogue differs from the committed one (date aside)."""
    if not committed.is_file():
        print(f"drift: {committed} does not exist", file=sys.stderr)
        return True
    on_disk = json.loads(committed.read_text(encoding="utf-8"))
    if _without_volatile(on_disk) == _without_volatile(fresh):
        return False
    print(f"drift: regenerated catalogue differs from {committed.name}", file=sys.stderr)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Regenerate the GMAT field catalogue.")
    parser.add_argument("--gmat-root", help="GMAT install root (else $GMAT_ROOT, else autodetect).")
    parser.add_argument(
        "--gmat-version", help="GMAT release tag (else inferred from the root path)."
    )
    parser.add_argument(
        "--output", help="Output path (else src/gmat_script/data/fields-<ver>.json)."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Regenerate in memory and exit non-zero if it differs from the committed file.",
    )
    args = parser.parse_args(argv)

    root = locate_gmat(args.gmat_root)
    version = args.gmat_version or _infer_version(root)
    if not version:
        raise SystemExit("could not infer GMAT version from the install path; pass --gmat-version")

    gmat = load_gmatpy(root)
    print(f"Reflecting GMAT {version} at {root} ...", file=sys.stderr)
    data = build_catalog(gmat, version, date.today().isoformat())
    print(f"  {data['type_count']} types, {data['field_count']} fields", file=sys.stderr)

    output = Path(args.output) if args.output else _DATA_DIR / f"fields-{version}.json"

    if args.check:
        return 1 if check_drift(output, data) else 0

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(data), encoding="utf-8", newline="\n")  # LF on every OS
    print(f"Wrote {output}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
