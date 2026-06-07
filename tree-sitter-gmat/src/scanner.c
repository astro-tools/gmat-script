/*
 * External scanner for GMAT scripts. Three tokens, all of which need line-aware lookahead the
 * context-free lexer cannot express (see docs/design/decisions.md, D13 / D4 / the statement-boundary
 * note in grammar.js):
 *
 *   - UNQUOTED_VALUE — GMAT's unquoted, rest-of-logical-line config values: multi-word enums
 *     (`Relative Position`), unquoted file paths (`../data/x.och`), unquoted dates
 *     (`19 Aug 2015 …`), and the doubled-quote artifact (`''…''`). No structured value form can
 *     represent these, so they are scanned raw and emitted only at a value position.
 *
 *   - SCRIPT_BODY — the opaque raw text inside a `BeginScript` … `EndScript` block, consumed
 *     verbatim up to (but not including) the `EndScript` keyword, never re-parsed.
 *
 *   - TERMINATOR — the statement boundary (`;`, one-or-more newlines, or EOF). A GMAT statement is
 *     one logical line; because the grammar's variadic `Create` name lists and command arguments
 *     consume bare identifiers, a newline cannot be plain layout or two `;`-less statements would
 *     merge. This token is hidden and emitted only where the grammar marks it valid — so newlines
 *     inside `(…)` / `{…}` / `[…]` (where it is not valid) stay layout, and the `...` continuation
 *     (an `extra` that swallows its own newline) never reaches the scanner as a boundary.
 */

#include "tree_sitter/parser.h"

#include <stdbool.h>
#include <stdint.h>

enum TokenType {
  UNQUOTED_VALUE,
  SCRIPT_BODY,
  TERMINATOR,
};

// Characters that begin a structured form the grammar parses on its own.
static inline bool starts_structured(int32_t c) {
  return c == '{' || c == '[' || c == '(';
}

// Statement / value boundaries: an un-continued line break, the optional terminator, a comment, EOF
// — plus `,` and `)`, which bound a raw value used as a call argument (`f(opt, ../path)`). No
// structured-or-unquoted GMAT value contains a bare `,` / `)`, so adding them never truncates a
// value position; it only stops a raw call-argument value at its separator / closing paren.
static inline bool ends_value(int32_t c) {
  return c == '\n' || c == '\r' || c == ';' || c == '%' || c == ',' || c == ')' || c == 0;
}

// A "word" character — the makings of a bareword (identifier, number, or dotted token). Two
// barewords separated only by whitespace is the multi-word signature (`Relative Position`).
static inline bool is_word(int32_t c) {
  return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_' ||
         c == '.';
}

static inline bool is_hspace(int32_t c) { return c == ' ' || c == '\t'; }

void *tree_sitter_gmat_external_scanner_create(void) { return NULL; }
void tree_sitter_gmat_external_scanner_destroy(void *payload) { (void)payload; }
unsigned tree_sitter_gmat_external_scanner_serialize(void *payload, char *buffer) {
  (void)payload;
  (void)buffer;
  return 0;
}
void tree_sitter_gmat_external_scanner_deserialize(void *payload, const char *buffer, unsigned length) {
  (void)payload;
  (void)buffer;
  (void)length;
}

// Try to match the literal `EndScript` followed by a non-word boundary at the current position,
// consuming the matched characters. Returns true on a full, boundary-terminated match.
static bool match_end_script(TSLexer *lexer) {
  static const char kw[] = "EndScript";
  for (int i = 0; kw[i] != 0; i++) {
    if (lexer->lookahead != (int32_t)kw[i]) {
      return false;
    }
    lexer->advance(lexer, false);
  }
  int32_t after = lexer->lookahead;
  return !is_word(after);
}

// SCRIPT_BODY: consume everything from here to the line that begins `EndScript`, exclusive.
static bool scan_script_body(TSLexer *lexer) {
  // Leading whitespace / newlines sit between `BeginScript` and the body content, not in it.
  while (is_hspace(lexer->lookahead) || lexer->lookahead == '\r' || lexer->lookahead == '\n') {
    lexer->advance(lexer, true);
  }
  if (lexer->lookahead == 0) {
    return false; // nothing but whitespace, then EOF — empty body
  }

  bool any = false;
  for (;;) {
    // At a line start: the body ends here if this line is the `EndScript` terminator.
    lexer->mark_end(lexer);
    while (is_hspace(lexer->lookahead)) {
      lexer->advance(lexer, false);
    }
    if (match_end_script(lexer)) {
      if (!any) {
        return false; // empty body — let the grammar match `EndScript` directly
      }
      lexer->result_symbol = SCRIPT_BODY; // end already marked at this line's start
      return true;
    }

    // Not `EndScript`: this whole line is body. Consume through its newline, then re-check.
    for (;;) {
      int32_t c = lexer->lookahead;
      if (c == 0) {
        lexer->mark_end(lexer);
        lexer->result_symbol = SCRIPT_BODY;
        return any; // EOF before EndScript — emit what we have (recovery)
      }
      lexer->advance(lexer, false);
      any = true;
      if (c == '\n') {
        break;
      }
    }
  }
}

