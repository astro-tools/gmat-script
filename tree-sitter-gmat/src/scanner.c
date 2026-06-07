/*
 * External scanner for GMAT's unquoted, rest-of-logical-line values.
 *
 * GMAT's initialization values are line-oriented: a value is "the rest of the logical line,"
 * interpreted afterward by the field's type. Most values are recognized structured forms — numbers,
 * quoted strings, `{…}` / `[…]` literals, references, expressions — which the generated grammar
 * parses directly. But the stock corpus also carries values that no structured form can represent:
 * unquoted multi-word enums (`Relative Position`), unquoted file paths (`../data/x.och`), unquoted
 * dates (`19 Aug 2015 00:00:00.000`), and the doubled-quote artifact (`''…''`). Per the GMAT User
 * Guide (Script Language → File Paths, Enumerated Values) and the running samples, these are valid
 * GMAT and must parse. See docs/design/decisions.md (D13).
 *
 * Because the grammar (D3 / D6) keeps newlines as layout rather than statement terminators, a value
 * spanning the rest of the line cannot be recognized by the context-free lexer: the same prefix
 * (`Relative`) begins both a structured reference and a raw multi-word value. This scanner resolves
 * it with one token of line-aware lookahead. At a value position it scans to the end of the logical
 * line and emits `unquoted_value` only when the content carries a "raw" signature the structured
 * grammar cannot model; otherwise it defers, letting the grammar parse the structured form.
 */

#include "tree_sitter/parser.h"

#include <stdbool.h>
#include <stdint.h>

enum TokenType {
  UNQUOTED_VALUE,
};

// Characters that begin a structured form the grammar parses on its own.
static inline bool starts_structured(int32_t c) {
  return c == '{' || c == '[' || c == '(';
}

// Statement / value boundaries: an un-continued line break, the optional terminator, a comment, EOF.
static inline bool ends_value(int32_t c) {
  return c == '\n' || c == '\r' || c == ';' || c == '%' || c == 0;
}

// A "word" character — the makings of a bareword (identifier, number, or dotted token). Two
// barewords separated only by whitespace is the multi-word signature (`Relative Position`).
static inline bool is_word(int32_t c) {
  return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_' ||
         c == '.';
}

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

bool tree_sitter_gmat_external_scanner_scan(void *payload, TSLexer *lexer, const bool *valid_symbols) {
  (void)payload;

  if (!valid_symbols[UNQUOTED_VALUE]) {
    return false;
  }

  // Skip leading horizontal whitespace; it sits between the `=` and the value, not in the token.
  while (lexer->lookahead == ' ' || lexer->lookahead == '\t') {
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

    // Path and time characters never appear in a structured GMAT value.
    if (c == '/' || c == '\\' || c == ':') {
      raw = true;
    }

    if (c == ' ' || c == '\t') {
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
