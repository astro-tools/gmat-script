; Symbol-tag queries for the GMAT grammar — the document-symbol outline and code navigation.
;
; A `@definition.*` capture names a symbol declared in the file; a `@reference.*` capture names a
; use / call site. The `@name` capture inside each marks the symbol's name span. Node names follow
; the frozen CST taxonomy (docs/design/decisions.md, D3).

; ---- definitions ----------------------------------------------------------------------------------

; Each resource declared with `Create` is a top-level symbol (`Create Spacecraft Sat` → `Sat`).
(create_command
  name: (identifier) @name) @definition.class

; A GmatFunction (.gmf) header defines a function.
(function_definition
  name: (identifier) @name) @definition.function

; ---- references -----------------------------------------------------------------------------------

; Mission commands — the operations invoked in the sequence (`Propagate`, `Maneuver`, …).
(command
  name: (identifier) @name) @reference.call

; Output-binding function calls — `[out] = Func(args)`. The function reference may be a bare name, a
; dotted path, or a parenthesised call; tag the leaf name in each shape.
(function_call_command
  function: (identifier) @name) @reference.call

(function_call_command
  function: (member_expression
    property: (identifier) @name)) @reference.call

(function_call_command
  function: (call_expression
    function: (identifier) @name)) @reference.call

(function_call_command
  function: (call_expression
    function: (member_expression
      property: (identifier) @name))) @reference.call
