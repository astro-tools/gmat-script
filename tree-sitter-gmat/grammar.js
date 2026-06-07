/**
 * @file Tree-sitter grammar for GMAT mission scripts.
 *
 * Implements the full v0.1 surface per the frozen CST node taxonomy in docs/design/decisions.md
 * (D3 / D4 / D10): the lexical core, the configuration section (`Create` declarations and
 * `resource.field = value` assignments), the shared value / expression grammar, and the mission
 * sequence — the `BeginMissionSequence` boundary, the generic command set with its argument grammar,
 * the bracket-LHS `function_call_command`, the control-flow (`If` / `For` / `While`) and solver
 * (`Target` / `Optimize`) blocks, the opaque `BeginScript` block, and the GmatFunction (`.gmf`)
 * `function` header. The grammar is a deliberately permissive superset: it accepts what the parser
 * must understand structurally and defers semantic rules (literal-only-in-configuration, valid
 * keywords, no-parens-in-conditions, …) to the linter.
 *
 * Statement boundaries. A GMAT statement is one logical line: it ends at a newline (or `;`), and the
 * `...` continuation folds the next line into it. Because the configuration section's variadic
 * `Create` name lists and the mission sequence's variadic command arguments both consume bare
 * identifiers, a newline cannot be plain layout — two adjacent `;`-less commands would otherwise
 * merge. So statements are delimited by a hidden external `_terminator` token (`;` / newline(s) /
 * EOF) scanned in src/scanner.c; it is suppressed inside brackets, where the grammar does not expect
 * it (so newlines there stay layout) and after a `...` continuation. The terminator is hidden, so it
 * does not appear in the tree and re-emission stays byte-exact (D6).
 *
 * @license MIT
 */

/// <reference types="tree-sitter-cli/dsl" />
// @ts-check

// Expression precedence, loosest to tightest. Relational / logical operators appear only in `If` /
// `While` conditions; arithmetic sits above them, member / call access tightest.
const PREC = {
  OR: 1, // |
  AND: 2, // &
  COMPARE: 3, // < <= > >= == ~=
  ADD: 4, // + -
  MUL: 5, // * /
  POW: 6, // ^   (right associative)
  UNARY: 7, // leading + -
  CALL: 8, // f(...) / A(i, j)
  MEMBER: 9, // a.b
};

