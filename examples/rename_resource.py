"""Rename a GMAT resource and watch its references update across the script.

Run with:  python examples/rename_resource.py
"""

from __future__ import annotations

from gmat_script import Script

SOURCE = """\
Create Spacecraft Sat
Sat.SMA = 7000

Create ImpulsiveBurn TOI
TOI.Element1 = 0.5

BeginMissionSequence
Maneuver TOI(Sat)
Propagate DefaultProp(Sat) {Sat.ElapsedDays = 1}
Report rf Sat.Earth.SMA
"""


def main() -> None:
    print("--- before ---")
    print(SOURCE, end="")

    # Rename Sat -> MainSat. By default every *reference* to the object is rewritten too — the
    # Maneuver / Propagate operands and the root of Sat.Earth.SMA — while the field-name segments
    # (the trailing .Earth.SMA) and the resource's GMAT type are left untouched.
    script = Script.parse(SOURCE)
    script.rename_resource("Sat", "MainSat")
    print("\n--- after (references updated) ---")
    print(script.to_source(), end="")

    # Pass update_references=False to rename only the declaration, leaving every call site as-is.
    only_decl = Script.parse(SOURCE)
    only_decl.rename_resource("Sat", "MainSat", update_references=False)
    print("\n--- after (declaration only) ---")
    print(only_decl.to_source(), end="")


if __name__ == "__main__":
    main()
