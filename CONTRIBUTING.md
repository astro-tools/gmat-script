# Contributing to gmat-script

Thanks for your interest. This page is the one place to learn the workflow.

## Getting set up

```bash
git clone https://github.com/astro-tools/gmat-script.git
cd gmat-script
uv sync --all-groups
```

This installs the package, its runtime dependency, and the dev and docs groups. Building the
package compiles the vendored grammar, so a **C compiler** must be present (gcc/clang on
Linux/macOS, the Visual Studio Build Tools on Windows). You do **not** need Node or the tree-sitter
CLI unless you are editing the grammar itself (see below) — the generated parser is committed.

### Editing the grammar

The tree-sitter grammar lives under `tree-sitter-gmat/`. Changing `grammar.js` means regenerating
the committed parser and running the corpus tests, which needs Node:

```bash
cd tree-sitter-gmat
npm install            # fetches the pinned tree-sitter CLI
npx tree-sitter generate   # regenerates src/parser.c — commit the result
npx tree-sitter test       # runs the corpus tests under test/corpus/
```

CI regenerates the parser with the pinned CLI and fails if the committed `src/parser.c` is stale,
so always commit the regenerated output alongside the grammar change.

## Branches and PRs

- One issue per branch. Branch names use a short prefix for type:
  - `feat/<slug>` — new capability, tied to a `type:feature` issue.
  - `fix/<slug>` — bug fix, tied to a `type:bug` issue.
  - `chore/<slug>` — infra / tooling / hygiene.
  - `docs/<slug>` — docs-only change.
- Open a PR against `main`. Put `Closes #<N>` in the PR description so the issue auto-closes on
  merge and the project board advances the card to Done.
- Squash-merge is the only merge method. The PR title becomes the squash commit subject — write it
  as a complete imperative sentence.

## Local checks before pushing

```bash
uv run ruff check                # lint
uv run ruff format --check       # formatting (CI runs this too — it is part of the lint gate)
uv run mypy                      # types (strict)
uv run pytest                    # tests
```

CI re-runs these on Ubuntu, Windows, and macOS across Python 3.10, 3.11, and 3.12, plus a
minimal-install smoke job, the grammar-build + `tree-sitter test` job, and the corpus parse-coverage
job.

## Commit messages

Keep them short and imperative. One subject line, optional body.

Do not include AI or tool attribution trailers in commits, PR titles, PR descriptions, or comments.

## Scope discipline

gmat-script reads, checks, formats, and transforms GMAT script *text*; it does not run missions —
that is GMAT's job — and it requires no GMAT install at runtime. Before opening a feature issue,
check the [design decisions](docs/design/decisions.md) and existing issues to make sure the work
belongs here.

## Questions

Open a [discussion](https://github.com/orgs/astro-tools/discussions) rather than an issue for
open-ended questions, usage help, or brainstorming. The astro-tools org runs a single shared
discussions space — there is no per-repo discussions board.
