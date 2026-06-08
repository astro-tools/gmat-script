# Editing scripts

The [typed AST](typed-ast.md) is not read-only. The same `Script` and `Resource` objects are
mutable: you set a field, add or rename a resource, or splice a mission-sequence command, and the
change is written back into the source. Editing keeps the byte-for-byte guarantee for every
*untouched* byte — only the span you touched is re-emitted.

```python
from gmat_script import Script

script = Script.parse("""\
Create Spacecraft Sat
Sat.SMA = 7000
Sat.ECC = 0.01

BeginMissionSequence
Propagate DefaultProp(Sat) {Sat.ElapsedDays = 1}
""")

script.spacecraft["Sat"]["SMA"] = 8000   # raise the orbit
script.set_field("Sat", "ECC", 0.001)    # the same edit, spelled as a method
print(script.to_source())
```

```text
Create Spacecraft Sat
Sat.SMA = 8000
Sat.ECC = 0.001

BeginMissionSequence
Propagate DefaultProp(Sat) {Sat.ElapsedDays = 1}
```

## How an edit is applied — and why it can't corrupt your script

A `Script` owns its source buffer. Each mutator computes byte-range edits over the current tree,
splices them in, re-parses the result, and commits — and that re-parse is a guard:

- it **refuses to edit a script that already has syntax errors**, and
- it **rejects any edit whose result would not parse cleanly**, raising `MutationError` and leaving
  the source unchanged.

So a committed mutation always re-parses with zero `ERROR` nodes — you can never edit a valid script
into a broken one. Names and field paths are validated up front (a name carrying whitespace or a
newline would splice in extra statements that parse cleanly on their own, which the re-parse guard
could not catch), so those raise `MutationError` too:

```python
from gmat_script import MutationError

try:
    script.add_resource("Spacecraft", "Bad Name")
except MutationError as exc:
    print(exc)   # resource name 'Bad Name' is not a valid GMAT identifier
```

Every mutator returns the `Script`, so edits chain:

```python
script.set_field("Sat", "SMA", 7000).set_field("Sat", "ECC", 0.02)
```

## Editing fields

A `Resource` is a `MutableMapping`, so the dict operations all work and route through two underlying
edits — set and delete:

```python
sat = script.spacecraft["Sat"]
sat["SMA"] = 7200            # rewrite the value in place (or append if the field is new)
sat.update({"TA": 0, "RAAN": 90})
del sat["ECC"]              # remove every assignment to the field
sat.setdefault("INC", 28.5)
```

Setting a field rewrites the last assignment to it in place when it already exists, and otherwise
appends a canonical `<resource>.<field> = <value>` line next to the resource's configuration.
Deleting removes *every* assignment to that field; deleting a field that was never assigned raises
`KeyError`. The method forms — `script.set_field(resource, field, value)` and
`script.delete_field(resource, field)` — do the same thing without a `Resource` handle.

