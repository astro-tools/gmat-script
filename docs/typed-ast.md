# The typed AST

`parse` gives you the concrete syntax tree (CST) — faithful to the last byte, but untyped: every
node is a generic `tree_sitter.Node`. The **typed AST** layers a small, typed object model over that
tree. Its entry point is `Script`: it presents a parsed script as typed `Resource` objects with
dict-like field access and an ordered mission sequence, while still re-emitting the original source
byte-for-byte.

```python
from gmat_script import Script

script = Script.parse("""\
Create Spacecraft Sat
Sat.SMA = 7000
Sat.ECC = 0.01

BeginMissionSequence
Propagate DefaultProp(Sat) {Sat.ElapsedDays = 1}
""")

script.resources["Sat"]["SMA"]   # 7000
script.spacecraft["Sat"]["ECC"]  # 0.01
len(script.mission_sequence)     # 1
script.to_source()               # the original text, byte-for-byte
```

`Script.parse(source)` is shorthand for `Script(parse(source))` — wrap an existing
[`Tree`](api.md) with `Script(tree)` when you have already parsed it.

## A lossless view

A `Script` is a typed *view* over the tree, not a copy of it. Every typed node wraps exactly one CST
node and recomputes its structure on access, so the overlay can never drift from the underlying
tree, and an unmodified script re-emits exactly:

```python
script.to_source() == source   # True — until the first edit
```

This is the same byte-for-byte guarantee `parse` makes — the typed layer adds structure on top of
it without giving it up. (Once you [edit](editing.md) a script, every *untouched* byte stays exact;
only the edited span is re-emitted.)

## Resources

A `Resource` is one `Create`'d GMAT object. Reach resources three ways:

- **by name** — `script.resources["Sat"]`;
- **by type** — `script.resources_by_type["Spacecraft"]["Sat"]`;
- **by the type sugar** — `script.spacecraft["Sat"]`, where the attribute is the GMAT type
  lowercased. Only types actually present in the script resolve; a typo (or a type that is not
  there) raises `AttributeError` rather than returning an empty mapping.

Each resource carries its declaration metadata:

```python
sat = script.spacecraft["Sat"]
sat.name              # 'Sat'
sat.type              # 'Spacecraft' — verbatim from `Create Spacecraft Sat`
sat.to_source()       # 'Create Spacecraft Sat' — the declaration slice

array = Script.parse("Create Array A[3, 3]").resources["A"]
array.array_dimensions  # (3, 3) — the [r, c] size suffix; None for a non-Array
```

A multi-name declaration (`Create Variable x y z`) yields one `Resource` per name, each sharing that
declaration.

### Dict-like field access

A `Resource` is a `Mapping` from field name to its configured value. Reading a field returns the
value assigned to it in the configuration section, coerced to a Python value; when a field is
assigned more than once, the last assignment wins (GMAT applies them in order). Iterating a resource
yields its field names.

```python
sat["SMA"]            # 7000
list(sat)             # ['SMA', 'ECC']
"ECC" in sat          # True
dict(sat)             # {'SMA': 7000, 'ECC': 0.01}
```

A dotted field path is a single key:

```python
fm = Script.parse(
    "Create ForceModel FM\nFM.GravityField.Earth.PotentialFile = 'JGM2.cof'\n"
).resources["FM"]
fm["GravityField.Earth.PotentialFile"]   # 'JGM2.cof' — the whole dotted path is one key
```

The mapping spans **dotted field assignments** (`Sat.SMA = …`). Whole-object assignments (`x = 5`)
and array-element writes (`A(1, 1) = …`) reach the resource through its `assignments` property but
are deliberately not exposed as fields.

## Value coercion

Field and operand values are coerced *structurally* — inferred from a literal's shape, never from a
field catalogue (that semantic typing is a job for a later linter). The mapping is total: every value
the grammar can place on the right-hand side of an assignment maps to one of these:

| GMAT literal | Python value |
|--------------|--------------|
| `7000` | `int` |
| `1.25e-1`, `850.0` | `float` |
| `'a string'` | `str` (the single quotes are stripped) |
| `true` / `false` | `bool` |
| `Earth`, `Sat.SMA` (a bare or dotted name used as a value) | `ObjectRef` |
| `{Earth, Luna}` (a brace-list) | `list` of coerced elements |
| `[1 2 3]`, `[1 0 0; 0 1 0; 0 0 1]` (a square-bracket array / matrix) | `Array` |
| a computed expression, a multi-word enum, an unquoted path / date | `RawValue` |

```python
from gmat_script import Array, ObjectRef, RawValue

s = Script.parse("""\
Create Spacecraft Sat
Sat.SMA = 7000
Sat.DateFormat = 'UTCGregorian'
Sat.Tanks = {FuelTank}
Sat.OrbitColor = [1 0 0]
Sat.NAIFId = -123456789
""")
sat = s.resources["Sat"]
sat["SMA"]          # 7000           (int)
sat["DateFormat"]   # 'UTCGregorian' (str)
sat["Tanks"]        # [ObjectRef(name='FuelTank')]
sat["OrbitColor"]   # Array(elements=(1, 0, 0))
sat["NAIFId"]       # -123456789     (a signed number folds the sign)
```

`ObjectRef` distinguishes a name *used as a value* (an object reference) from a quoted string with
the same text. `RawValue` is the escape hatch: it holds the exact source text for any form with no
faithful Python reduction — a computed right-hand side like `sqrt(x)`, a multi-word enum like
`Relative Position`, an unquoted file path, or an unquoted date. Whether a referenced object actually
exists is, again, a question for the linter, not this layer.

!!! note "Brace-lists and bracket-arrays are kept distinct"
    `{a, b}` coerces to a `list` and `[a b]` to an `Array`, even though both hold coerced elements,
    because GMAT emits them differently — collapsing them to one type would lose the form on a
    read-modify-write round-trip. A 2-D matrix `[r1; r2]` is an `Array` whose elements are each a
    row `Array`.

## The mission sequence

Everything after the `BeginMissionSequence` marker is the ordered mission sequence, exposed as
`script.mission_sequence` — a tuple of typed `Command` objects in source order. A file with no marker
is configuration-only and has an empty sequence.

```python
seq = script.mission_sequence
seq[0].keyword        # 'Propagate'
seq[0].to_source()    # 'Propagate DefaultProp(Sat) {Sat.ElapsedDays = 1}'
```

The split between configuration and sequence is **positional** — the same `assignment_command`
serves a literal config assignment and a computed mission-sequence assignment; their section is
fixed by their position relative to the marker, not by a different node type. A resource only ever
sees configuration-section assignments. See the [grammar surface](grammar-surface.md) and the
[design decisions](design/decisions.md) for the language model this rests on.

## Next steps

- [Editing](editing.md) — the same `Script` and `Resource` objects are mutable; set a field, rename
  a resource, or splice a command.
- [The formatter](formatting.md) — re-emit a `Script` in canonical form.
- [API reference](api.md) — the full typed surface.
