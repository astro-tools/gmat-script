"""Build-time tooling for gmat-script.

This subpackage holds code that runs at build / CI time only, never at runtime. Its single module,
:mod:`gmat_script.tools.gen_catalog`, is the *only* GMAT-touching code in the project: it walks
``gmatpy`` reflection to regenerate the shipped field catalogue. Installing gmat-script never
imports anything here (design decisions D9 / D15).
"""
