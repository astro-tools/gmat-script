# Design decisions

The running decision log for gmat-script — the choices that fix the grammar scope, the concrete
syntax tree (CST) node taxonomy, and the v0.1 public surface, recorded with their rationale so the
implementation has one contract to build against. New decisions append to this file.

These decisions resolve the open questions the charter deferred to kickoff and **freeze the grammar
scope + CST node taxonomy on paper** before any grammar code lands. They are grounded in a survey of
the GMAT R2026a stock corpus — the **162 `.script` files + 1 `.gmf`** shipped in the `samples/`
directory of a GMAT R2026a install — cross-checked against the GMAT User's Guide; the empirical
figures cited throughout come from that survey (reproduced in the appendix). The corpus is the
acceptance oracle: the grammar is "done" for v0.1 when every one of those files parses with zero
`ERROR` nodes and re-emits byte-for-byte.

---

## The language model

A GMAT script has two sections in strict order:

1. **Configuration** — `Create` resource declarations and literal `resource.field = value`
   assignments. Populates the Resources tree. No command execution.
2. **Mission sequence** — everything after the `BeginMissionSequence` marker: an ordered list of
   commands and control-flow / solver blocks.

The split is positional, not lexical: the *same* assignment syntax appears in both sections, and
which section a statement is in is determined by its position relative to `BeginMissionSequence`, not
by a different node type. GMAT enforces extra rules per section (configuration assignments are
literal-only; `Create` is illegal after `BeginMissionSequence`) — **those are semantic rules the
linter owns (v0.3), not the grammar.** The grammar is deliberately permissive: it accepts the
superset and lets later layers reject what GMAT would.

GmatFunction (`.gmf`) files share the entire resource / command surface; they add only a `function`
header and `Global` declarations and are parsed by the same grammar (see D10).

---

## D1 — repository directory structure (and the grammar's place in it)