// TERMINATOR: a `;`, one-or-more newlines, or EOF at a statement boundary.
static bool scan_terminator(TSLexer *lexer) {
  // Skip horizontal whitespace between the last token and the terminator.
  while (is_hspace(lexer->lookahead) || lexer->lookahead == '\r') {
    lexer->advance(lexer, true);
  }
  // A trailing line comment with no preceding `;` still ends the statement — skip it to reach the
  // newline (the comment bytes round-trip as interstitial; only this rare no-`;` case loses the
  // comment node, the `;` case below stops before the comment so it stays a node).
  if (lexer->lookahead == '%') {
    while (lexer->lookahead != '\n' && lexer->lookahead != 0) {
      lexer->advance(lexer, true);
    }
  }

  int32_t c = lexer->lookahead;
  if (c != ';' && c != '\n' && c != 0) {
    return false; // more content on this logical line — defer
  }

  // Consume a run of terminators and the blank lines between them, so consecutive statements leave
  // no empty statement behind. Stop before a comment or content so own-line comments still attach as
  // `comment` nodes.
  while (true) {
    c = lexer->lookahead;
    if (c == ';' || c == '\n' || c == '\r' || is_hspace(c)) {
      lexer->advance(lexer, false);
    } else {
      break;
    }
  }
  lexer->mark_end(lexer);
  lexer->result_symbol = TERMINATOR;
  return true;
}

// UNQUOTED_VALUE: GMAT's raw rest-of-logical-line value, emitted only when it carries a signature no
// structured form has.
static bool scan_unquoted_value(TSLexer *lexer) {
  // Skip leading horizontal whitespace; it sits between the `=` and the value, not in the token.
  while (is_hspace(lexer->lookahead)) {
    lexer->advance(lexer, true);
  }

  int32_t c = lexer->lookahead;

  // Empty value, or a structured collection / parenthesis: let the grammar handle it.
  if (ends_value(c) || starts_structured(c)) {
    return false;
  }

  bool raw = false;

  // A value beginning with a quote is a normal string (grammar's job) unless it is the doubled-quote
  // artifact `''…''`, which no string rule accepts — that is raw. Peek the second character.
  if (c == '\'') {
    lexer->advance(lexer, false);
    if (lexer->lookahead != '\'') {
      return false; // a well-formed string literal — defer (the lexer rewinds on false)
    }
    raw = true; // doubled quote — consume the rest of the line as a raw value
  }

  // Scan to the end of the logical line, watching for raw signatures.
  bool space_pending = false; // whitespace seen since the last value character
  bool prev_word = false;     // was that last value character a word character
  bool any = false;           // have we consumed any value character

  for (;;) {
    c = lexer->lookahead;
    if (ends_value(c)) {
      break;
    }

    // A quoted string is opaque: the spaces, separators, and path characters inside it are data, not
    // value structure, so a structured value that merely *contains* a string (`strcmp('a b', 'c')`)
    // must not be mistaken for a raw multi-word value. Skip the string so it neither trips a raw
    // signature nor ends the value, and treat it as a non-word for the multi-word heuristic.
    if (c == '\'') {
      lexer->advance(lexer, false);
      while (lexer->lookahead != '\'' && lexer->lookahead != '\n' && lexer->lookahead != 0) {
        lexer->advance(lexer, false);
      }
      if (lexer->lookahead == '\'') {
        lexer->advance(lexer, false);
      }
      any = true;
      space_pending = false;
      prev_word = false;
      continue;
    }

    // A bracketed sub-structure — a call / index `(…)`, an array `[…]`, or a list `{…}` — means the
    // value is structured, not raw (`diag([1 2 3])`, `Sqrt(a / b)`). Its insides would otherwise trip
    // the raw signatures below; defer and let the grammar parse it.
    if (starts_structured(c)) {
      return false;
    }

    // Path and time characters never appear in a structured GMAT value.
    if (c == '/' || c == '\\' || c == ':') {
      raw = true;
    }

    if (is_hspace(c)) {
      space_pending = any;
    } else {
      bool word = is_word(c);
      // Two barewords with only whitespace between them — a multi-word value.
      if (space_pending && prev_word && word) {
        raw = true;
      }
      space_pending = false;
      prev_word = word;
      any = true;
    }

    lexer->advance(lexer, false);
  }

  if (!raw || !any) {
    return false;
  }

  lexer->mark_end(lexer);
  lexer->result_symbol = UNQUOTED_VALUE;
  return true;
}

bool tree_sitter_gmat_external_scanner_scan(void *payload, TSLexer *lexer, const bool *valid_symbols) {
  (void)payload;

  // The terminator is offered first so a newline at a statement boundary becomes a boundary rather
  // than layout. Where it is not valid (inside brackets) the scanner falls through and the newline
  // stays an `extra`.
  if (valid_symbols[TERMINATOR] && scan_terminator(lexer)) {
    return true;
  }

  if (valid_symbols[SCRIPT_BODY] && scan_script_body(lexer)) {
    return true;
  }

  if (valid_symbols[UNQUOTED_VALUE]) {
    return scan_unquoted_value(lexer);
  }

  return false;
}
