/**
 * @file Tree-sitter grammar for GMAT mission scripts — lexical core + configuration section.
 *
 * Implements the lexical layer, the configuration section (`Create` resource declarations and
 * `resource.field = value` assignments), and the shared value / expression grammar, per the frozen
 * CST node taxonomy in docs/design/decisions.md (D3 / D4). The grammar is a deliberately permissive
 * superset: it accepts what the parser must understand structurally and leaves semantic rules
 * (literal-only-in-configuration, type validity, …) to the linter.
 *
 * The mission sequence — `BeginMissionSequence` and everything after it: commands, control-flow and
 * solver blocks, and the bracket-LHS function-call command — extends this same grammar in the next
 * grammar milestone. Its node types slot into the marked `source_file` / `binary_expression`
 * extension points; nothing here needs to change for them.
 *
 * @license MIT
 */

/// <reference types="tree-sitter-cli/dsl" />
// @ts-check

// Expression precedence, loosest to tightest. Relational and logical operators (used only in
// `If` / `While` conditions) join `binary_expression` with the mission-sequence grammar; their
// precedence levels will sit below ADD.
const PREC = {
  ADD: 3, // + -
  MUL: 4, // * /
  POW: 5, // ^   (right associative)
  UNARY: 6, // leading + -
  CALL: 7, // f(...) / A(i, j)
  MEMBER: 8, // a.b
};

module.exports = grammar({
  name: "gmat",

  // Whitespace, newlines, and the `...` line continuation are layout, preserved as the parser's
  // between-token text so re-emission stays lossless (D6). A `% …` comment attaches anywhere as an
  // `extra`. The `...` continuation is layout, not a node, so it is an anonymous token here.
  extras: ($) => [/\s/, $.comment, token(seq("...", /[^\S\n]*/, /\r?\n/))],

  // `unquoted_value` is scanned externally (see src/scanner.c): GMAT's line-oriented config values
  // include raw, rest-of-line forms — multi-word enums, unquoted paths / dates, the doubled-quote
  // artifact — that the structured value grammar cannot represent (D13). The scanner emits it only
  // when the value is not a structured form, so it never competes with the literals below.
  externals: ($) => [$.unquoted_value],

  // The lexer treats `identifier` as the "word" token, so the `Create` / `GMAT` keywords are
  // extracted as whole-word keywords and an object legitimately *named* like one still lexes as an
  // identifier outside the keyword position.
  word: ($) => $.identifier,

  // A `Create` name-list and a following identifier-led assignment both start with an identifier,
  // and newlines are layout (D3 / D6), not statement terminators — so where a `Create` ends without
  // a `;` cannot be decided by one token of lookahead. The two interpretations diverge at the next
  // token (`= …` makes it an assignment; another name keeps the list), so GLR yields a single valid
  // parse; this lets the generator defer the choice to it.
  conflicts: ($) => [[$.create_command]],

  rules: {
    // The configuration section: a run of `#Include` directives, `Create` declarations, and
    // assignments (comments and blank lines attach as extras). The mission sequence —
    // `BeginMissionSequence` and the commands / blocks after it — is added to this choice next.
    source_file: ($) => repeat($._statement),

    _statement: ($) => choice($.include, $.create_command, $.assignment_command),

    // ---- structural ---------------------------------------------------------------------------

    // `#Include 'path'` preprocessor directive; top-level only; the trailing `;` is optional (both
    // forms occur in the corpus).
    include: ($) => seq("#Include", field("path", $.string), repeat(";")),

    // `Create <Type> <name> [<name> …]`. `<Type>` is parsed generically (any identifier) so new or
    // plugin resource types parse without a grammar change; type validity is the linter's job. Each
    // declared name may carry an `Array` size suffix `[r, c]` (only `Array` uses it — generic here).
    create_command: ($) =>
      seq(
        "Create",
        field("type", $.identifier),
        repeat1(seq(field("name", $.identifier), optional($.array_size), optional(","))),
        repeat(";"),
      ),

    // The `Array` size suffix, following the name it sizes: `A[3, 3]`. Generic (any name may carry
    // it) — pairing it to `Array` resources is the linter's job.
    array_size: ($) => seq("[", commaSep1($.number), "]"),

    // ---- assignment ---------------------------------------------------------------------------

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
        repeat(";"),
      ),

    // An object / field path, or an array-indexed target like `A(1, 1)`.
    _lhs: ($) => $._reference,

    // The right-hand side: a structured literal / expression, or — when no structured form fits —
    // GMAT's raw rest-of-line `unquoted_value` (multi-word enums, unquoted paths / dates, the
    // doubled-quote artifact). The external scanner emits `unquoted_value` only for the raw case, so
    // the two alternatives never overlap (D13).
    _value: ($) => choice($._expression, $.unquoted_value),

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

    argument_list: ($) => seq("(", optional(commaSep1($._expression)), ")"),

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

    // Arithmetic only here; relational (`< <= > >= == ~=`) and logical (`& |`) operators join this
    // rule with the condition grammar in the mission-sequence milestone.
    binary_expression: ($) => {
      const factor = [
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

    // Brace-list: empty, nestable; holds strings / refs / nested lists. Elements are separated by
    // commas or whitespace, and GMAT tolerates empty slots (`{a, , b}`), so commas are free-standing.
    list: ($) => seq("{", repeat(choice($._expression, ",")), "}"),

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
    command_label: ($) => $._single_quoted,
    _single_quoted: (_) => token(seq("'", /[^'\n]*/, "'")),

    // `% …` to end of line; no block comments. An `extra`, so it attaches anywhere.
    comment: (_) => token(seq("%", /[^\n]*/)),
  },
});

function commaSep1(rule) {
  return seq(rule, repeat(seq(",", rule)));
}
