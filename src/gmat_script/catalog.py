"""The GMAT field catalogue loader — the runtime knowledge base, with no GMAT dependency.

This reads the shipped ``data/fields-<version>.json`` (generated at build time by
:mod:`gmat_script.tools.gen_catalog`) and exposes a typed query API the linter, hover docs, and
completion consume. It **never imports ``gmatpy``** — the catalogue ships as data, so a plain
``pip install gmat-script`` carries it with no GMAT install anywhere (design decisions D9 / D11).

The catalogue is version-pinned. v0.3 ships exactly ``fields-R2026a.json``; :meth:`Catalog.load`
takes a ``target_version`` selector that defaults to the newest shipped catalogue, so adding another
GMAT release later is a data file plus a default — not a code change (D11).

    >>> cat = Catalog.load()
    >>> cat.has_type("Spacecraft")
    True
    >>> cat.field_type("Spacecraft", "SMA")
    'real'
    >>> cat.enum_values("ImpulsiveBurn", "Axes")
    ('VNB', 'LVLH', 'MJ2000Eq', 'SpacecraftBody')
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any

_DATA_PACKAGE = "gmat_script.data"
_FILENAME_RE = re.compile(r"^fields-(?P<version>.+)\.json$")


@dataclass(frozen=True)
class FieldSpec:
    """A single field of a resource type, as reflected from GMAT.

    ``type`` is the normalised catalogue type (``real`` / ``integer`` / ``string`` / ``bool`` /
    ``enum`` / ``object`` / ``object_array`` / ``string_array`` / ``real_array`` / ``matrix`` /
    ``filename`` / ``on_off`` / ``color`` / ``gmat_time`` / ...); ``gmat_type`` keeps GMAT's raw
    type label. ``allowed`` is populated for enums where GMAT exposes the values, ``ref_target`` for
    object references, and ``default`` for settable scalar fields — each ``None`` where absent.
    """

    name: str
    type: str
    gmat_type: str
    read_only: bool
    allowed: tuple[str, ...] | None = None
    ref_target: str | None = None
    default: str | None = None
    unit: str | None = None


@dataclass(frozen=True)
class TypeSpec:
    """A resource type: its GMAT object-type ``category`` and its fields by name."""

    name: str
    category: str
    fields: Mapping[str, FieldSpec]

    def field(self, name: str) -> FieldSpec | None:
        return self.fields.get(name)


class Catalog:
    """A loaded GMAT field catalogue with a typed, alias-aware query API."""

    def __init__(
        self,
        *,
        gmat_version: str,
        generated: str,
        types: Mapping[str, TypeSpec],
        aliases: Mapping[str, str],
    ) -> None:
        self._gmat_version = gmat_version
        self._generated = generated
        self._types = dict(types)
        self._aliases = dict(aliases)

    # -- provenance -------------------------------------------------------------------------------

    @property
    def gmat_version(self) -> str:
        """The GMAT release this catalogue was reflected from (e.g. ``"R2026a"``)."""
        return self._gmat_version

    @property
    def generated(self) -> str:
        """The ISO date the catalogue was generated."""
        return self._generated

    # -- construction -----------------------------------------------------------------------------

    @classmethod
    def load(cls, target_version: str | None = None) -> Catalog:
        """Load a shipped catalogue. ``target_version`` defaults to the newest available (D11)."""
        available = _available_catalogues()
        version = _choose_version(available, target_version)
        text = (resources.files(_DATA_PACKAGE) / available[version]).read_text(encoding="utf-8")
        return cls.from_dict(json.loads(text))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Catalog:
        """Build a catalogue from a parsed JSON mapping (the on-disk schema)."""
        types: dict[str, TypeSpec] = {}
        for name, spec in data.get("types", {}).items():
            fields = {
                fname: _field_from_dict(fname, fspec)
                for fname, fspec in spec.get("fields", {}).items()
            }
            types[name] = TypeSpec(name=name, category=spec.get("category", ""), fields=fields)
        return cls(
            gmat_version=data.get("gmat_version", ""),
            generated=data.get("generated", ""),
            types=types,
            aliases=dict(data.get("aliases", {})),
        )

    # -- queries ----------------------------------------------------------------------------------

    def types(self) -> list[str]:
        """All canonical type names, sorted (excludes alias spellings)."""
        return sorted(self._types)

    def resolve(self, name: str) -> str | None:
        """Resolve a script type name (possibly an alias) to its canonical key, or ``None``."""
        if name in self._types:
            return name
        canonical = self._aliases.get(name)
        return canonical if canonical in self._types else None

    def has_type(self, name: str) -> bool:
        """Whether ``name`` is a known type (directly or via an alias)."""
        return self.resolve(name) is not None

    def type_spec(self, name: str) -> TypeSpec | None:
        """The :class:`TypeSpec` for ``name`` (alias-resolved), or ``None`` if unknown."""
        canonical = self.resolve(name)
        return self._types.get(canonical) if canonical else None

    def fields(self, type_name: str) -> list[str]:
        """Sorted field names for ``type_name``; ``[]`` if the type is unknown."""
        spec = self.type_spec(type_name)
        return sorted(spec.fields) if spec else []

    def field(self, type_name: str, field_name: str) -> FieldSpec | None:
        """The :class:`FieldSpec` for ``type_name.field_name``, or ``None`` if either is unknown."""
        spec = self.type_spec(type_name)
        return spec.field(field_name) if spec else None

    def field_type(self, type_name: str, field_name: str) -> str | None:
        """The normalised type of a field, or ``None`` if unknown."""
        spec = self.field(type_name, field_name)
        return spec.type if spec else None

    def enum_values(self, type_name: str, field_name: str) -> tuple[str, ...] | None:
        """A field's allowed enum values where GMAT exposes them, else ``None``."""
        spec = self.field(type_name, field_name)
        return spec.allowed if spec else None

    def ref_target(self, type_name: str, field_name: str) -> str | None:
        """The target GMAT type of an object-reference field, or ``None``."""
        spec = self.field(type_name, field_name)
        return spec.ref_target if spec else None


def _field_from_dict(name: str, spec: Mapping[str, Any]) -> FieldSpec:
    allowed = spec.get("allowed")
    return FieldSpec(
        name=name,
        type=spec["type"],
        gmat_type=spec["gmat_type"],
        read_only=bool(spec["read_only"]),
        allowed=tuple(allowed) if allowed else None,
        ref_target=spec.get("ref_target"),
        default=spec.get("default"),
        unit=spec.get("unit"),
    )


def _available_catalogues() -> dict[str, str]:
    """Map each shipped GMAT version to its catalogue filename (``R2026a`` -> the JSON name)."""
    out: dict[str, str] = {}
    for entry in resources.files(_DATA_PACKAGE).iterdir():
        match = _FILENAME_RE.match(entry.name)
        if match:
            out[match.group("version")] = entry.name
    return out


def _choose_version(available: Mapping[str, str], target: str | None) -> str:
    """Pick a catalogue version: the requested one, else the newest. Raise if it cannot be met."""
    if not available:
        raise RuntimeError("no field catalogue is shipped with gmat_script")
    if target is None:
        return max(available)  # version tags sort chronologically (R2022a < R2025a < R2026a)
    if target in available:
        return target
    raise ValueError(
        f"no field catalogue for GMAT version {target!r}; available: {sorted(available)}"
    )


@cache
def load_catalog(target_version: str | None = None) -> Catalog:
    """Load (and cache) a shipped catalogue — the convenience entry point most consumers want."""
    return Catalog.load(target_version)
