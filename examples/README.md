# Examples

Runnable scripts that exercise the `gmat_script` library against the installed package. Each prints
a before/after so you can see the transformation it performs. None of them need a GMAT install.

```bash
pip install gmat-script        # or: uv sync, from a checkout
python examples/edit_field.py
```

| Script | What it shows |
|--------|---------------|
| [`edit_field.py`](edit_field.py) | Read a resource field, then set it — `script.spacecraft["Sat"]["SMA"] = 8000`. |
| [`rename_resource.py`](rename_resource.py) | Rename a resource with and without rewriting its references. |
| [`format_in_place.py`](format_in_place.py) | Format a messy script into canonical form, written back to the file. |
| [`lint_script.py`](lint_script.py) | Lint a flawed script — type, field, reference-target, and enum findings — then show it clean. |

For the concepts behind these, see the documentation:
[the typed AST](https://astro-tools.github.io/gmat-script/typed-ast/),
[editing](https://astro-tools.github.io/gmat-script/editing/),
[the formatter](https://astro-tools.github.io/gmat-script/formatting/), and
[the linter](https://astro-tools.github.io/gmat-script/lint/).
