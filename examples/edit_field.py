"""Programmatically edit a field on a GMAT resource, then print the before/after script.

Run with:  python examples/edit_field.py
"""

from __future__ import annotations

from gmat_script import Script

SOURCE = """\
Create Spacecraft Sat
Sat.SMA = 7000
Sat.ECC = 0.01

BeginMissionSequence
Propagate DefaultProp(Sat) {Sat.ElapsedDays = 1}
"""


def main() -> None:
    script = Script.parse(SOURCE)

    print("--- before ---")
    print(script.to_source(), end="")

    # Read the current value (coerced to a Python int), then raise the orbit.
    sat = script.spacecraft["Sat"]
    print(f"\nSMA was {sat['SMA']}\n")

    # Two equivalent ways to set a field; the dict-subscript form is the idiomatic one.
    script.spacecraft["Sat"]["SMA"] = 8000
    script.set_field("Sat", "ECC", 0.001)

    print("--- after ---")
    print(script.to_source(), end="")
    print(f"\nSMA is now {script.spacecraft['Sat']['SMA']}")


if __name__ == "__main__":
    main()
