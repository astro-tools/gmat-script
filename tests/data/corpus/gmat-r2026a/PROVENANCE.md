# GMAT R2026a stock corpus

This directory is the parser's **acceptance oracle**: the unmodified sample scripts that ship with
NASA's General Mission Analysis Tool (GMAT), release **R2026a**. The grammar is "done" for a release
when every file here parses with zero `ERROR`/`MISSING` nodes and re-emits byte-for-byte.

## What's here

Sourced verbatim from a GMAT R2026a installation, with the install's directory layout preserved:

- `samples/` — the **162** `.script` files from the install's `samples/` tree (all subdirectories),
  plus `samples/Navigation/Ex_RICdelta.gmf`.
- `userfunctions/gmat/` — the **8** `.gmf` GmatFunctions from the install's `userfunctions/gmat/`
  tree.

That is **162 `.script` + 9 `.gmf`** in total. The nine `.gmf` are the full GmatFunction-header
oracle (the `function` header is wider than a single form — see the design decisions, D10), which is
why the eight `userfunctions/gmat/` functions are included alongside the one under `samples/`.

The subtree is preserved rather than flattened because a few sample basenames repeat across
subdirectories (e.g. `Ex_AlgebraicOptimization.script`, `Ex_MinFuelLunarTransfer.script`).

## What's deliberately *not* here

Only the `.script` and `.gmf` **text** is included. The samples' data dependencies — ephemerides,
SPICE kernels, support files, and `#Include` targets — are omitted: the parser treats file paths and
`#Include` directives as opaque string literals and never resolves or reads them, so none of those
files are needed to parse the corpus.

## Line endings

The files are committed with their **original, mixed** line endings (a subset use CRLF, the rest LF).
The library performs no EOL normalisation, and the repository's `.gitattributes` marks `*.script`,
`*.gmf`, and everything under `tests/data/` as `-text` so Git does not rewrite line endings on
checkout — without that, the byte-for-byte round-trip assertions would fail on Windows.

## Licensing

GMAT and its bundled sample scripts are distributed under the **Apache License 2.0** (see the
`LICENSE` file in this directory, copied verbatim from the GMAT distribution). The samples carry no
separate per-file copyright notices and the distribution ships no `NOTICE` file; redistribution of
the corpus under Apache-2.0 is therefore permitted with the license text retained, which this
directory does.

GMAT is developed by NASA's Goddard Space Flight Center and the GMAT development team. gmat-script is
not affiliated with or endorsed by NASA; the corpus is included solely as a parsing test oracle.

## Refreshing the corpus

To regenerate this directory from a GMAT R2026a installation, copy — preserving the relative
directory structure and the original bytes — every `*.script` and `*.gmf` under the install's
`samples/` tree and every `*.gmf` under its `userfunctions/gmat/` tree, then copy the install's
`License.txt` here as `LICENSE`. The harness asserts the resulting file counts (see
`tests/check_corpus.py`), so an incomplete copy fails loudly rather than silently.
