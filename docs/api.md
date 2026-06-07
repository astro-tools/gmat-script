# API reference

The public surface of `gmat_script`. It is deliberately minimal and additive — today it is the
`parse` entry point and the `Tree` it returns, plus the `ErrorNode` / `Position` records that
describe syntax errors. Later layers (the typed AST, the formatter) are re-exported here as they
land.

For a worked introduction see [Getting started](getting-started.md); for the error model see
[Error reporting](errors.md).

::: gmat_script
