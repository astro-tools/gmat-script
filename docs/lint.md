# Linting

The linter statically checks a script for *structural* problems — references to resources that were
never created, fields and types GMAT does not define, values that contradict a field's type or
enumeration — by walking the [typed AST](typed-ast.md) and consulting the bundled field catalogue. It
is install-free (no GMAT, C, or Node toolchain) and never runs the mission: it reasons about the
script as text, not about whether a targeter converges or an orbit is physical.

Use it from Python with `lint`, or from the shell with [`gmat-script lint`](cli.md#lint-static-checks).

## The `lint` function

`lint` accepts source text, a parsed [`Tree`](api.md), or a [`Script`](typed-ast.md) overlay, and
returns a list of `Diagnostic` records sorted by position:

```python
from gmat_script import lint

source = """
Create Spacecraft Sat
Sat.SMA = 'high'
Create Thruster Thr
Sat.Tanks = {Thr}
BeginMissionSequence
Propagate Sat
"""

for d in lint(source):
    print(f"{d.start.line}:{d.start.column} {d.severity} {d.rule}: {d.message}")
```

```
3:11 warning type-mismatch: field 'SMA' expects a number, got a quoted string
5:14 warning ref-target-mismatch: Sat.Tanks expects a FuelTank, but 'Thr' is a Thruster
```

Each `Diagnostic` carries the `rule` code, a `Severity` (`error` / `warning` / `info`), a `message`,
and 1-indexed `start` / `end` [`Position`](api.md) ranges. A clean script returns an empty list.

A script with *syntax* errors short-circuits: `lint` returns the syntax errors alone (as
`syntax-error` diagnostics) and runs no structural rule, because the typed model is unreliable on a
broken parse. Fix the syntax first — `gmat-script parse` reports it the same way.

### Selecting rules and the catalogue version

Each rule is individually toggleable. Pass `select` to run only an allow-list, or `ignore` to drop a
deny-list:

```python
lint(source, select=["unknown-field", "type-mismatch"])
lint(source, ignore=["unused-resource"])
```

The semantics the rules check against are pinned to a GMAT release. `lint(source,
target_version="R2026a")` selects a specific shipped catalogue; the default is the newest available.

## The rules

| Rule | Severity | Catches |
|------|----------|---------|
| `unknown-resource-type` | error | A `Create <Type>` whose type GMAT does not define (a typo, or a plugin type not recognised). |
| `undeclared-reference` | error | An object-reference field naming a resource that was never created (and is not a built-in). |
| `duplicate-name` | error | Two resources created with the same name. |
| `unknown-field` | warning | A field not in the catalogue for its resource type — usually a misspelling. |
| `type-mismatch` | warning | A value whose type plainly contradicts the field's type (a string given to a real field, …). |
| `enum-violation` | warning | A value outside a field's allowed enumeration. |
| `ref-target-mismatch` | warning | An object-reference field pointing at a resource of the wrong type. |
| `unused-resource` | info | A resource that is created but never referenced anywhere. |

A few rules deliberately stay quiet rather than risk a false positive. `unknown-field`,
`type-mismatch`, `enum-violation`, and `ref-target-mismatch` skip resource types the catalogue does
not carry (plugin types), nested sub-object paths (`FM.GravityField.Earth.Degree`), and fields whose
catalogue type is ambiguous — degrading to "no finding" wherever it cannot be sure.

## Suppressing a finding

Two inline comment directives turn rules off for part of a file. Because GMAT comments run from a `%`
to the end of the line, a directive can sit at the end of the offending line or on its own.

`disable-line` suppresses the listed rules on the line the comment is on — ideal for a one-off:

```text
Create MyPluginType Widget   % gmat-script: disable-line=unknown-resource-type
```

`disable` suppresses them from its line to the end of the file — put it at the top to silence a rule
for the whole script:

```text
% gmat-script: disable=unused-resource
```

Omit the `=<rules>` clause to suppress *every* rule for that scope:

```text
Sat.SomethingOdd = 1   % gmat-script: disable-line
```

List several rules with commas: `% gmat-script: disable-line=unknown-field,type-mismatch`.

## From the command line

`gmat-script lint FILE ...` runs the same checks as a CI gate, printing one
`FILE:line:col: severity rule: message` line per finding and exiting non-zero on an error-severity
diagnostic. See [the CLI reference](cli.md#lint-static-checks) for output formats and exit codes.
