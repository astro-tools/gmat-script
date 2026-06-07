# Grammar surface

This page describes what the parser understands: the structure of a GMAT script, the concrete
syntax tree (CST) node taxonomy, and the constructs that are covered versus deferred. For the
reasoning behind these choices, see the [design decisions](design/decisions.md).

## The language model

A GMAT script has two sections, in strict order:

1. **Configuration** — `Create` resource declarations and literal `resource.field = value`
   assignments.
2. **Mission sequence** — everything after the `BeginMissionSequence` marker: an ordered list of
   commands and control-flow / solver blocks.

The split is **positional, not lexical**: the same assignment syntax appears in both sections, and
which section a statement belongs to is determined by its position relative to
`BeginMissionSequence`, not by a different node type. GMAT enforces extra rules per section (for
example, configuration assignments must be literal, and `Create` is illegal after
`BeginMissionSequence`); those are semantic rules a later linter owns, not the grammar. The grammar
is deliberately permissive — it accepts the superset and leaves what GMAT would reject to later
layers.

GmatFunction (`.gmf`) files parse with the **same grammar**. They are a superset of the script
surface, adding only a `function` header and `Global` declarations.

## Generic over enumerated

The grammar never enumerates resource types or command keywords. The R2026a corpus alone has 67
distinct `Create` types and roughly 37 command keywords, and GMAT plugins add more — so:

- `Create <Type> <name> …` parses with `<Type>` as **any identifier**. There is one generic
  `create_command`, not a rule per resource family.
- An unrecognised command keyword parses as a **generic `command` node**, not an error.

Only the constructs the grammar must understand *structurally* — assignments, the bracket-output
call form, the matched begin/end blocks, the section boundary, includes, and comments — get their own
node type. Everything else is recovered by later layers from a field catalogue, not from the parse
tree. A resource type or command keyword added or removed in any GMAT release therefore parses with
no grammar change.

## Node taxonomy

The named node types the parser produces, grouped by role.

### Top level and structural

| Node | Surface | Notes |
|------|---------|-------|
| `source_file` | the whole file | the root node |
| `comment` | `% …` to end of line | attaches anywhere, including mid-construct; no block comments; a `%` inside a string is data, not a comment |
| `include` | `#Include 'path'` | preprocessor directive; top level only; trailing `;` optional |
| `create_command` | `Create <type> <name> [<name> …]` | `<type>` is any identifier; one or more names (`Create Variable x y z`); an `Array` declaration carries its `[r,c]` size as an `array_size` |
| `begin_mission_sequence` | `BeginMissionSequence` | the configuration ↔ mission-sequence boundary |

### Commands

| Node | Surface | Notes |
|------|---------|-------|
| `assignment_command` | `[GMAT] [label] <lhs> = <rhs>` | optional leading `GMAT` keyword; optional `'label'`; `<lhs>` is a reference or array-indexed target; `<rhs>` is the full expression grammar. The same node serves a literal configuration assignment and a computed mission-sequence assignment |
| `function_call_command` | `[<out>, …] = <name>(<args>)` | the bracket-list LHS (an `output_list`) distinguishes it from an assignment; `<name>` may be dotted; `<args>` is an `argument_list`. This is the modelled function-call form |
| `command` | `<keyword> [label] <args …>` | the generic command — `Propagate`, `Maneuver`, `Report`, `Vary`, `Achieve`, `Minimize`, `Toggle`, `Save`, `Stop`, `Global`, `BeginFiniteBurn` / `EndFiniteBurn`, and any unrecognised keyword. A bare no-output call (`MyFunc(args);`) is a `command` too |

### Blocks

Matched begin/end constructs with a nested command body.

| Node | Surface | Notes |
|------|---------|-------|
| `if_statement` | `If <cond> … [Else …] EndIf` | an `Else` branch is an `else_clause` |
| `for_statement` | `For <var> = <range> … EndFor` | the `start:step:stop` or `start:stop` range is a `for_range` |
| `while_statement` | `While <cond> … EndWhile` | |
| `target_statement` | `Target <solver> [{opts}] … EndTarget` | nests `Vary` / `Achieve` / etc. as ordinary `command`s; brace options are `option_assignment`s |
| `optimize_statement` | `Optimize <solver> [{opts}] … EndOptimize` | nests `Vary` / `Minimize` / `NonlinearConstraint` |
| `script_block` | `BeginScript … EndScript` | **opaque**: the body is a single raw-text `script_body` token, not re-parsed |

!!! note "`BeginFiniteBurn` / `EndFiniteBurn` are not blocks"
    The commands they bracket are flat siblings, not a nested body, so each parses as an ordinary
    `command`. The same goes for `BeginFileThrust` / `EndFileThrust`. Pairing them, if ever needed,
    is a job for a layer above the grammar.

### Values and expressions

The right-hand-side grammar.

