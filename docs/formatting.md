# The formatter

`format` re-emits a GMAT script in **canonical form**: one statement per line, consistent spacing
and indentation, per-resource grouping — with no reordering and no semantic change. It is a
deterministic, idempotent pretty-printer, safe to run on every save. This page covers the library
function; for the `gmat-script format` command and the pre-commit hook, see the
[CLI reference](cli.md#format-canonical-formatting).

```python
from gmat_script import format

messy = """\
Create Spacecraft   Sat
GMAT Sat.SMA=7000;
GMAT Sat.ECC = 0.01 ;


BeginMissionSequence
If Sat.ElapsedDays < 1
Propagate DefaultProp(Sat) {Sat.ElapsedDays = 1}
EndIf
"""

print(format(messy))
```

```text
Create Spacecraft Sat
Sat.SMA = 7000
Sat.ECC = 0.01

BeginMissionSequence

If Sat.ElapsedDays < 1
    Propagate DefaultProp(Sat) {Sat.ElapsedDays = 1}
EndIf
```

`format(source, style="canonical")` accepts the script text, an already-parsed
[`Tree`](api.md), or a [`Script`](typed-ast.md) — so you can format the result of a batch of
[edits](editing.md) without re-serialising first:

```python
from gmat_script import Script

script = Script.parse(messy)
script.set_field("Sat", "SMA", 7200)
canonical = format(script)             # format a Script directly
```

It returns the canonical source ending in a single trailing newline (the file's own LF / CRLF style
is preserved). A script with syntax errors raises `ValueError` rather than risk corrupting it, as
does an unrecognised `style`; `canonical` is the only style today — the parameter is the seam for
future ones.

## The canonical form

The formatter **re-lays-out; it never reorders.** Resources, fields, and commands are emitted in
source order — it touches *layout*, not *sequence*. A resource is one grouped block, and the blocks
keep their authored order; field order is source order, preserving GMAT's last-write-wins semantics
exactly.

- **One statement per line** — `...` line continuations are folded away. A single space around `=`
  and binary operators; `.` and unary signs are tight; colon ranges are tight (`1:2:10`). Brace-lists
  `{a, b}`, index / call argument lists `[1, 1]`, and matrices `[r1; r2]` follow the same conventions
  as the value emitter, so the formatter and the [mutation layer](editing.md) emit values
  identically.
- **Per-resource grouping with structural blank lines.** In the configuration section each `Create`
  is glued to its own assignments with no blank line between them, and exactly one blank line
  precedes each new `Create` / `#Include` group and the `BeginMissionSequence` marker. In the mission
  sequence the author's blank lines are preserved (collapsed to at most one), keeping their grouping
  intent.
- **Indentation** is four spaces per nesting level inside `If` / `For` / `While` / `Target` /
  `Optimize` blocks (and `Else` branches). A `BeginScript … EndScript` body is **opaque**: it is
  preserved verbatim — only the `BeginScript` line is re-indented.
- **Literal spellings are preserved verbatim.** Numbers, strings, and identifiers are never rewritten
  (`1.0e-11` is not normalised to `1e-11`) — formatting is pure layout.

The **only auto-fixes** are the three things that are layout, not meaning: dropping the redundant
leading `GMAT` keyword on an assignment, dropping the optional trailing `;`, and removing trailing
whitespace.

### Comments

An own-line comment attaches to the statement that *follows* it and is glued directly above it; a
same-line comment stays trailing. Blank gaps within a run of own-line comments are preserved
(collapsed to at most one), so a file header stays separated from a section banner while the banner
hugs its `Create`. A trailing comment is re-emitted with a `;` terminating the statement
(`EndTarget; % …`) — without it, a re-parse would drop the comment, so the `;` is required to keep
the formatter idempotent.

## The guarantees

The canonical form is chosen so two strong invariants hold for every script:

- **Idempotent** — formatting an already-canonical script changes nothing: `format(format(x))`
  equals `format(x)`. This is what makes it safe as a `--check` gate and a pre-commit hook.
- **Semantic-preserving** — `parse(format(x))` is structurally equal to `parse(x)`: no resource,
  field, or command is added, dropped, reordered, or altered. The formatter rewrites how the script
  is laid out, never what it says.

Together these mean you can run it unattended, on every save, and it produces minimal diffs. For the
reasoning behind the order-preserving design, see the [design decisions](design/decisions.md).

## Next steps

- [CLI reference](cli.md#format-canonical-formatting) — the `gmat-script format` command
  (`--check` / `--diff`) and the [pre-commit hook](cli.md#pre-commit-hook).
- [Editing](editing.md) — the mutation API that shares this canonical value emission.
- [API reference](api.md) — the `format` signature in full.
