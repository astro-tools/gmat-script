# The field catalogue

The field catalogue is the knowledge base behind everything that reasons about GMAT *semantics*: the
[linter](lint.md), and the [language server](lsp.md)'s hover docs and completion. It records, for
every GMAT resource type, the fields that type defines — each field's type, allowed enumeration,
reference target, default, and unit — so a tool can tell that `Spacecraft.SMA` wants a number, that
`ImpulsiveBurn.Axes` is one of four values, or that `Spacecraft.Tanks` points at a `FuelTank`,
without running GMAT.

It is shipped as **data**, not derived at runtime. The wheel carries a precompiled JSON catalogue;
loading it imports no GMAT and touches no `gmatpy`.

## Where it comes from — and the GMAT-free guarantee

The catalogue is reflected from a real GMAT install at build time, by a single generator, and then
frozen into the package. Two halves, deliberately kept apart:

- **Generation (build/CI time, GMAT required).** `gmat_script.tools.gen_catalog` is the *only*
  GMAT-touching code in the project. It imports `gmatpy`, walks GMAT's object factory and each
  object's parameter metadata, normalises the types, and writes
  `gmat_script/data/fields-<version>.json`.
- **Loading (runtime, no GMAT).** `gmat_script.catalog` reads that JSON and answers queries. It
  **never imports `gmatpy`** — so a plain `pip install gmat-script` carries the full catalogue with
  no GMAT install anywhere.

This split is the GMAT-free guarantee in practice: GMAT's knowledge is captured once, offline, and
travels with the package as a data file. (See the [design decisions](design/decisions.md).)

The shipped catalogue is reflected from **GMAT R2026a** and records its 102 resource types and 2614
fields.

## Reading the catalogue

`load_catalog()` returns a cached, queryable `Catalog`. It and its records are part of the public
API:

```python
from gmat_script import load_catalog

cat = load_catalog()

cat.gmat_version            # 'R2026a' — the release this was reflected from
cat.generated               # '2026-06-08' — the ISO date it was generated

cat.has_type("Spacecraft")          # True
cat.field_type("Spacecraft", "SMA") # 'real'
cat.enum_values("ImpulsiveBurn", "Axes")
# ('VNB', 'LVLH', 'MJ2000Eq', 'SpacecraftBody')
cat.ref_target("Spacecraft", "Tanks")   # 'FuelTank'
```

A type name that GMAT spells differently in scripts resolves through an alias (`Propagator` ->
`PropSetup`, `ODEModel` -> `ForceModel`), so `cat.has_type("Propagator")` is `True`. Any query for an
unknown type or field returns `None` (or `[]`) rather than raising — the linter and editor leans on
this to degrade to "no finding" wherever the catalogue is silent.

### What a field carries

`cat.field(type, name)` returns a `FieldSpec`:

| Attribute | Meaning |
|-----------|---------|
| `type` | The normalised catalogue type: `real`, `integer`, `string`, `bool`, `enum`, `object`, `object_array`, `string_array`, `real_array`, `matrix`, `filename`, `on_off`, `color`, `gmat_time`, … |
| `gmat_type` | GMAT's own raw type label, kept verbatim (e.g. `Real`, `Rmatrix`). |
| `read_only` | Whether GMAT exposes the field as output-only (not settable from a script). |
| `allowed` | The enum's allowed values, where GMAT exposes them — else `None`. |
| `ref_target` | The target GMAT type for an object-reference field — else `None`. |
| `default` | The default for a settable scalar field — else `None`. |
| `unit` | The field's unit, where GMAT reports one — else `None`. |

`cat.type_spec(type)` returns a `TypeSpec` carrying the type's GMAT object-type `category` and its
`fields` mapping. The lower-level `Catalog.load(target_version=...)` builds an uncached catalogue;
`load_catalog` is the convenience entry point most consumers want.

## Versioning

The semantics a script must satisfy — valid field names, enums, defaults — vary by GMAT release, so
the catalogue is **version-pinned and provenance-stamped**: every catalogue carries the GMAT version
it was reflected from and the date it was generated. The grammar, by contrast, never enumerates types
or keywords and is effectively version-independent; the catalogue is the one version-coupled artifact.

`load_catalog()` defaults to the newest shipped catalogue. Pass `target_version` to pin a specific
release:

```python
load_catalog("R2026a")        # an explicit release
load_catalog()                # the newest available (currently R2026a)
```

The linter exposes the same selector — `lint(source, target_version="R2026a")` — and the language
server uses the default. Requesting a version that is not shipped raises `ValueError` listing what is
available.

Supporting another GMAT release is **additive**: a new `fields-<version>.json` is dropped into
`gmat_script/data/`, and `load_catalog()`'s "newest" default and the `target_version` selector pick
it up with no code change. There is no per-version code fork.

## Regenerating the catalogue (the version-bump process)

Regenerating is only needed when targeting a new GMAT release or picking up a point-release metadata
change. It needs a real GMAT install — `gmatpy` is imported from it directly and is never
pip-installed.

```console
# Regenerate and overwrite the shipped file, against a GMAT install:
$ python -m gmat_script.tools.gen_catalog
# Regenerate in memory and fail on any drift from the committed catalogue (the CI check):
$ python -m gmat_script.tools.gen_catalog --check
```

The generator locates GMAT from `--gmat-root`, else the `GMAT_ROOT` environment variable, else a set
of platform-standard install paths. A dedicated CI job runs the `--check` form on a schedule (and on
demand) against a freshly provisioned GMAT install, so a catalogue that drifts from the current GMAT
metadata is surfaced rather than silently rotting. The generation date is ignored in the drift
comparison, so re-running on a different day is not spurious drift.

To bump to a new release: regenerate against that GMAT version (so the file is written as
`fields-<new-version>.json`), commit the new data file alongside the existing one, and the loader's
"newest" default begins serving it. Keeping the prior file lets callers pin the older release through
`target_version`.
