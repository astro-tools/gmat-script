# API reference

The public surface of `gmat_script`. It is deliberately minimal and additive: the `parse` entry
point and the `Tree` it returns, the `ErrorNode` / `Position` records that describe syntax errors,
the typed `Script` overlay with its mutation API (`ObjectRef`, `RawValue`, `MutationError`), the
canonical `format` pretty-printer, the `lint` checker with its `Diagnostic` / `Severity` records, and
the `Catalog` field catalogue (`load_catalog`, `FieldSpec`, `TypeSpec`). Each layer is re-exported
here as it lands.

For a worked introduction see [Getting started](getting-started.md); for the error model see
[Error reporting](errors.md); for the linter see [Linting](lint.md); for the catalogue see
[The field catalogue](catalogue.md).

::: gmat_script
