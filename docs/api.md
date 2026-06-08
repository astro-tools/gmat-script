# API reference

The public surface of `gmat_script`. It is deliberately minimal and additive: the `parse` entry
point and the `Tree` it returns, the `ErrorNode` / `Position` records that describe syntax errors,
the typed `Script` overlay with its mutation API (`ObjectRef`, `RawValue`, `MutationError`), and the
canonical `format` pretty-printer. Each layer is re-exported here as it lands.

For a worked introduction see [Getting started](getting-started.md); for the error model see
[Error reporting](errors.md).

::: gmat_script
