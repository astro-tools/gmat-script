# API reference

The public surface of `gmat_script`. It grows as each milestone lands; today it is the `parse`
entry point.

## Quick start

```python
from gmat_script import parse

tree = parse("Create Spacecraft Sat\nSat.SMA = 7000\n")

tree.has_errors      # False — the script is well-formed
tree.to_source()     # round-trips byte-for-byte to the input (so does tree.text)

bad = parse("BeginMissionSequence\nIf Sat.TA > 90\n   Propagate Prop(Sat);\n")
for error in bad.errors:
    print(error.type, error.start.line, error.start.column, error.message)
```

`parse` never raises on malformed input: it returns a tree carrying `ERROR` / `MISSING` nodes
localised to the broken construct (design decision D7). Error positions are 1-indexed. The raw
tree-sitter node is available as `tree.root_node` for downstream layers.

::: gmat_script