module.exports = grammar({
  name: "gmat",

  // Whitespace, newlines, and the `...` line continuation are layout, preserved as the parser's
  // between-token text so re-emission stays lossless (D6). A `% …` comment attaches anywhere as an
  // `extra`. The `...` continuation is layout, not a node, so it is an anonymous token here. A
  // newline is layout *here* but is also offered to the external scanner first (see `externals`),
  // which claims it as a `_terminator` at statement boundaries.
  extras: ($) => [/\s/, $.comment, token(prec(1, seq("...", /[^\S\n]*/, /\r?\n/)))],

  // Externally scanned tokens (see src/scanner.c):
  //   - `unquoted_value` — GMAT's raw rest-of-line config values (multi-word enums, unquoted paths /
  //     dates, the doubled-quote artifact) that the structured value grammar cannot represent (D13).
  //   - `script_body` — the opaque raw text inside a `BeginScript` … `EndScript` block (D4).
  //   - `_terminator` — the statement boundary (`;` / newline(s) / EOF); hidden, so it never appears
  //     in the tree. The scanner only emits it where the grammar marks it valid, so newlines inside
  //     `(…)` / `{…}` / `[…]` stay layout.
  externals: ($) => [$.unquoted_value, $.script_body, $._terminator],

  // The lexer treats `identifier` as the "word" token, so keywords (`Create`, `If`, `Target`, …) are
  // extracted as whole-word keywords and an object legitimately *named* like one still lexes as an
  // identifier outside the keyword position.
  word: ($) => $.identifier,

  rules: {
    // The file: a run of statements (configuration *and* mission sequence — the split is positional,
    // recovered from the tree, not a different node type; D5). Comments and blank lines attach as
    // extras.
    source_file: ($) => repeat($._statement),

    // Every statement is one logical line, closed by the hidden `_terminator`.
    _statement: ($) =>
      seq(
        choice(
          $.include,
          $.create_command,
          $.assignment_command,
          $.function_call_command,
          $.command,
          $.begin_mission_sequence,
          $.if_statement,
          $.for_statement,
          $.while_statement,
          $.target_statement,
          $.optimize_statement,
          $.script_block,
          $.function_definition,
        ),
        $._terminator,
      ),

    // ---- structural ---------------------------------------------------------------------------

    // `#Include 'path'` preprocessor directive; top-level only. The trailing `;` (both forms occur in
    // the corpus) is consumed by the statement terminator.
    include: ($) => seq("#Include", field("path", $.string)),

    // `Create <Type> <name> [<name> …]`. `<Type>` is parsed generically (any identifier) so new or
    // plugin resource types parse without a grammar change; type validity is the linter's job. Each
    // declared name may carry an `Array` size suffix `[r, c]` (only `Array` uses it — generic here).
    create_command: ($) =>
      seq(
        "Create",
        field("type", $.identifier),
        repeat1(seq(field("name", $.identifier), optional($.array_size), optional(","))),
      ),

    // The `Array` size suffix, following the name it sizes: `A[3, 3]`. Generic (any name may carry
    // it) — pairing it to `Array` resources is the linter's job.
    array_size: ($) => seq("[", commaSep1($.number), "]"),

    // `BeginMissionSequence` — the configuration ↔ sequence boundary, a marker command.
    begin_mission_sequence: (_) => "BeginMissionSequence",

    // ---- assignment / function call -----------------------------------------------------------

    // `[GMAT] [label] <lhs> = <rhs>`. The optional leading `GMAT` keyword and the optional
    // single-quoted command label are both modelled per D3; the same node serves a literal
    // configuration assignment and a computed mission-sequence assignment (the split is positional).
    assignment_command: ($) =>
      seq(
        optional("GMAT"),
        optional(field("label", $.command_label)),
        field("left", $._lhs),
        "=",
        field("right", $._value),
      ),

    // `[<out>, …] = <name>(<args>)` — a function-call command that binds outputs. The bracket-list
    // LHS distinguishes it from an assignment; `<name>` may be dotted
    // (`Python.IODFunctions.ThreePositionIOD`) and the parenthesised argument list is optional
    // (`[now] = Python.time.time`, `[s] = path`). The bare no-output call form (`MyFunc(args);`) is a
    // generic `command`, not this node (D4).
    function_call_command: ($) =>
      seq(field("outputs", $.output_list), "=", field("function", $._reference)),

    output_list: ($) => seq("[", optional(commaSep1($.identifier)), "]"),

    // An object / field path, or an array-indexed target like `A(1, 1)`.
    _lhs: ($) => $._reference,

    // The right-hand side: a structured literal / expression, or — when no structured form fits —
    // GMAT's raw rest-of-line `unquoted_value` (multi-word enums, unquoted paths / dates, the
    // doubled-quote artifact). The external scanner emits `unquoted_value` only for the raw case, so
    // the two alternatives never overlap (D13).
    _value: ($) => choice($._expression, $.unquoted_value),

    // ---- generic command ----------------------------------------------------------------------

    // The generic mission command: `<head> [label] <args…>`. `<head>` is a reference — a keyword
    // identifier (`Propagate`, `Maneuver`, `Vary`, `Toggle`, `Save`, `Stop`, `BeginFiniteBurn`, …,
    // and any unrecognised keyword) or a bare-call reference (`Obj.SetModelParameter(args)`,
    // `TargeterInsideFunction`). Arguments use the value grammar plus the `Prop(Sat) {…}` /
    // `DC(TOI.Element1 = 0.5, {…})` forms. `BeginFiniteBurn` / `EndFiniteBurn` and `BeginFileThrust`
    // / `EndFileThrust` are *not* blocks — they parse as ordinary `command` pairs (D3).
    command: ($) =>
      prec.right(
        seq(
          // The label sits after a command keyword (`Propagate 'label' …`) or before a bare-call
          // head (`'label' TargeterInsideFunction;`) — at most one, either side (D3).
          choice(
            seq(field("label", $.command_label), field("name", $._reference)),
            seq(field("name", $._reference), optional(field("label", $.command_label))),
          ),
          repeat($._command_argument),
        ),
      ),

    _command_argument: ($) =>
      choice($._reference, $.string, $.number, $.unary_expression, $.list),

    // ---- control-flow / solver blocks ---------------------------------------------------------

    // `If <cond> … [Else …] EndIf`. `ElseIf` is not in the corpus — deferred / best-effort (D4).
    if_statement: ($) =>
      seq(
        "If",
        optional(field("label", $.command_label)),
        field("condition", $._expression),
        $._terminator,
        repeat($._statement),
        optional($.else_clause),
        "EndIf",
      ),

    else_clause: ($) => seq("Else", $._terminator, repeat($._statement)),

    // `For <var> = <start>:[<step>:]<stop> … EndFor`.
    for_statement: ($) =>
      seq(
        "For",
        optional(field("label", $.command_label)),
        field("variable", $._reference),
        "=",
        field("range", $.for_range),
        $._terminator,
        repeat($._statement),
        "EndFor",
      ),

    for_range: ($) =>
      seq(
        field("from", $._expression),
        ":",
        field("to", $._expression),
        optional(seq(":", field("by", $._expression))),
      ),

    // `While <cond> … EndWhile`.
    while_statement: ($) =>
      seq(
        "While",
        optional(field("label", $.command_label)),
        field("condition", $._expression),
        $._terminator,
        repeat($._statement),
        "EndWhile",
      ),

    // `Target <solver> [{opts}] … EndTarget` — nests `Vary` / `Achieve` / etc. as ordinary commands.
    target_statement: ($) =>
      seq(
        "Target",
        optional(field("label", $.command_label)),
        field("solver", $._reference),
        optional(field("options", $.list)),
        $._terminator,
        repeat($._statement),
        "EndTarget",
      ),

    // `Optimize <solver> [{opts}] … EndOptimize` — nests `Vary` / `Minimize` / `NonlinearConstraint`.
    optimize_statement: ($) =>
      seq(
        "Optimize",
        optional(field("label", $.command_label)),
        field("solver", $._reference),
        optional(field("options", $.list)),
        $._terminator,
        repeat($._statement),
        "EndOptimize",
      ),

    // `BeginScript … EndScript` — opaque: the body is a single raw-text token (`script_body`,
    // externally scanned), not re-parsed (D4).
    script_block: ($) =>
      seq(
        "BeginScript",
        optional(field("label", $.command_label)),
        optional($.script_body),
        "EndScript",
      ),

    // ---- GmatFunction header (.gmf) -----------------------------------------------------------

    // `function [[<out>, …] =] <name> [(<param>, …)]` — the `.gmf` header (D10). The output list and
    // the parameter list are each optional and bracketed / parenthesised when present (void
    // functions, empty `[]`, no-parens forms all occur).
    function_definition: ($) =>
      seq(
        "function",
        optional(seq("[", optional(commaSep1($.identifier)), "]", "=")),
        field("name", $.identifier),
        optional($.parameter_list),
      ),

    parameter_list: ($) => seq("(", optional(commaSep1($.identifier)), ")"),

    // ---- expressions / values -----------------------------------------------------------------

    _expression: ($) => choice($._primary, $.unary_expression, $.binary_expression),

    _primary: ($) =>
      choice(
        $.number,
        $.string,
        $._reference,
        $.list,
        $.array_literal,
        $.parenthesized_expression,
      ),

    // A reference is what can be dotted or indexed: a bare name or a member / call chain rooted in
    // one. GMAT dots and indexes references, never literals or parenthesised expressions, so member
    // and call build over `_reference`, not the full expression grammar.
    _reference: ($) => choice($.identifier, $.member_expression, $.call_expression),

    // Dotted reference path of any depth, e.g. `FM.GravityField.Earth.PotentialFile`. A field name
    // may begin with a digit (`Earth.3DModelFile`), unlike a resource name, so the property is its
    // own token aliased to `identifier`.
    member_expression: ($) =>
      prec(
        PREC.MEMBER,
        seq(field("object", $._reference), ".", field("property", $._field_name)),
      ),

    _field_name: ($) => alias($._field_token, $.identifier),
    _field_token: (_) => token(/[A-Za-z0-9_]*[A-Za-z_][A-Za-z0-9_]*/),

    // A postfix `(<args>)`: array indexing `A(1, 1)` and function invocation `sqrt(x)` are the same
    // syntax — one node; which it is, is semantic, not syntactic.
    call_expression: ($) =>
      prec(
        PREC.CALL,
        seq(field("function", $._reference), field("arguments", $.argument_list)),
      ),

    // Call / index arguments. Beyond plain expressions, the solver-command call form carries keyword
    // arguments (`DC(TOI.Element1 = 0.5, …)`) — modelled as `option_assignment`, the same node the
    // `{…}` option blocks use.
    argument_list: ($) => seq("(", optional(commaSep1($._argument)), ")"),

    // A call argument may also be a raw `unquoted_value` — the EMTG `SetModelParameter` calls pass
    // unquoted file paths (`SetModelParameter(Opt, ../data/x.emtg_launchvehicleopt)`). The external
    // scanner emits it only for the raw case and stops at `,` / `)`, so structured args are
    // unaffected (D13).
    _argument: ($) => choice($._expression, $.option_assignment, $.unquoted_value),

    // `<ref> = <value>` inside a `{…}` option block or a solver-command call. Distinct from the
    // top-level `assignment_command` (no `GMAT` keyword, no label, no terminator).
    option_assignment: ($) =>
      seq(field("left", $._reference), "=", field("right", $._expression)),

    parenthesized_expression: ($) => seq("(", $._expression, ")"),

    // A leading sign. Unary binds tighter than any binary operator, so its operand is a primary (or
    // a nested unary), never a bare binary expression — which also keeps signed elements inside
    // `[ … ]` matrix literals unambiguous (`[ -90000 -90000 20000 ]` is three elements).
    unary_expression: ($) =>
      prec(
        PREC.UNARY,
        seq(field("operator", choice("-", "+")), field("operand", $._unary_operand)),
      ),

    _unary_operand: ($) =>
      choice($.number, $._reference, $.parenthesized_expression, $.unary_expression),

    // Arithmetic `+ - * / ^`; relational `< <= > >= == ~=`; logical `& |`. Relational / logical
    // appear in `If` / `While` conditions; GMAT forbids parens there, but the grammar stays
    // permissive and lets the linter enforce.
    binary_expression: ($) => {
      const factor = [
        ["|", PREC.OR],
        ["&", PREC.AND],
        ["==", PREC.COMPARE],
        ["~=", PREC.COMPARE],
        ["<", PREC.COMPARE],
        ["<=", PREC.COMPARE],
        [">", PREC.COMPARE],
        [">=", PREC.COMPARE],
        ["+", PREC.ADD],
        ["-", PREC.ADD],
        ["*", PREC.MUL],
        ["/", PREC.MUL],
      ];
      return choice(
        ...factor.map(([operator, precedence]) =>
          prec.left(
            precedence,
            seq(
              field("left", $._expression),
              field("operator", operator),
              field("right", $._expression),
            ),
          ),
        ),
        prec.right(
          PREC.POW,
          seq(
            field("left", $._expression),
            field("operator", "^"),
            field("right", $._expression),
          ),
        ),
      );
    },

    // Brace-list: empty, nestable; holds values, nested lists, and the `field = value` option
    // entries of command / solver option blocks (`{Sat.ElapsedSecs = 8640, OrbitColor = Red}`).
    // Elements are separated by commas or whitespace, and GMAT tolerates empty slots (`{a, , b}`),
    // so commas are free-standing.
    list: ($) => seq("{", repeat(choice($.option_assignment, $._expression, ",")), "}"),

    // Square-bracket array / matrix literal: 1-D (whitespace- or comma-separated) and 2-D (with `;`
    // row separators — e.g. the 6×6 `OrbitErrorCovariance`). Elements are literals: numbers
    // (optionally signed), identifiers (`true` / `false`), or strings — never arithmetic.
    array_literal: ($) => seq("[", optional($._matrix_rows), "]"),

    _matrix_rows: ($) => seq($._matrix_row, repeat(seq(";", $._matrix_row))),

    _matrix_row: ($) =>
      seq($._array_element, repeat(seq(optional(","), $._array_element))),

    _array_element: ($) =>
      choice($.number, $.string, $.identifier, $.unary_expression),

    // ---- terminals ----------------------------------------------------------------------------

    identifier: (_) => /[A-Za-z_][A-Za-z0-9_]*/,

    // Integer / real / scientific; tolerates the corpus's zero-padded exponent (`1e+070`,
    // `e-015`). A leading sign is a `unary_expression`, not part of the token.
    number: (_) => token(/(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?/),

    // Single-quoted; no escapes; cannot contain `'` or a newline. A `%` inside a string is data,
    // not a comment (the corpus has `sprintf('%.15f …')`), so it is allowed. `string` and
    // `command_label` share one terminal and are told apart by grammar position.
    string: ($) => $._single_quoted,
    // A single-quoted token immediately after a command keyword / head is the command label, not a
    // string-valued first argument or condition — pervasive in the corpus. Higher precedence makes
    // that the deterministic reading wherever the two compete.
    command_label: ($) => prec(1, $._single_quoted),
    _single_quoted: (_) => token(seq("'", /[^'\n]*/, "'")),

    // `% …` to end of line; no block comments. An `extra`, so it attaches anywhere.
    comment: (_) => token(seq("%", /[^\n]*/)),
  },
});

function commaSep1(rule) {
  return seq(rule, repeat(seq(",", rule)));
}
