# Changelog

All notable changes to gmat-script are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] — 2026-06-08

gmat-script grows from a parser and formatter into a full editor toolchain: a GMAT field catalogue
reflected from R2026a, a linter that checks scripts against it, a Language Server Protocol server,
and a VS Code extension on the Marketplace and Open VSX. Everything still runs with no GMAT install —
the catalogue ships as data inside the wheel — and the grammar is unchanged, so every byte-for-byte
round-trip from earlier releases still holds.

### Added

- **Field catalogue (`gmat_script.catalog`)** — the semantics GMAT defines but the permissive grammar
  deliberately ignores: every resource type, its fields, and each field's type, default, allowed
  values, units, and reference target. Reflected from GMAT R2026a through `gmatpy` by a
  `tools/gen_catalog.py` generator and shipped as a version-pinned, provenance-stamped data file
  (`data/fields-R2026a.json`, 102 resource types and 2614 fields) inside the wheel, loaded by
  `load_catalog()`. Adding another GMAT release is a new data file, not a code change, and nothing
  downstream needs a GMAT install (#19).
- **Linter (`gmat-script lint`)** — a structural checker that reads the field catalogue: it flags
  unknown resource fields, enum and type violations, references to undeclared resources, duplicate
  names, and more, with inline suppression comments and `ruff`-style severities and exit codes. Each
  diagnostic carries a rule id, a location, and a message, and the engine is shared verbatim with the
  language server (#20).
- **Tree-sitter queries** — `highlights`, `locals`, and `tags` queries packaged with the
  `tree-sitter-gmat` grammar, giving editors resource / command / field highlighting, scope-aware
  local resolution, and a symbol index with no extra setup (#21).
- **Language server (`gmat-script[lsp]`)** — a `pygls` server, launched as `gmat-script-lsp` or
  `python -m gmat_script.lsp`, that brings the catalogue and linter to any LSP-capable editor: hover
  docs for a field's type, default, allowed values, and units; live diagnostics as you type;
  completion of resource names, the fields valid for the resource under the cursor, and enum values;
  go-to-definition and find-all-references; a document outline; and format-on-save via the canonical
  formatter (#22).
- **VS Code extension** — **GMAT Script**, published to the Visual Studio Marketplace and Open VSX.
  Bundled TextMate highlighting works the moment it installs; the richer language features come from
  the language server (`pip install "gmat-script[lsp]"`). `.script` and `.gmf` files get a file icon,
  comment / bracket configuration, and format-on-save on by default (#23).
- **Documentation** — new guide pages for the field catalogue, the linter, the language server, and
  the VS Code extension, plus README sections on editor tooling and the GMAT-free catalogue (#25).

### Changed

- `gmat-script` (PyPI) and `tree-sitter-gmat` (npm) continue to release in version lockstep, now at
  0.3.0. The grammar and generated parser are unchanged since 0.2.0; the npm package is republished
  to carry the new editor queries — an expanded `highlights.scm` and a new `locals.scm` (#21).

## [0.2.0] — 2026-06-08

A typed AST overlay over the v0.1 parse tree, a lossless mutation API, a canonical formatter, and a
`format` CLI with a pre-commit hook — every layer operating on script text alone, still with no GMAT,
C, or Node toolchain required and the byte-for-byte round-trip preserved for untouched input.

### Added

- **Typed AST overlay (`gmat_script.ast`)** — a typed view over the v0.1 CST: a `Script` root that
  splits configuration from the mission sequence at `BeginMissionSequence`, typed `Resource`s with
  dict-like dotted field access (`script.spacecraft["Sat"]["SMA"]`), an ordered, typed mission
  sequence (`GenericCommand`, `Assignment`, `FunctionCall`, `If` / `For` / `While`, `Target` /
  `Optimize` solver blocks, opaque `ScriptBlock`), and total, structural value coercion — numbers,
  strings, booleans, `ObjectRef` references, brace-lists, 1-D / 2-D arrays, and colon ranges — with a
  `RawValue` raw-text fallback. The overlay holds only references into the wrapped tree, so it
  re-emits byte-for-byte (#12).
- **Mutation API** — the overlay is now mutable while every untouched byte is preserved. `Resource`
  is a `MutableMapping` (`script.spacecraft["Sat"]["SMA"] = 7000`, `del`, plus `update` / `pop` /
  `clear`); `Script` gains `add_resource` / `remove_resource` / `rename_resource` (rewriting every
  textual reference form, or declaration-only) and `insert_command` / `remove_command` /
  `move_command` / `replace_command`. Each edit splices byte-ranges and re-parses, so only edited
  spans change and the result re-parses with zero `ERROR` nodes; a corrupting edit raises
  `MutationError` and leaves the source untouched (#13).
- **Canonical formatter** — `gmat_script.format(source, style="canonical")`, a deterministic,
  idempotent pretty-printer that re-lays-out in source order and never reorders, so
  `parse(format(x))` is structurally equal to `parse(x)` — safe on every save or as a pre-commit
  hook. Canonical form: single spacing around `=` / operators, one statement per line, per-resource
  grouping, four-space block indentation, and verbatim `BeginScript` bodies; auto-fixes are limited
  to dropping a redundant `GMAT` prefix and optional `;` and stripping trailing whitespace. The
  canonical-form contract is recorded as design decision D14 (#14).
- **`gmat-script format` CLI and pre-commit hook** — a `format` subcommand that rewrites files in
  place (`-` formats stdin), with read-only `--check` and `--diff` modes whose exit codes mirror
  `ruff format`. A shipped `.pre-commit-hooks.yaml` exposes `gmat-script-format` (in place) and
  `gmat-script-format-check` (check-only) for `.script` / `.gmf` files, needing no GMAT, C, or Node
  toolchain (#15).
- **Documentation** — new Typed AST, Editing, and Formatter guide pages; a refreshed README
  quick-start with mutate and format examples and a command-line section; and three runnable
  `examples/` scripts (programmatic field edit, resource rename, format-in-place) (#17).

### Changed

- `gmat-script` (PyPI) and `tree-sitter-gmat` (npm) continue to release in version lockstep. The
  grammar is unchanged since 0.1.1; this release carries it forward to 0.2.0 to keep the two packages
  at one version.

## [0.1.1] — 2026-06-07

### Added

- A README for the `tree-sitter-gmat` grammar package — describing the grammar, its editor /
  tree-sitter usage, and the link to the Python library — so the npm package page documents how to
  get started.

### Changed

- The `tree-sitter-gmat` package homepage now points to the documentation site.
- `gmat-script` (PyPI) and `tree-sitter-gmat` (npm) are now released in version lockstep. This patch
  carries the Python distribution forward unchanged from 0.1.0 to keep the two at the same version.

## [0.1.0] — 2026-06-07

Initial release: a tree-sitter grammar for GMAT mission scripts and an install-free Python parser
built on it.

### Added

- **Tree-sitter grammar** for GMAT `.script` and GmatFunction (`.gmf`) files — one grammar for both,
  a deliberately permissive superset: `Create <Type> <name>` accepts any resource type and unknown
  commands parse as generic command nodes, so a new resource or command never needs a grammar
  change. Every input re-emits **byte-for-byte**, comments and layout included. The acceptance bar is
  concrete: all 162 `.script` and 9 `.gmf` files shipped with NASA GMAT R2026a parse with zero
  `ERROR` nodes and round-trip exactly (#2, #4, #5, #8).
- **`parse()` API** — `parse(text)` returns a `Tree` that never raises on malformed input; syntax
  problems surface as `ERROR` / `MISSING` nodes localised through `tree.errors`, alongside
  `tree.has_errors` and a byte-exact `tree.to_source()` (#6, #9).
- **`gmat-script parse` CLI** — a fast, install-free syntax gate: it prints the syntax tree and exits
  non-zero on a syntax error, with a machine-readable `--json` `{file, ok, errors}` report (#7).
- **Packaging** — `pip install gmat-script` ships a precompiled grammar in a stable-ABI wheel for
  Python 3.10–3.12 on Linux, macOS, and Windows; the only runtime dependency is `tree-sitter`, and no
  C or Node toolchain — and never a GMAT install — is required (#3).
- **Documentation** — getting-started, the grammar-surface reference, the `parse` CLI and
  error-reporting guides, and the API reference, published to GitHub Pages (#3, #10).
