"""Shipped package data: the version-pinned GMAT field catalogue(s).

``fields-<version>.json`` files here are generated at build time by
:mod:`gmat_script.tools.gen_catalog` and read at runtime by :mod:`gmat_script.catalog` through
``importlib.resources``. This is a package (not a bare directory) so the catalogue resolves the same
way in a built wheel as in an editable install.
"""
