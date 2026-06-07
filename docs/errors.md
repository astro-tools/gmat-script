# Error reporting

## Nodes, never exceptions

A malformed or incomplete script **never raises** from `parse`. tree-sitter's error recovery yields a
usable partial tree with `ERROR` and `MISSING` nodes localised to the broken construct — the property
that makes editor-grade feedback on a half-typed buffer possible. The library surfaces them as data
on the returned `Tree`:

- `tree.has_errors` — a boolean.
- `tree.errors` — a list of error records, in source order, empty if the script parsed cleanly.

```python
from gmat_script import parse

bad = parse("Create Spacecraft Sat\nSat.SMA = \n")

bad.has_errors   # True
for error in bad.errors:
    print(error.type, error.start.line, error.start.column, error.message)
# ERROR 2 1 unexpected token
```

## The error record

Each entry in `tree.errors` is an `ErrorNode`:

| Field | Type | Meaning |
|-------|------|---------|
| `type` | `str` | `"ERROR"` for an unexpected-token node, `"MISSING"` for a token the grammar expected but did not find |
| `start` | `Position` | where the broken construct begins |
| `end` | `Position` | where it ends |
| `message` | `str` | a short description |

A `Position` is a 1-indexed `line` / `column` pair — the compiler / human convention. (tree-sitter's
native points are 0-indexed; the wrapper converts.)

```python
error = bad.errors[0]
error.type             # 'ERROR'
error.start.line       # 2
error.start.column     # 1
error.end.column       # 10
error.message          # 'unexpected token'
```

`ErrorNode` and `Position` are frozen dataclasses, so they are hashable and safe to compare or store.

## `has_errors` is authoritative

`tree.has_errors` reads tree-sitter's own `has_error` flag, which is the source of truth. It counts a
`MISSING` instance of a *hidden* token — this grammar's statement terminator — that the node-child
API does not expose. `tree.errors` is reconciled with that flag, so it never under-reports relative
to `has_errors`: if a tree is flagged erroneous, `tree.errors` carries at least one record. Branch on
`has_errors` for the yes/no question; iterate `tree.errors` for the locations.

## On the command line

The `parse` CLI turns this model into an exit code and diagnostics:

- The exit code is `1` when any file has an `ERROR` / `MISSING` node, `0` otherwise (and `2` for a
  file that could not be read).
- Each error prints as `FILE:line:col: <message>` on stderr.
- `--json` emits the same records as a `{file, ok, errors}` report, with `start` / `end` positions
  and the `type` / `message` fields above.

```console
$ printf 'Create Spacecraft Sat\nSat.SMA = \n' | gmat-script parse --json -
{
  "file": "<stdin>",
  "ok": false,
  "errors": [
    {
      "type": "ERROR",
      "start": { "line": 2, "column": 1 },
      "end":   { "line": 2, "column": 10 },
      "message": "unexpected token"
    }
  ]
}
```

See the [`parse` CLI reference](cli.md) for the full output contract.

## Parsing is not validation

"Does it parse" is a **structural** question: are the tokens well-formed GMAT script syntax. It is not
whether a field name exists, an enum value is valid, or the mission would run or converge — those are
semantics that need a field catalogue (a later layer) or GMAT itself. A script can parse with zero
errors and still be rejected by GMAT at run time, and that is by design: the grammar is a permissive
superset, and stricter rules belong to the linter and to GMAT.