| Node | Surface | Notes |
|------|---------|-------|
| `identifier` | `Sat`, `true`, `On` | case-sensitive; `true` / `false` / `On` / `Off` are lexically identifiers (their booleanness is a catalogue fact, not a node type) |
| `member_expression` | `Sat.Earth.RMAG`, `FM.GravityField.Earth.PotentialFile` | a dotted reference path of any depth |
| `call_expression` | `A(1,1)`, `sqrt(x)`, `cross(r1, v1)` | a postfix `(<args>)`. Array indexing and function invocation are syntactically identical — one node; which it is, is semantic |
| `number` | `7000`, `1.25e-1`, `1e+070` | integer / real / scientific; tolerates a zero-padded exponent |
| `string` | `'01 Jan 2025 12:00:00.000'` | single-quoted; no escapes; cannot contain `'`, a newline, or `%` |
| `array_literal` | `[1 2 3]`, `[1 0 0; 0 1 0; 0 0 1]` | square brackets; elements separated by whitespace or commas; `;` separates rows of a 2-D matrix |
| `list` | `{Earth}`, `{Sun, Luna}`, `{}` | brace-list; comma-separated; may be empty; nestable |
| `binary_expression` | `a + b`, `x^2`, `Sat.TA > 90`, `a & b` | arithmetic `+ - * / ^`; relational `< <= > >= == ~=`; logical `& \|` |
| `unary_expression` | `-Element1`, `+x` | a leading sign |
| `parenthesized_expression` | `(a + b)` | grouping |
| `unquoted_value` | `VectorType = Relative Position`, `Epoch = 19 Aug 2015 00:00:00.000` | the raw rest of a logical line, used when the value is not one of the structured forms above — multi-word enums, unquoted paths and dates |
| `command_label` | `'Raise apogee'` | a single-quoted label that is a statement's first element (before the command keyword or assignment LHS) |

### GmatFunction header

| Node | Surface | Notes |
|------|---------|-------|
| `function_definition` | `function [<out>, …] = <name>(<params>)` | the `.gmf` header. The output list (an `output_list`) and the parameter list (a `parameter_list`) are each optional; the trailing `;` is optional. `Global <name> …` declarations parse as generic `command`s |

## Layout and re-emission

Whitespace, newlines, comments, and the `...` line continuation are preserved as the parser's
between-token text, so re-emission is lossless: concatenating every leaf token together with the
interstitial layout reproduces the input **byte-for-byte**. `...` before a newline continues a
statement — it is layout, not a node. The statement terminator `;` is optional and preserved
verbatim where present.

The library performs **no end-of-line normalisation** — it reads and writes the source's original
line endings exactly, never converting CRLF↔LF.

## Covered

These parse with zero `ERROR` nodes across the whole R2026a stock corpus:

- Every `Create` resource declaration, generically — every resource family.
- The configuration section: dotted `resource.field = value` assignments, the optional `GMAT`
  keyword, `Array` declarations `A[r,c]` and access `A(i,j)`, brace-lists, square-bracket array and
  2-D matrix literals, multi-word unquoted values, comments, blank lines, the `...` continuation.
- `#Include 'path'`.
- `BeginMissionSequence` and the mission sequence: the generic command set and the full expression
  grammar (arithmetic, relational / logical, function calls).
- The `Propagate` argument grammar, including `Prop(Sat) {Sat.ElapsedSecs = 8640}` brace option
  blocks, multi-spacecraft propagation, chained propagators, and the `BackProp` / `Synchronized`
  modifiers.
- Control-flow and solver blocks: `If` / `Else` / `EndIf`, `For` / `EndFor`, `While` / `EndWhile`,
  `Target` / `EndTarget`, `Optimize` / `EndOptimize`, with solver-mode brace options and nested
  commands.
- `BeginScript` / `EndScript` (opaque body) and `BeginFiniteBurn` / `EndFiniteBurn` (a flat command
  pair).
- Command labels on any command.
- The bracket-output function-call command `[out, …] = name(args)` (including dotted names) and the
  bare no-output call `Name(args);`.
- GmatFunction (`.gmf`) files — the `function` header in all its forms, `Global` declarations, and
  the otherwise identical surface.
- A configuration-only file with no `BeginMissionSequence` (the boundary marker is optional in the
  grammar even though a runnable mission needs it).

## Deferred and best-effort

These parse through the generic fallback — the file still round-trips — but they are not first-classed
or corpus-tested:

- **Older-release syntax.** R2026a is the target; older files are best-effort.
- **`ElseIf`.** It recovers if encountered, but is not a first-class `if_statement` branch.
- **`BeginScript` / `EndScript` bodies.** Opaque by design — the raw text round-trips but is not
  parsed into structure.
- **MATLAB / Python callback internals.** The call command parses; what the external function does
  is out of scope.

## What it does not do

The grammar answers "is this well-formed GMAT script text". It does **not** check whether a field
name, resource type, or enum value is valid — those are semantics that vary by GMAT release and
belong to a later linter. And it never runs anything: "does it parse" is structural; "does it run /
converge" is GMAT's question. See [What it is not](index.md#what-it-is-not).
