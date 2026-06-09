# gmat-script

Parse, format, lint, and edit [GMAT](https://gmat.gsfc.nasa.gov/) `.script` mission files from
Python — built on a [tree-sitter](https://tree-sitter.github.io/tree-sitter/) grammar. The whole
stack operates on script **text**; nothing here requires a GMAT install.

It ships the parser, a typed AST with a mutation API, a canonical formatter, and a static linter,
plus a `gmat-script` command-line tool over the same engine. Editor tooling builds on top of the same
tree as it lands.

## Install

```bash
pip install gmat-script
```

gmat-script supports Python 3.10, 3.11, and 3.12. The wheel bundles a precompiled grammar, so the
install needs no C or Node toolchain — and never GMAT.

## Quick start

**Parse** a script — `parse` never raises on malformed input: it returns a tree carrying `ERROR` /
`MISSING` nodes localised to the broken construct, surfaced through `tree.errors`.

```python
from gmat_script import parse

tree = parse("Create Spacecraft Sat\nSat.SMA = 7000\n")

tree.has_errors      # False — the script is well-formed
tree.to_source()     # round-trips byte-for-byte to the input
```

**Edit** it through the typed AST — typed resources with dict-like field access. Each edit splices
the source and re-parses, so untouched bytes are never disturbed and a corrupting edit is refused.

```python
from gmat_script import Script

script = Script.parse("Create Spacecraft Sat\nSat.SMA = 7000\n")

script.spacecraft["Sat"]["SMA"]         # 7000 — read a field
script.spacecraft["Sat"]["SMA"] = 8000  # set it
script.rename_resource("Sat", "MainSat")  # rename, rewriting references
script.to_source()                      # the edited source
```

**Format** it — a deterministic, idempotent pretty-printer that re-lays-out without reordering.

```python
from gmat_script import format

format("GMAT Sat.SMA=7000;\n")   # 'Sat.SMA = 7000\n'
```

**Lint** it — structural checks against the bundled field catalogue: unknown types and fields,
type / enum / reference-target mismatches, duplicate names, unused or undeclared references.

```python
from gmat_script import lint

for d in lint("Create Spcecraft Sat\n"):
    print(d.rule, d.message)   # unknown-resource-type unknown resource type 'Spcecraft'
```

## Command line

The same engine drives the `gmat-script` command-line tool — a fast, install-free gate for CI:

```console
$ gmat-script parse mission.script     # print the syntax tree; exit non-zero on a syntax error
$ gmat-script format --check *.script   # fail if any file is not in canonical form
$ gmat-script lint mission.script       # report structural problems; exit non-zero on an error
```

`format` rewrites files in place by default, or checks / diffs them with `ruff`-style exit codes. It
also ships [pre-commit](https://pre-commit.com/) hooks, so scripts are formatted on every commit —
add the repo to your `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/astro-tools/gmat-script
    rev: v0.3.0
    hooks:
      - id: gmat-script-format        # auto-format on commit
      # - id: gmat-script-format-check  # or: check only, never write (CI)
```

## Editor tooling

[![VS Marketplace](https://img.shields.io/visual-studio-marketplace/v/astro-tools.gmat-mission-script?label=VS%20Marketplace&color=311B92)](https://marketplace.visualstudio.com/items?itemName=astro-tools.gmat-mission-script)
[![Open VSX](https://img.shields.io/open-vsx/v/astro-tools/gmat-mission-script?label=Open%20VSX&color=311B92)](https://open-vsx.org/extension/astro-tools/gmat-mission-script)

The same engine drives an editor experience — highlighting, hover docs, live diagnostics, completion,
go-to-definition, an outline, and format-on-save.

- **VS Code** — the **GMAT Script** extension, on the
  [Visual Studio Marketplace](https://marketplace.visualstudio.com/items?itemName=astro-tools.gmat-mission-script)
  and [Open VSX](https://open-vsx.org/extension/astro-tools/gmat-mission-script). Highlighting works on
  install; the richer features come from the language server (`pip install "gmat-script[lsp]"`).
- **Neovim, Emacs, Helix, and the rest** — a Language Server Protocol server (`gmat-script-lsp`,
  from the `lsp` extra) backs any LSP-capable editor.

See the [VS Code extension guide](https://astro-tools.github.io/gmat-script/vscode/) and the
[language server guide](https://astro-tools.github.io/gmat-script/lsp/).

## The grammar surface

The tree-sitter grammar parses GMAT scripts (`.script`) and GmatFunctions (`.gmf`) — the same
grammar for both — and re-emits any input **byte-for-byte**, comments and layout included. It is a
deliberately permissive superset: `Create <Type> <name>` accepts any resource type and unknown
command keywords parse as generic command nodes, so a new resource or command never needs a grammar
change. The acceptance bar is concrete: every one of the 162 `.script` and 9 `.gmf` files shipped
with NASA GMAT R2026a parses with zero errors and round-trips exactly.

See the [grammar surface reference](https://astro-tools.github.io/gmat-script/grammar-surface/) for
the node taxonomy and the covered / deferred constructs.

## The GMAT-free guarantee

Reading, checking, formatting, and transforming a script needs only this package — never a GMAT
install. `pip install gmat-script` never pulls in, requires, or looks for GMAT or `gmatpy`; the only
runtime dependency is `tree-sitter`. (GMAT is used at build time only, to generate the field
catalogue the linter checks against.)

## GMAT version

The grammar targets **GMAT R2026a**. Because it never enumerates resource types or command keywords,
parsing is effectively version-independent — scripts from other releases parse too. Semantics that
*do* vary by release (valid field names, enums, defaults) belong to the linter and are scoped
to R2026a.

Those semantics live in a **field catalogue** reflected from R2026a (102 resource types, 2614
fields) and shipped as data inside the wheel, so the linter and editor tooling need no GMAT install.
It is version-pinned and provenance-stamped, selectable per release, and adding another GMAT version
is a data file — not a code change. See [the field catalogue](https://astro-tools.github.io/gmat-script/catalogue/).

## What gmat-script is not

- **Not a propagator or astrodynamics engine.** It reads and transforms script *text*; it computes
  no orbits and models no physics.
- **Not a mission runner.** Running a script is GMAT's job — gmat-script does no execution.
- **Not an engine-dependent validator.** "Does it parse" is a structural question answered here;
  "does it run / converge" is a different question that needs GMAT.

## Documentation

Full documentation — getting started, the grammar surface, the typed AST and editing guides, the
formatter, the linter and the field catalogue, the command-line tool, the language server and VS Code
extension, the error-reporting model, and the API reference — is at
**[astro-tools.github.io/gmat-script](https://astro-tools.github.io/gmat-script/)**.

## License

[MIT](LICENSE) — part of the [astro-tools](https://github.com/astro-tools) organization.
