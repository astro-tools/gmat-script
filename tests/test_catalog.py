"""The field-catalogue loader (:mod:`gmat_script.catalog`).

Query and alias logic is pinned against a small synthetic catalogue; a handful of spot-checks assert
the real shipped ``fields-R2026a.json`` loads and carries the expected content. One test guards the
D9 boundary: loading the catalogue must never import ``gmatpy``.
"""

from __future__ import annotations

import sys

import pytest

from gmat_script import Catalog, FieldSpec, TypeSpec, load_catalog
from gmat_script.catalog import _available_catalogues, _choose_version

# A synthetic catalogue exercising every field shape and both alias cases (one resolvable, one
# dangling). Kept independent of GMAT's real reflected content so the query tests are stable.
_SYNTHETIC = {
    "schema_version": 1,
    "gmat_version": "R2099z",
    "generated": "2099-01-01",
    "aliases": {"Widget": "Gadget", "Ghost": "Missing"},
    "types": {
        "Gadget": {
            "category": "Hardware",
            "fields": {
                "Size": {
                    "type": "real",
                    "gmat_type": "Real",
                    "read_only": False,
                    "default": "1.5",
                    "unit": "m",
                },
                "Mode": {
                    "type": "enum",
                    "gmat_type": "Enumeration",
                    "read_only": False,
                    "allowed": ["A", "B"],
                },
                "Ref": {
                    "type": "object",
                    "gmat_type": "Object",
                    "read_only": False,
                    "ref_target": "Gizmo",
                },
                "Locked": {"type": "integer", "gmat_type": "Integer", "read_only": True},
            },
        }
    },
}


@pytest.fixture
def cat() -> Catalog:
    return Catalog.from_dict(_SYNTHETIC)


# -- provenance + construction --------------------------------------------------------------------


def test_provenance(cat: Catalog) -> None:
    assert cat.gmat_version == "R2099z"
    assert cat.generated == "2099-01-01"


def test_types_lists_canonical_names_only(cat: Catalog) -> None:
    assert cat.types() == ["Gadget"]  # alias spellings are not listed


# -- alias resolution -----------------------------------------------------------------------------


def test_resolve_direct(cat: Catalog) -> None:
    assert cat.resolve("Gadget") == "Gadget"


def test_resolve_via_alias(cat: Catalog) -> None:
    assert cat.resolve("Widget") == "Gadget"
    assert cat.has_type("Widget") is True


def test_resolve_dangling_alias_is_none(cat: Catalog) -> None:
    # "Ghost" aliases to "Missing", which is not a defined type.
    assert cat.resolve("Ghost") is None
    assert cat.has_type("Ghost") is False


def test_resolve_unknown_is_none(cat: Catalog) -> None:
    assert cat.resolve("Nope") is None
    assert cat.has_type("Nope") is False


# -- field queries (present) ----------------------------------------------------------------------


def test_type_spec_and_fields(cat: Catalog) -> None:
    spec = cat.type_spec("Gadget")
    assert isinstance(spec, TypeSpec)
    assert spec.category == "Hardware"
    assert cat.fields("Gadget") == ["Locked", "Mode", "Ref", "Size"]


def test_fields_via_alias(cat: Catalog) -> None:
    assert cat.fields("Widget") == ["Locked", "Mode", "Ref", "Size"]


def test_field_spec_scalar(cat: Catalog) -> None:
    field = cat.field("Gadget", "Size")
    assert isinstance(field, FieldSpec)
    assert (field.type, field.gmat_type, field.default, field.unit) == ("real", "Real", "1.5", "m")
    assert field.read_only is False
    assert field.allowed is None and field.ref_target is None


def test_field_type(cat: Catalog) -> None:
    assert cat.field_type("Gadget", "Size") == "real"
    assert cat.field_type("Widget", "Locked") == "integer"  # via alias


