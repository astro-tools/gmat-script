"""Curated GMAT knowledge the reflected catalogue does not carry — kept small and corpus-validated.

The field catalogue (``catalog``) is generated from a *default headless* GMAT load, so
it omits two things the linter must still recognise to avoid false positives on real scripts:

* **Plugin resource types** — types from optional GMAT plugins (OpenFrames, the EMTG / optimal-
  control suite, MATLAB, extra optimisers) absent from the default load, so never reflected. They
  are real ``Create`` targets; :data:`KNOWN_PLUGIN_TYPES` lets ``unknown-resource-type`` accept them
  while the catalogue-driven field rules degrade gracefully (no spec → no check) on them.
* **Built-in object instances** — celestial bodies, default barycenters, default coordinate systems,
  and a couple of special object-field keywords that exist in every mission with no ``Create``.
  :data:`GMAT_BUILTINS` lets ``undeclared-reference`` treat them as resolved.

Both sets are validated to give zero false positives across the R2026a stock corpus (the precision
bar). They are deliberately conservative: type *keywords* that are themselves catalogue types
(``ObjectReferenced``, ``MJ2000Eq``, ``BodyFixed`` …) are recognised via the catalogue, not listed
here.
"""

from __future__ import annotations

__all__ = ["GMAT_BUILTINS", "KNOWN_PLUGIN_TYPES"]

# Resource types from optional GMAT plugins, absent from the default-load catalogue
# (#19 / D15 deferred corpus-completeness to the linter). All appear in the R2026a stock corpus.
KNOWN_PLUGIN_TYPES: frozenset[str] = frozenset(
    {
        # OpenFrames visualisation plugin
        "OpenFramesView",
        "OpenFramesInterface",
        "OpenFramesVector",
        "OpenFramesSensorMask",
        # EMTG / CSALT optimal-control suite
        "EMTGSpacecraft",
        "DynamicsConfiguration",
        "Trajectory",
        "Phase",
        "OptimalControlGuess",
        "OptimalControlFunction",
        "CustomLinkageConstraint",
        # External optimisers
        "VF13ad",
        "SNOPT",
        # MATLAB interface (constructs only with the MATLAB plugin loaded)
        "MatlabFunction",
        # N-plate SRP / estimation extras
        "Plate",
        "ProcessNoiseModel",
        "EstimatedParameter",
        "Smoother",
        "PlanetographicRegion",
    }
)

# Object names referenceable without a ``Create``: the default solar-system bodies and points, the
# coordinate systems GMAT defines in every mission, and two special object-field keywords (``Local``
# burn frame; ``Lagrange`` interpolator) whose object-typed fields take a keyword, not an instance.
GMAT_BUILTINS: frozenset[str] = frozenset(
    {
        # Default celestial bodies (always in GMAT's solar system)
        "Sun",
        "Mercury",
        "Venus",
        "Earth",
        "Luna",
        "Mars",
        "Jupiter",
        "Saturn",
        "Uranus",
        "Neptune",
        "Pluto",
        # Default calculated points
        "SolarSystemBarycenter",
        "EarthMoonBarycenter",
        # Coordinate systems built into every mission
        "EarthMJ2000Eq",
        "EarthMJ2000Ec",
        "EarthFixed",
        "EarthICRF",
        "EarthFK5",
        # Special object-field keywords that name no creatable resource
        "Local",
        "Lagrange",
    }
)
