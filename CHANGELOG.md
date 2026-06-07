# Changelog

All notable changes to gmat-script are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
