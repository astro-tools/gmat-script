; Scope / definition / reference queries for the GMAT grammar.
;
; These power go-to-definition and find-references: a `@local.definition` introduces a name in the
; enclosing `@local.scope`, and a `@local.reference` resolves to the nearest such definition of the
; same text. Node names follow the frozen CST taxonomy (docs/design/decisions.md, D3).

; GMAT resources are file-global — `Create` may be referenced before it appears, and there is no
; lexical block scoping for names — so the whole script is a single scope.
(source_file) @local.scope

; ---- definitions ----------------------------------------------------------------------------------

; A resource is defined by its `Create` declaration: `Create Spacecraft Sat` defines `Sat`.
(create_command
  name: (identifier) @local.definition)

; A GmatFunction (.gmf) header defines the function name and its parameters.
(function_definition
  name: (identifier) @local.definition)

(parameter_list
  (identifier) @local.definition)

; A `For` loop binds its iteration variable.
(for_statement
  variable: (identifier) @local.definition)

; ---- references -----------------------------------------------------------------------------------

; Every name used anywhere is a reference. A member-access `property` is also an aliased identifier
; and is matched here too; naming no declared resource, it simply resolves to nothing — the safe
; direction (an unresolved reference is harmless; a missed one is not).
(identifier) @local.reference
