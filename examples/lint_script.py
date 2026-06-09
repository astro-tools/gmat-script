"""Lint a GMAT script: print the diagnostics for a flawed script, then show it clean.

Run with:  python examples/lint_script.py

The linter checks a script's *structure* against the bundled field catalogue — unknown types and
fields, type / enum / reference-target mismatches, duplicate names, and unused or undeclared
references. It never runs the mission and needs no GMAT install.
"""

from __future__ import annotations

from gmat_script import lint

# A syntactically valid script with several seeded *structural* problems the linter catches.
FLAWED = """\
Create Spacecraft Sat
Sat.SMA = 'high'
Sat.Naem = 7000

Create Thruster Thr
Sat.Tanks = {Thr}

Create ImpulsiveBurn TOI
TOI.Axes = Sideways

BeginMissionSequence
Maneuver TOI(Sat)
"""

# The same mission with each finding addressed: a numeric SMA, the misspelled field corrected, a
# FuelTank in the tank slot, and a valid burn axis. The linter reports nothing.
CLEAN = """\
Create Spacecraft Sat
Sat.SMA = 7000
Sat.Id = 'SAT-1'

Create FuelTank Tank
Sat.Tanks = {Tank}

Create ImpulsiveBurn TOI
TOI.Axes = VNB

BeginMissionSequence
Maneuver TOI(Sat)
"""


def report(label: str, source: str) -> None:
    print(f"--- {label} ---")
    diagnostics = lint(source)
    if not diagnostics:
        print("no findings")
        return
    for d in diagnostics:
        print(f"{d.start.line}:{d.start.column} {d.severity} {d.rule}: {d.message}")


def main() -> None:
    report("flawed script", FLAWED)
    print()
    report("cleaned script", CLEAN)


if __name__ == "__main__":
    main()