The whole repository layout is fixed here so the grammar's location is a decision *within a known
whole*, not in isolation. The scaffold (#3) creates this tree; later milestones fill in the
directories marked for them. The single load-bearing choice is that **the tree-sitter grammar lives
in-repo** under `tree-sitter-gmat/` (a self-contained, npm-publishable package), not in a separate
`astro-tools/tree-sitter-gmat` repo.

```text
gmat-script/
├── tree-sitter-gmat/            # the grammar package — self-contained, npm-publishable      (v0.1, #3/#4/#5)
│   ├── grammar.js               #   the hand-written grammar
│   ├── package.json             #   npm metadata; tree-sitter-cli as a devDependency
│   ├── src/                     #   `tree-sitter generate` output (committed)
│   │   ├── parser.c             #     the generated parser
│   │   ├── grammar.json
│   │   └── node-types.json
│   ├── bindings/python/         #   generated: exposes the compiled grammar's language() capsule
│   │   ├── tree_sitter_gmat/__init__.py
│   │   └── binding.c
│   ├── queries/                 #   highlights.scm, locals.scm, tags.scm   (dir v0.1; content v0.3, #21)
│   └── test/corpus/             #   tree-sitter corpus tests — committed expected S-expressions
├── src/                         # src-layout Python package (per #3)
│   └── gmat_script/             #   py.typed, fully annotated
│       ├── __init__.py          #     re-exports parse() at v0.1; format/lint added at their milestone
│       ├── py.typed
│       ├── parser.py            #     parse(text) -> Tree; loads the vendored grammar             (v0.1, #6)
│       ├── cli.py               #     the `gmat-script` console script                            (v0.1: parse; +format/lint later)
│       ├── _grammar/            #     the VENDORED compiled grammar shipped in the wheel          (v0.1 build output; form per D2/#3)
│       ├── ast/                 #     typed nodes + dict access + mutation API                    (v0.2, #12/#13)
│       ├── format.py            #     canonical, idempotent formatter                             (v0.2, #14)
│       ├── lint/                #     rule engine + rules + scope/reference resolution            (v0.3, #20)
│       ├── catalog.py           #     catalogue loader (NO gmatpy import)                         (v0.3, #19)
│       ├── data/fields-R2026a.json  # shipped reflection catalogue                                (v0.3, #19)
│       ├── lsp/                 #     pygls language server                                       (v0.3, #22)
│       └── tools/gen_catalog.py #     build-time only; the ONLY gmatpy-touching code              (v0.3, #19)
├── tests/                       # pytest suites
│   └── data/                    #   golden corpus fixtures (-text in .gitattributes)
├── docs/                        # MkDocs-Material site
│   ├── index.md
│   └── design/decisions.md      #   this file
├── editors/vscode/              # VS Code extension — LSP client + TextMate grammar              (v0.3, #23)
├── .github/
│   ├── workflows/               #   ci.yml, docs.yml, release.yml
│   ├── ISSUE_TEMPLATE/          #   bug / feature / "does not parse" / chore
│   ├── PULL_REQUEST_TEMPLATE.md
│   └── CODEOWNERS
├── pyproject.toml               # PEP 621 + Hatchling; declares the `tree-sitter` dep + the grammar build hook
├── mkdocs.yml
├── .gitattributes               # tests/data/** -text, *.script -text, *.gmf -text (D6)
├── .gitignore
├── .python-version
├── CHANGELOG.md                 # aggregated at release-cut
├── CONTRIBUTING.md              # notes lint CI includes `ruff format --check`
├── CITATION.cff
├── LICENSE                      # MIT
└── README.md
```

**The grammar → wheel bridge.** `tree-sitter-gmat/` holds the *source* grammar and the generated
`parser.c`; the Python wheel ships a *compiled* form of it. The modern `tree-sitter` runtime loads a
grammar via `Language(<module>.language())` — a PyCapsule from a compiled extension, not a `.so` path
— and grammars normally ship as their own binary wheels (`tree-sitter-python`, etc.). gmat-script
**does not** publish a separate `tree-sitter-gmat` PyPI wheel and depend on it; instead the Hatchling
build compiles the grammar (`tree-sitter-gmat/src/parser.c` + the Python binding) and **vendors it
into the single `gmat_script` wheel** (shown as `_grammar/`), so `parser.py` loads it with no
node/C toolchain and no second install (D9: never GMAT either). The exact vendored form — one bundled
extension module vs. an embedded `tree_sitter_gmat` module — is the build mechanic deferred to D2/#3;
this decision fixes only that it is one wheel, vendored, toolchain-free.

**Rationale (in-repo, and why the whole shape).** For v0.x the grammar and the Python library evolve
in lockstep — every grammar change needs a matching corpus / binding / build change — so one repo
keeps them atomic in a single PR and a single CI run, with no cross-repo version dance and no second
release to coordinate. The `src/`-layout Python package (per #3) keeps import-time hygiene (tests run
against the installed wheel, not the working tree) and gives the vendored grammar a clean home under
`gmat_script/`. The grammar subdir is still a *complete* tree-sitter package with its own
`package.json`, so it publishes to **npm** independently (per tree-sitter convention) for editor
consumers that want highlighting without the Python library. `queries/` is shared by both the editor
highlighting and the `tags` go-to-definition feature, so it lives with the grammar, not the editor.

**Does the in-repo choice still hold given the full layout? Yes — more so.** The two realistic
alternatives both get worse once the structure is explicit: (a) a split grammar repo published as a
separate `tree-sitter-gmat` *PyPI* wheel would make it a runtime dependency of `gmat_script` with its
own release cadence — exactly the cross-repo version dance the single wheel avoids; (b) a split repo
pulled in as a git submodule would break the "one PR, one CI run" lockstep the grammar+corpus+binding
need during active development. So the grammar stays in-repo for v0.x. A split to a dedicated grammar
repo is **revisited at v1.0**, once the grammar is frozen and the npm package has external consumers
whose cadence diverges from the Python library's.

## D2 — dependencies, version pins, and the vendoring strategy

**The Python binding is the PyPI package `tree-sitter`.** The bindings live in the
`tree-sitter/py-tree-sitter` GitHub repo but ship to PyPI under the distribution name **`tree-sitter`**
— there is no separate `py-tree-sitter` distribution. The runtime dependency is therefore a single
package, `tree-sitter`, *not* the two packages ("`tree-sitter` + `py-tree-sitter`") the early issue
drafts imply. (Forward note for the scaffold, #3: `pyproject.toml` declares one runtime dep,
`tree-sitter`.)

**Pins.**

| Component | Pin | Role |
|-----------|-----|------|
| `tree-sitter` (PyPI, the Python runtime + bindings) | `>=0.25,<0.26` (0.25.2 current; `requires-python >=3.10`) | load the vendored grammar, walk trees at runtime |
| `tree-sitter-cli` (npm, dev-only) | the `0.25.x` line, tracking the runtime | generate `parser.c` and run the grammar corpus tests |

The exact versions are locked in `uv.lock` once the scaffold (#3) lands. The binding's
`requires-python >=3.10` lines up exactly with the org's 3.10 / 3.11 / 3.12 support matrix.

**ABI alignment is the load-bearing constraint.** The CLI generates a parser at a tree-sitter ABI
version; the runtime can only load parsers at or below the ABI it supports. So the **CLI line tracks
the runtime line** (both `0.25.x`) rather than chasing the newest CLI (0.26.x), which could emit an
ABI the pinned runtime cannot load. The grammar-build CI job (wired in #3) is the drift detector: it
regenerates the parser with the pinned CLI and runs the corpus tests, so an ABI mismatch fails CI
rather than a user's `import`.

**Vendoring — the GMAT-free, toolchain-free guarantee.** The wheel **vendors the compiled grammar**
so `pip install gmat-script` needs neither a C toolchain nor Node nor a tree-sitter CLI, and never
GMAT (see D9). The exact build mechanic (ship the prebuilt parser vs. compile the bundled `parser.c`
at wheel-build time via the Hatchling hook) is **#3's call** — this decision fixes only the
*guarantee*: a clean `pip install` on any of the three OSes / three Pythons imports `gmat_script` and
parses, with no toolchain present.

## D3 — the CST node taxonomy (the contract #4 / #5 / #6 implement)

This is the contract every downstream layer reads. The names below are frozen for v0.1; the grammar
(#4 lexical + configuration, #5 mission sequence) implements them, the bindings (#6) expose them, and
the typed-AST overlay (v0.2, #12) wraps them.

**Generic over enumerated, everywhere.** Resource types and command keywords are *not* enumerated in
the grammar. The corpus has **67 distinct `Create` types** and ~**37 distinct command keywords**, and
GMAT plugins add more; baking the set into the grammar would force a grammar change for every new
resource or command. So:

- `Create <Type> <name>…` parses with `<Type>` as **any identifier** — one generic `create_command`,
  not one rule per resource family. Type validity is the linter's job (v0.3), against the
  reflection catalogue (#19).
- An unrecognised command keyword parses as a **generic `command` node**, not an error. Only the
  constructs that the grammar *structurally* needs to understand — assignments, function-call
  commands, and the begin/end blocks that must be matched — get their own node type.

### Node types

**Top level / structural**

| Node | Surface | Notes |
|------|---------|-------|
| `source_file` | the whole file | root |
| `comment` | `% …` to end of line | an `extra` — attaches anywhere, including mid-construct; no block comments; `%` is not a comment inside a string |
| `include` | `#Include 'path'` | preprocessor directive; top-level only; trailing `;` optional (both forms occur in the corpus) |
| `create_command` | `Create <type> <name> [<name> …]` | `type` = identifier; one or more `name`s (e.g. `Create Variable x y z`); `Array` decl carries the `[r,c]` size: `Create Array A[3,3]` |
| `begin_mission_sequence` | `BeginMissionSequence` | the configuration ↔ sequence boundary (a marker command) |

**Statements / commands**

| Node | Surface | Notes |
|------|---------|-------|
| `assignment_command` | `[GMAT] [label] <lhs> = <rhs>` | optional leading `GMAT` keyword token; optional `'label'`; `<lhs>` is a reference or array-indexed target; `<rhs>` is the full expression grammar (below). Same node in both sections — D5 |
| `function_call_command` | `[<out>, …] = <name>(<args>)` | bracket-list LHS distinguishes it from an assignment; `<name>` may be dotted (`Python.IODFunctions.ThreePositionIOD`); covers the GmatFunction / `CallPythonFunction` call form (see D4 on `CallGmat/MatlabFunction`) |
| `command` | `<keyword> [label] <args…>` | the generic command: `Propagate`, `Maneuver`, `Report`, `Toggle`, `Save`, `Write`, `Set`, `Stop`, `Achieve`, `Vary`, `Minimize`, `NonlinearConstraint`, `PenUp`/`PenDown`, `MarkPoint`, `ClearPlot`, `CommandEcho`, `RunSimulator`/`RunEstimator`/`RunSmoother`, `Global`, `BeginFiniteBurn`/`EndFiniteBurn`, `BeginFileThrust`/`EndFileThrust`, and any unrecognised keyword. Args use the value grammar plus the `Prop(Sat) {…}` / `DC(…)` argument forms |

**Blocks** (lexical begin/end that must be matched, with a nested command body)

| Node | Surface | Notes |
|------|---------|-------|
| `if_statement` | `If <cond> … [Else …] EndIf` | `Else` observed; `ElseIf` is **not** in the corpus — deferred / best-effort (D4) |
| `for_statement` | `For <var> = <range> … EndFor` | `start:step:stop` or `start:stop` range |
| `while_statement` | `While <cond> … EndWhile` | |
| `target_statement` | `Target <solver> [{opts}] … EndTarget` | nests `Vary`/`Achieve`/etc. as ordinary `command`s |
| `optimize_statement` | `Optimize <solver> [{opts}] … EndOptimize` | nests `Vary`/`Minimize`/`NonlinearConstraint` |
| `script_block` | `BeginScript … EndScript` | **opaque**: the body is a single raw-text token, not re-parsed (D4) |

> **`BeginFiniteBurn`/`EndFiniteBurn` and `BeginFileThrust`/`EndFileThrust` are *not* blocks.** In
> GMAT the commands they bracket are flat siblings, not a nested body, so they parse as two ordinary
> `command` nodes. Pairing them (if ever needed) is an AST-layer concern, not a grammar one. This is
> the one place the charter's "control-flow / solver blocks" framing is looser than the real grammar.

**Values / expressions** (the RHS grammar — richer than the charter's "value grammar")

| Node | Surface | Notes |
|------|---------|-------|
| `identifier` | `Sat`, `true`, `On` | case-sensitive on names; `true`/`false`/`On`/`Off` are lexically identifiers (booleanness is a catalogue/linter fact, not a node type) |
| `member_expression` | `Sat.Earth.RMAG`, `FM.GravityField.Earth.PotentialFile` | dotted reference path of any depth (4-deep paths occur in the corpus) |
| `call_expression` | `A(1,1)`, `sqrt(x)`, `cross(r1,v1)` | a postfix `(<args>)`. **Array indexing and function invocation are syntactically identical** — one node; which it is, is semantic (linter/AST), not syntactic |
| `number` | `7000`, `1.25e-1`, `1e+70`, `1e+070` | integer / real / scientific; tolerates the corpus's `e+070` zero-padded exponent |
| `string` | `'01 Jan 2025 12:00:00.000'` | single-quoted; no escapes; cannot contain `'`, newline, or `%` |
| `array_literal` | `[1 2 3]`, `[ true false]`, `[1 0 0; 0 1 0; 0 0 1]` | square brackets; elements separated by whitespace **or** commas; `;` separates **rows** (2-D matrices — e.g. the 6×6 `OrbitErrorCovariance`) |
| `list` | `{Earth}`, `{Sun, Luna}`, `{}`, nested | brace-list; comma-separated; may be empty; nestable; holds strings / refs |
| `binary_expression` | `a + b`, `x^2`, `Sat.TA > 90`, `a & b` | arithmetic `+ - * / ^`; relational `< <= > >= == ~=`; logical `& \|`. Relational/logical appear in `If`/`While` conditions; GMAT forbids parens there, but the grammar stays permissive and lets the linter enforce |
| `unary_expression` | `-Element1`, `+x` | leading sign |
| `parenthesized_expression` | `(a + b)` | grouping |
| `command_label` | `'Raise apogee'` | a single-quoted label that is the statement's first element after the optional `GMAT` keyword — it precedes the command keyword **or** an assignment LHS (e.g. `'Save RAAN' RAAN = MoonSat.RAAN`, no `GMAT`). Pervasive (576 occurrences) |

**Lexical details that the layout / re-emission depends on**

- **Whitespace, newlines, and the `...` line continuation** are preserved as the parser's
  between-token text (tree-sitter "extras" / interstitial text), so re-emission is lossless (D6).
  `...` before a newline continues a statement; it is layout, not a node.
- **Statement terminator `;` is optional** and preserved verbatim where present. Multiple statements
  on one line are not legal GMAT and are not specially modelled.

### What is deliberately one node vs. many

The grammar specializes a node type **only** when it must, to parse correctly:

- **must** distinguish: `create_command` (the `Create` keyword + name list), `assignment_command`
  (`=` with a single LHS), `function_call_command` (`=` with a `[…]` LHS), the begin/end **blocks**
  (matched terminators + nested body), `begin_mission_sequence` (the section boundary), `include`,
  `comment`.
- **need not** distinguish: the individual mission commands (one generic `command` keyed by its
  leading keyword), the individual resource types (one generic `create_command`), array-index vs
  function-call (one `call_expression`), boolean vs plain identifier (one `identifier`). These
  distinctions are recovered by later layers from the catalogue, not from the parse tree.

A **bare no-output call** — an identifier statement with no `[…] =` LHS, e.g. `TargeterInsideFunction;`
or `MyFunc(args);` (a GmatFunction invoked for side effects, or the `CallGmatFunction` /
`CallMatlabFunction` engine command) — is just a generic `command`. Only the bracket-LHS form
`[out, …] = name(args)` that *binds outputs* is a first-class `function_call_command` (D4).

## D4 — surface-coverage freeze

**Covered (must parse, zero `ERROR` nodes, across the whole corpus):**

- All `Create` resource declarations — every family, generically (the 67 corpus types span
  Spacecraft / ForceModel / Propagator / burns / solvers / estimation / coordinate systems /
  subscribers / hardware / parameters / `Variable` / `Array` / `String` / `GmatFunction` …).
- The configuration section: dotted `resource.field = value` assignments, the optional `GMAT`
  keyword, `Array` declaration `A[r,c]` and `A(i,j)` access, brace-lists `{…}`, square-bracket array
  and 2-D matrix literals `[…]`, comments, blank lines, the `...` continuation.
- `#Include 'path'` (top-level directive — present in the corpus; **not** in the charter's original
  in-scope list, added here).
- `BeginMissionSequence` and the mission sequence: the generic command set above; the full RHS
  expression grammar (arithmetic, relational/logical, function calls) — needed because mission-
  sequence assignments and `.gmf` bodies compute, e.g. `Cost = sqrt(TOI.Element1^2 + …)`.
- The `Propagate` argument grammar including `Prop(Sat) {Sat.ElapsedSecs = 8640}` brace option
  blocks, multi-spacecraft `Prop(Sat1, Sat2)`, chained propagators, and the `BackProp` /
  `Synchronized` modifiers.
- Control-flow and solver blocks: `If`/`Else`/`EndIf`, `For`/`EndFor`, `While`/`EndWhile`,
  `Target`/`EndTarget`, `Optimize`/`EndOptimize`, with solver-mode brace options and nested commands.
- `BeginScript`/`EndScript` (opaque body) and `BeginFiniteBurn`/`EndFiniteBurn` (flat command pair).
- Command labels `'…'` on any command (and on a bare assignment with no `GMAT` keyword).
- The function-call command `[out, …] = name(args)` (binds outputs), including dotted names; and the
  **bare no-output call** `Name;` / `Name(args);` (a void GmatFunction invocation — a generic `command`).
- The two corpus files **without** `BeginMissionSequence` (`Ex_CompareEphemeris.script`,
  `Ex_IncludeFile.script`): a configuration-only file is valid — the boundary marker is optional in
  the grammar even though it is mandatory for a runnable mission (a runnability question for
  gmat-run / the linter, not the parser).

**The `CallGmatFunction` / `CallMatlabFunction` correction.** The charter and the #5 draft name
`CallGmatFunction` / `CallMatlabFunction` as command keywords. Those keywords appear **0×** in the
stock corpus. What the corpus actually uses is the **bracket-assignment call form**
(`[out, …] = func(args)`, `[crossProd] = cross(vec1, vec2)`) and dotted external calls
(`[V2,Log] = Python.IODFunctions.ThreePositionIOD(…)`). So the grammar's function-call surface is the
`function_call_command` of D3, not a `Call*Function` keyword. The `Call*Function` keywords, if they
appear in any input, still parse as generic `command` nodes (the generic fallback), so nothing is
lost — but the modelled, first-class form is the bracket-assignment one. (The GMAT help documents
`CallGmatFunction` as the engine's official call command; the sample scripts nonetheless use the
bracket form and the bare no-output call, so those are what is first-classed.)

**Deferred / best-effort (parses via the generic fallback, but not first-classed or corpus-tested):**

- Older-release (pre-R2026a) syntax. R2026a is the target; the grammar is best-effort on older files
  (the full version strategy is D11).
- `ElseIf` — not present in the corpus; if encountered it should still recover, but it is not a
  first-class `if_statement` branch in v0.1.
- `BeginScript`/`EndScript` bodies — opaque by design; the raw text round-trips but is not parsed
  into structure.
- MATLAB / Python callback *internals* beyond the call form — the call command parses; what the
  external function does is out of scope.

## D5 — v0.1 returns the CST only; the typed AST is v0.2

`parse(text)` returns a thin `Tree` wrapper over the tree-sitter concrete syntax tree (CST) — **not**
typed resource/command objects and **not** dict access. The typed-AST overlay
(`ast.spacecraft["Sat"]["SMA"]`), the mutation API, and the formatter are v0.2 (#12 / #13 / #14),
built *on top of* this tree. The v0.1 `Tree` wrapper API is kept minimal and forward-compatible so
the v0.2 overlay wraps it without a breaking change.

The configuration/sequence split (above) is positional, recovered from the tree, not encoded as
distinct node types — so the same `assignment_command` node serves a literal config assignment and a
computed mission-sequence assignment; telling them apart (and applying GMAT's literal-only-in-config
rule) is the linter's job.

## D6 — the identity invariant: byte-for-byte re-emission

"Re-emit byte-for-byte" is defined precisely as: **concatenating every leaf token together with all
interstitial text (whitespace, newlines, comments, the `...` continuation, and the optional `;`) in
source order reproduces the input file exactly, byte for byte.** Comments and layout are preserved
because they live in the tree's between-token text, not discarded. Exposed as `tree.text` /
`to_source(tree)` (#6).

- **No EOL normalisation in the library.** The library reads and writes UTF-8 and preserves the
  source's original line endings exactly; it never converts CRLF↔LF.
- **The corpus normalisation rule is `-text` in `.gitattributes`**, not in code. The golden corpus
  ships with `tests/data/** -text` (plus `*.script -text` / `*.gmf -text`) so Windows CI does not
  rewrite line endings under the byte-exact assertion. (This is why the EOL handling is a VCS
  attribute, not a library feature.)

## D7 — error recovery: nodes, never exceptions

A malformed or incomplete script **never raises** from `parse()`. tree-sitter's error recovery
yields a usable partial tree with `ERROR` and `MISSING` nodes localised to the broken construct — the
property that makes editor-grade feedback on a half-typed buffer possible (and that the LSP, v0.3,
depends on). The library surfaces them:

- `tree.errors` — a list of `ERROR`/`MISSING` nodes with their line/column ranges and a short
  message.
- `tree.has_errors` — a boolean.

The `parse` CLI turns this into an exit code and a diagnostic (D8). "Does it parse" is structural;
"does it run / converge" is a different question gmat-run answers.

## D8 — the `parse` CLI output format

`gmat-script parse FILE`:

- **Default** — prints the tree as an S-expression (tree-sitter's `s-expression` form) to stdout.
  Exit **0** if the tree has no `ERROR`/`MISSING` node, **1** if it does (for CI use).
- **`--json`** — prints a machine-readable report instead of the S-expression:

  ```json
  {
    "file": "flyby.script",
    "ok": false,
    "errors": [
      {
        "type": "ERROR",
        "start": { "line": 12, "column": 5 },
        "end":   { "line": 12, "column": 18 },
        "message": "unexpected token"
      }
    ]
  }
  ```

  `ok` mirrors the exit code (`true` ⇔ exit 0). Positions in the **CLI / JSON are 1-indexed** for
  line and column (compiler convention, human-facing). The internal tree-sitter positions are
  0-indexed; the wrapper converts. (The LSP layer, v0.3, emits LSP's native 0-indexed positions
  separately — the CLI's choice does not bind it.)

A clean script prints its S-expression and exits 0; a malformed one prints the error report (or, by
default, the partial S-expression) and exits 1, with line/column on every error.

## D9 — the GMAT-free guarantee

`gmatpy` and GMAT are **build-time only**, used by exactly one piece of code: the field-catalogue
generator `tools/gen_catalog.py` (v0.3, #19), run in the setup-gmat CI job. The catalogue ships as
JSON package data.

- **v0.1 and v0.2 import neither GMAT nor `gmatpy`** — not at runtime, not in tests, not in the build.
  The only runtime dependency is `tree-sitter` (D2).
- `pip install gmat-script` never pulls in, requires, or looks for a GMAT install.
- The v0.3 catalogue *loader* (`catalog.py`) reads the shipped JSON with **no `gmatpy` import**; only
  the *generator* touches `gmatpy`, and only in CI.

This is the project's defining boundary: running a script needs GMAT (gmat-run's job); reading,
checking, formatting, and transforming its text does not.

## D10 — GmatFunction (`.gmf`) shares the grammar

`.gmf` files parse with the **same grammar**. They are a superset of the script surface, adding only a
`function` header and `Global` declarations. The header — modelled as a `function_definition` node —
is **wider than one form**; confirmed against all **nine** `.gmf` in an R2026a install (one in
`samples/`, eight in `userfunctions/gmat/`) plus real-world `.gmf` on GitHub:

- **Output list is optional, and always bracketed when present** — absent (`function Name(...)`),
  empty (`function [] = Name(...)`), single (`function [q] = Name(...)`), or multiple
  (`function [dr, dv] = Name(...)`). There is **no** bare MATLAB single-output form (`out = name(...)`)
  — even one output is `[out]`.
- **Parameter list is optional** — absent entirely (`function [a,b] = Name`), empty
  (`function Name()`), or `(p1, p2, …)`.
- **Optional trailing `;`** on the header (`function [delta] = SatSep(Sat1, Sat2);`), and whitespace
  may sit before `(` (`function [q] = ComposeQuaternions (qA, qB)`).

So `function_definition` carries an *optional* output list, the name, and an *optional* parameter
list. (The no-parameter-list and empty-`[]` forms come from older / documentation examples and are
best-effort — D11; every R2026a install `.gmf` uses an explicit `(...)`.)

- `Global <name>…` declarations (a generic `command`) share resources with the caller.
- Otherwise the identical `Create` / `BeginMissionSequence` / command / expression surface. The eight
  `userfunctions/gmat/` functions exercise far more than the single `samples/` file — `Target` /
  `EndTarget` and `Optimize` solver blocks, `If` / `EndIf`, `For`, `Vary` / `Achieve` / `Maneuver`,
  and `Global` — all already covered by D3.

A **void function** (no output list) is *called* as a bare no-output `command` statement
(`TargeterInsideFunction;`), tying D10 to D4's bare-call form. The grammar applies to both `.script`
and `.gmf`; the file extension selects nothing in the parser. The function-header oracle is the
**nine** install `.gmf` (not the single `samples/` one), so the corpus harness (#8) should include the
`userfunctions/gmat/` set.

## D11 — GMAT version handling: one version-agnostic grammar, version-pinned catalogues, additive

The version question splits cleanly along the grammar / catalogue boundary (D3 / D9), and the two
halves are handled oppositely.

- **The grammar is version-agnostic by construction, and there is exactly one.** The generic
  `create_command` (any `<Type>`) and generic `command` (any keyword) of D3 mean a resource type or
  command keyword added or removed in *any* GMAT release parses without a grammar change — the grammar
  never enumerates the vocabulary, so it does not date. GMAT's *syntax* (`Create`, assignments,
  `BeginMissionSequence`, control flow, the value / expression grammar) has been stable across
  releases; the grammar targets R2026a but parses older and newer scripts because it is a permissive
  superset. If a genuine *syntactic* divergence between versions ever appears (rare), it is added to
  the single grammar as an accepted alternative — **never forked into a per-version grammar.** One
  grammar covers all versions.
- **Semantics — the field catalogue — are version-pinned, and that is the *only* version-coupled
  artifact.** Valid field names, types, enums, defaults, and reference targets change every release,
  so the catalogue (D9, #19) is generated per GMAT install and stamped with its GMAT version +
  generation date in the JSON header. v0.3 ships exactly `fields-R2026a.json`.

**How the library indicates "R2026a" today.** The version it speaks for is not in the grammar (which
carries none) but in the **catalogue's provenance header** — the machine-readable declaration — and
restated in the README. The linter / hover / completion are therefore "R2026a semantics," validated
against the shipped R2026a catalogue. A script from another release still *parses* (the grammar is
agnostic) but may draw false unknown-field / enum diagnostics from the linter — so static **parsing**
is effectively version-independent while static **linting** is explicitly R2026a-scoped.

**Adding versions later is additive data, not a fork — same project, same repo.** Because the only
version-coupled artifact is catalogue data, supporting another release means: (1) generate
`fields-<ver>.json` from that install with the existing `gen_catalog.py` (the setup-gmat CI matrix
already spans multiple releases — and note only R2022a / R2025a / R2026a are real in that window;
GMAT shipped no R2023a / R2024a); (2) give the catalogue loader and linter / LSP a **`target_version`
selector**, defaulting to the newest shipped catalogue. To keep that future cheap, the v0.3 catalogue
API and the linter are designed with the selector **from the start**, even while only one catalogue
ships — so the later change is a data file plus a default, not a refactor. A separate per-version repo
is explicitly rejected: it would duplicate the grammar, linter, and LSP only to vary a JSON file. The
grammar's acceptance corpus may later gain per-version sample suites as best-effort parse oracles, but
the formal v0.1 bar stays the R2026a stock corpus.

**Scope now (unchanged from the charter).** v0.x targets R2026a; older releases are best-effort for
parsing and unsupported for linting. This decision adds version support to no v0.x milestone; it fixes
the *shape* of support so the v0.3 catalogue / linter design does not foreclose it.

## D12 — the grammar → wheel build mechanic (resolving the D1 / D2 deferral)

D1 fixed *that* the compiled grammar is vendored into one wheel; D2 fixed the *guarantee*
(toolchain-free install) and deferred the exact mechanic to the scaffold (#3). This records the
resolution — the contract the parser binding (#6) loads against.

- **The generated parser is committed.** `tree-sitter-gmat/src/parser.c` (with `grammar.json`,
  `node-types.json`, and `tree_sitter/*.h`) is checked in. Regenerating it needs Node + the
  tree-sitter CLI; *compiling* it needs only a C compiler. So routine wheel builds — and the sdist
  fallback — never touch Node.
- **One vendored extension, compiled at wheel-build time.** A Hatchling build hook
  (`hatch_build.py`) compiles `parser.c` + the Python binding (`bindings/python/binding.c`) into a
  single extension module vendored at `gmat_script/_grammar/_binding`. This resolves D1's
  "one bundled extension vs. embedded `tree_sitter_gmat` module" question as the **single bundled
  extension** form: the library loads it via `gmat_script._grammar.language()`, which the
  `tree-sitter` runtime wraps with `Language(...)`. `parser.py` is wired to this load path at #6;
  the scaffold proves it end to end.
- **Stable ABI (`abi3`, floor cp310).** The extension builds against the CPython limited API, so
  one wheel per platform runs on every supported Python (3.10 / 3.11 / 3.12). Wheels carry the
  `cp310-abi3-<platform>` tag.
- **`cibuildwheel` produces the per-platform wheels + an sdist.** Release builds run cibuildwheel
  (one cp310 build per platform → manylinux / macOS / Windows abi3 wheels) plus the sdist, which
  carries `parser.c` so an sdist build needs a C compiler but **no Node**. PyPI ships the prebuilt
  wheels — the D9 toolchain-free install — and the sdist is the compile-locally fallback for
  platforms without a prebuilt wheel.

The drift risk this introduces — a hand-edited `grammar.js` whose committed `parser.c` goes stale,
or a generated ABI the pinned runtime cannot load — is caught by the grammar-build CI job (D2),
which regenerates with the pinned CLI and runs the corpus tests, so it fails CI rather than a user's
`import`.

---

## Forward notes (not v0.1 decisions)

- **Catalogue & version bump (v0.3, #19).** The field catalogue is pinned to R2026a with a documented
  regeneration process (the multi-version strategy is D11); the gmatpy-reflection generator is the
  only GMAT-touching code, run via setup-gmat in CI. The corpus survey (67 resource types) is a useful
  cross-check on catalogue coverage but is not the catalogue source.
- **Formatter ordering (v0.2, #14).** The canonical formatter's section grouping and field ordering
  are decided at v0.2; the only v0.1 commitment is that the *unformatted* round-trip is byte-exact
  (D6), so the formatter has a faithful tree to reorder.
- **typed-AST shape (v0.2, #12).** The typed overlay's exact class surface is a v0.2 decision; D3 only
  guarantees the CST it wraps and that the `Tree` wrapper is forward-compatible.

## Charter / issue deltas recorded here

The corpus survey turned up constructs the charter's prose and the v0.1 issue drafts under-specify.
Recorded so #4 / #5 implement the real surface:

- **`#Include`** is a real top-level directive (2 corpus files) — added to scope (D3 `include`, D4).
- The **RHS is a full expression grammar** (arithmetic, function calls, relational/logical), not just
  "numbers, strings, refs, brace-lists" — mission-sequence assignments and `.gmf` bodies compute
  (D3, D4).
- **`[…]` square-bracket array *and* 2-D matrix literals** (with `;` row separators) exist alongside
  brace-lists `{…}` — the charter named only `{…}` (D3 `array_literal`).
- **Command labels `'…'`** are pervasive on every command, not just the `GMAT`-prefixed assignment
  (D3 `command_label`).
- **Line continuation `...`** (72 occurrences, 21 files) must be handled lexically (D3, D6).
- The **function-call command is the bracket form `[a,b]=f(x)`**, not the `Call*Function` keywords,
  which never appear in the corpus (D4).
- The Python binding dependency is the single PyPI package **`tree-sitter`**, not
  "`tree-sitter` + `py-tree-sitter`" (D2; forward note for #3's `pyproject.toml`).
- The **`function` header is wider than `[outs] = Name(ins)`** — the output list and the parameter
  list are each optional (void functions, empty `[]`, no-parens), with an optional trailing `;`
  (D10). The function-header oracle is **nine** `.gmf` in the install, not one.

---

## Appendix — corpus survey

Surveyed against an **R2026a install** (the stock `samples/` directory plus the install's
`userfunctions/gmat/`); the `samples/` set is byte/line-identical across the Linux and Windows
installs (0 content diffs; 71 / 162 files differ only by CRLF — the install carries mixed line
endings, which is why D6 forbids EOL normalisation and ships `-text`). Counts below were re-derived
on the corpus by folding `...` continuations and stripping leading `GMAT` keywords and command labels
before tokenising — this **supersedes** an earlier word-boundary `grep` that over-counted `Set` /
`Write` / `Global` and miscategorised the `BackProp` modifier.

Stock corpus: **162 `.script` + 1 `.gmf`** in `samples/`; the install has **9 `.gmf`** total
(+8 in `userfunctions/gmat/`).

- **`Create` types:** **67 distinct.** Most frequent: Spacecraft (293), OpenFramesView (267),
  Propagator (195), ForceModel (188), OpenFramesInterface (158), CoordinateSystem (157), Variable
  (154), ImpulsiveBurn (116), GroundStation (67), XYPlot (66), ReportFile (62) … down to single-use
  types (Smoother, ExtendedKalmanFilter, EclipseLocator, …). The long tail is exactly why `Create` is
  generic.
- **`BeginMissionSequence`:** present in 160 / 162 files; absent in `Ex_CompareEphemeris.script` and
  `Ex_IncludeFile.script` (configuration-only / include-driven).
- **Command keywords (leading-token occurrences, authoritative):** Propagate 401, Vary 270, Report
  242, NonlinearConstraint 128, Maneuver 97, Achieve 81, If/EndIf 69, Target/EndTarget 52, Toggle 44,
  BeginScript/EndScript 28 each (19 files), PenUp/PenDown 28 each, RunSimulator 23, RunEstimator 22,
  For/EndFor 20, BeginFiniteBurn 19 / EndFiniteBurn 18, Optimize/EndOptimize 19, Else 17, Write 17,
  Minimize 16, While/EndWhile 9, BeginFileThrust/EndFileThrust 5, UpdateDynamicData 3, Global 3,
  CommandEcho 2, Set 1, RunSmoother 1, Stop 1. **Modifier (not a command):** `BackProp` 51
  occurrences inside `Propagate`. **Absent (0):** `CallGmatFunction` / `CallMatlabFunction` /
  `CallPythonFunction` / `ElseIf` / `SkipMissionSequence`.
- **Function calls:** 24 bracket-LHS calls `[out, …] = name(args)` (incl. dotted `Python.…`);
  2 bare no-output calls (`TargeterInsideFunction;`).
- **`#Include`:** 2 files (`#Include '…';` and `#Include '…'` — trailing `;` optional).
- **Line continuation `...`:** 72 occurrences across 21 files.
- **Command labels `'…'`:** 576 occurrences — on Propagate / Target / Optimize / If / While / Vary /
  Achieve, the `GMAT 'label' x = …` assignment, and label-first assignments (`'Save RAAN' RAAN = …`).
- **`[…]` literals:** 1-D (`[ 0.1 0.05 ]`, `[ true false]`) and 43 two-dimensional matrices with `;`
  row separators (the 6×6 `OrbitErrorCovariance`); exponents include the zero-padded `1e+070` form.
- **Braces / indexing:** 124 empty `{}`, 112 nested braces, 70 LHS array-index targets `A(i,j) = …`;
  dotted member paths up to 4 deep (`FM.GravityField.Earth.PotentialFile`, 250 occurrences).
- **`.gmf` headers (9 files):** `[dr, dv] = Ex_RICdelta(rv1, rv2)`, `[crossProd] = cross(...)`,
  `[q] = ComposeQuaternions (qA, qB)` (space before `(`), `TargeterInsideFunction()` and
  `TargetLEOStationKeeping(a, b)` (no output list); plus, from real-world GitHub `.gmf`,
  `[outs] = GetCDStates` (no parameter list), `[] = RaiseApogee(burnSize)` (empty output list), and
  `… = SatSep(Sat1, Sat2);` (trailing `;`).
