; Syntax-highlighting queries for the GMAT grammar.
;
; Node names follow the frozen CST taxonomy (docs/design/decisions.md, D3). Captures use the
; standard tree-sitter highlight names so any host theme colours them without remapping. Patterns
; are ordered specific-first: a host that resolves overlaps by first match (the tree-sitter
; convention) gives the earlier, more specific capture precedence over the trailing catch-alls.

; ---- comments / literals --------------------------------------------------------------------------

(comment) @comment

(number) @number
(string) @string

; A single-quoted command / mission-step label (`Propagate 'Raise apogee' …`) — distinct from a
; string-valued argument.
(command_label) @label

; ---- keywords -------------------------------------------------------------------------------------

; Structural keywords: the configuration / sequence boundary words, control-flow and solver block
; delimiters, and the GmatFunction header. Resource types and command keywords are *not* keywords —
; the grammar parses them generically (D3) — so they are not enumerable here.
[
  "Create"
  "GMAT"
  "If"
  "Else"
  "EndIf"
  "For"
  "EndFor"
  "While"
  "EndWhile"
  "Target"
  "EndTarget"
  "Optimize"
  "EndOptimize"
  "BeginScript"
  "EndScript"
  "function"
] @keyword

"#Include" @keyword
(begin_mission_sequence) @keyword

; ---- operators / punctuation ----------------------------------------------------------------------

[
  "="
  "+"
  "-"
  "*"
  "/"
  "^"
  "<"
  "<="
  ">"
  ">="
  "=="
  "~="
  "&"
  "|"
] @operator

[
  "("
  ")"
  "["
  "]"
  "{"
  "}"
] @punctuation.bracket

[
  ","
  ";"
  ":"
  "."
] @punctuation.delimiter

; ---- names ----------------------------------------------------------------------------------------

; The resource type in a `Create <Type> <name>` declaration.
(create_command
  type: (identifier) @type)

; A command head — the mission operation (`Propagate`, `Maneuver`, `Report`, …). Generic by design
; (D3), so highlighted by position rather than by an enumerated keyword set.
(command
  name: (identifier) @function)

; A dotted field / property access — the trailing names of `Sat.SMA`, `FM.GravityField.Earth`.
(member_expression
  property: (identifier) @property)

; Catch-all: every other name is a resource / variable reference. Last, so the specific captures
; above win on hosts that resolve overlaps by first match.
(identifier) @variable