def test_enum_values(cat: Catalog) -> None:
    assert cat.enum_values("Gadget", "Mode") == ("A", "B")


def test_enum_values_none_for_non_enum(cat: Catalog) -> None:
    assert cat.enum_values("Gadget", "Size") is None


def test_ref_target(cat: Catalog) -> None:
    assert cat.ref_target("Gadget", "Ref") == "Gizmo"
    assert cat.ref_target("Gadget", "Size") is None


def test_read_only_flag(cat: Catalog) -> None:
    locked = cat.field("Gadget", "Locked")
    assert locked is not None and locked.read_only is True


# -- field queries (absent → graceful None / []) --------------------------------------------------


def test_unknown_type_degrades(cat: Catalog) -> None:
    assert cat.type_spec("Nope") is None
    assert cat.fields("Nope") == []
    assert cat.field("Nope", "Size") is None
    assert cat.field_type("Nope", "Size") is None
    assert cat.enum_values("Nope", "Size") is None
    assert cat.ref_target("Nope", "Size") is None


def test_unknown_field_degrades(cat: Catalog) -> None:
    assert cat.field("Gadget", "Nope") is None
    assert cat.field_type("Gadget", "Nope") is None


# -- version selection ----------------------------------------------------------------------------


def test_choose_version_newest_by_default() -> None:
    available = {"R2022a": "a.json", "R2025a": "b.json", "R2026a": "c.json"}
    assert _choose_version(available, None) == "R2026a"


def test_choose_version_explicit() -> None:
    available = {"R2025a": "b.json", "R2026a": "c.json"}
    assert _choose_version(available, "R2025a") == "R2025a"


def test_choose_version_missing_target_raises() -> None:
    with pytest.raises(ValueError, match="no field catalogue for GMAT version 'R1999z'"):
        _choose_version({"R2026a": "c.json"}, "R1999z")


def test_choose_version_empty_raises() -> None:
    with pytest.raises(RuntimeError, match="no field catalogue is shipped"):
        _choose_version({}, None)


# -- the real shipped catalogue -------------------------------------------------------------------


def test_available_catalogues_includes_r2026a() -> None:
    available = _available_catalogues()
    assert available.get("R2026a") == "fields-R2026a.json"


def test_real_catalogue_loads_and_has_expected_content() -> None:
    catalogue = Catalog.load()
    assert catalogue.gmat_version == "R2026a"
    # Core resource types and their fields.
    assert catalogue.has_type("Spacecraft")
    assert catalogue.field_type("Spacecraft", "SMA") == "real"
    assert catalogue.field_type("Spacecraft", "DryMass") == "real"
    # An enum with reflected allowed-values.
    axes = catalogue.enum_values("ImpulsiveBurn", "Axes")
    assert axes is not None and "VNB" in axes
    # An object-reference target.
    assert catalogue.ref_target("Spacecraft", "CoordinateSystem") == "CoordinateSystem"


def test_real_catalogue_resolves_script_aliases() -> None:
    catalogue = Catalog.load()
    # `Create Propagator` builds a PropSetup; `ForceModel`/`ODEModel` are the same class.
    assert catalogue.resolve("Propagator") == "PropSetup"
    assert catalogue.has_type("Propagator")
    assert catalogue.resolve("ODEModel") == "ForceModel"


def test_load_explicit_version() -> None:
    assert Catalog.load("R2026a").gmat_version == "R2026a"


def test_load_unknown_version_raises() -> None:
    with pytest.raises(ValueError, match="no field catalogue for GMAT version"):
        Catalog.load("R1999z")


def test_load_catalog_is_cached() -> None:
    assert load_catalog() is load_catalog()


def test_loader_does_not_import_gmatpy() -> None:
    # D9: the runtime catalogue path must never pull in GMAT. Importing gmat_script (which imports
    # this loader) and loading the catalogue must leave gmatpy unloaded.
    Catalog.load()
    assert "gmatpy" not in sys.modules