The value you write is formatted with the same canonical emitter the formatter uses, so a Python
value maps to one chosen GMAT form (see [value coercion](typed-ast.md#value-coercion) for the
inverse):

```python
from gmat_script import Array, ObjectRef

sat["SMA"] = 7000                       # -> Sat.SMA = 7000
sat["DragArea"] = 15.5                  # -> Sat.DragArea = 15.5
sat["DateFormat"] = "UTCGregorian"      # -> Sat.DateFormat = 'UTCGregorian'
sat["Tanks"] = [ObjectRef("FuelTank")]  # -> Sat.Tanks = {FuelTank}
sat["OrbitColor"] = Array((1, 0, 0))    # -> Sat.OrbitColor = [1 0 0]
```

Use `ObjectRef` to write a bare reference (`{FuelTank}`, not the string `{'FuelTank'}`), and
`RawValue` as the escape hatch for a computed right-hand side. A value that cannot be written
without corrupting the script is rejected at emission — a non-finite float, a string carrying a
single quote or newline, or an empty / newline-bearing bare value all raise `ValueError`.

## Editing resources

```python
script.add_resource("ImpulsiveBurn", "TOI", {"Element1": 0.5, "Axes": ObjectRef("VNB")})
```

`add_resource` appends `Create <type> <name>` (plus any fields) to the configuration, landing just
before `BeginMissionSequence` (or at end of file when there is no marker):

```text
Create Spacecraft Sat
Sat.SMA = 7000
Sat.ECC = 0.01

Create ImpulsiveBurn TOI
TOI.Element1 = 0.5
TOI.Axes = VNB
BeginMissionSequence
Propagate DefaultProp(Sat) {Sat.ElapsedDays = 1}
```

The edit is a minimal splice — it inserts the new lines and leaves every other byte exactly where it
was, which is why the blank line stays put rather than moving to sit before the marker. Run
[the formatter](formatting.md) afterwards to normalise the surrounding blank lines into canonical
form.

`remove_resource(name)` drops a resource's `Create` (or just its name, for a multi-name declaration)
and every configuration assignment rooted at it. References to it elsewhere are left as-is — use
`rename_resource` to rewrite those. Adding a name that already exists raises `MutationError`.

### Renaming, and the reference-rewrite

`rename_resource(old, new)` renames a resource **and rewrites references to it** by default:

```python
script.rename_resource("Sat", "MainSat")
```

```text
Create Spacecraft MainSat
MainSat.SMA = 7000

Create ImpulsiveBurn TOI
TOI.Element1 = 0.5

BeginMissionSequence
Maneuver TOI(MainSat)
Propagate DefaultProp(MainSat) {MainSat.ElapsedDays = 1}
Report rf MainSat.Earth.SMA
```

The rewrite is **best-effort over the textual reference forms**, and deliberately scoped. It
rewrites each identifier whose syntactic role is an object reference — the root of a dotted path, the
head of an array-index / function call, a bare operand or argument or list element, and the
declaration name. It deliberately leaves alone:

- **field-name segments** — the `.Earth.SMA` after the root in `MainSat.Earth.SMA`, so a field that
  happens to share the old name is never disturbed;
- **the `Create` type** — renaming an object never touches a coincidentally-equal type token;
- **identifiers inside an opaque `BeginScript … EndScript` body** — that body is a single raw token,
  not parsed, so references there are not rewritten.

Pass `update_references=False` to rename only the declaration, leaving every call site untouched —
which means the old references now point at a name that no longer exists, so reach for it only when
you intend exactly that:

```python
script.rename_resource("Sat", "MainSat", update_references=False)
# -> `Create Spacecraft MainSat`, but `Sat.SMA = 7000` and `Maneuver TOI(Sat)` keep `Sat`
```

Renaming onto a name that already exists raises `MutationError`.

## Editing mission-sequence commands

Commands are spliced by position in the mission sequence. `insert_command(index, text)` takes raw
command source and inserts it as its own line before `index` (or at the end):

```python
script.insert_command(0, "Toggle rf On")
script.insert_command(len(script.mission_sequence), "Stop")
```

The companions are `remove_command(index)` (drops the command — a whole block, if it is one),
`replace_command(index, text)` (rewrites the command in place, preserving its indentation and
trailing newline), and `move_command(from_index, to_index)` (reorders without re-emitting the
command). Inserting into an empty sequence needs a `BeginMissionSequence` marker to insert after; an
out-of-range index raises `IndexError`.

!!! note "Re-read the sequence after a command edit"
    `mission_sequence` is a snapshot of the current tree. After an edit that changes it, re-read the
    attribute rather than reusing command handles taken before the edit. `Resource` handles, by
    contrast, are live cursors — a handle kept across an edit reflects it, and reading a resource
    that was removed or renamed out from under it raises `KeyError`.

## Next steps

- [The formatter](formatting.md) — normalise layout after a batch of edits.
- [API reference](api.md) — the full mutation surface on `Script` and `Resource`.
- The [`examples/`](https://github.com/astro-tools/gmat-script/tree/main/examples) directory has
  runnable before/after scripts for a field edit and a resource rename.
