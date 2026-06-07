/**
 * @file Tree-sitter grammar for GMAT mission scripts — scaffold stub.
 *
 * This is a deliberately minimal placeholder. Its only job is to exercise the
 * generate -> compile -> vendor -> corpus-test pipeline end to end while the package
 * infrastructure is stood up. The real lexical + configuration grammar and the
 * mission-sequence grammar replace it in the grammar milestones; the frozen CST node
 * taxonomy they must implement is recorded in docs/design/decisions.md (D3).
 *
 * @license MIT
 */

/// <reference types="tree-sitter-cli/dsl" />
// @ts-check

module.exports = grammar({
  name: "gmat",

  // Whitespace is layout; `% …` comments attach anywhere as interstitial text. Both are
  // preserved as between-token text so the eventual grammar can re-emit byte-for-byte (D6).
  extras: ($) => [/\s/, $.comment],

  rules: {
    source_file: ($) => repeat($.identifier),

    identifier: (_) => /[A-Za-z_][A-Za-z0-9_]*/,

    comment: (_) => token(seq("%", /[^\n]*/)),
  },
});
