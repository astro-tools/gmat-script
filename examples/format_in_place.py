"""Format a messy GMAT script into canonical form, in place, and show the before/after.

Run with:  python examples/format_in_place.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from gmat_script import format

MESSY = """\
Create Spacecraft   Sat
GMAT Sat.SMA=7000;
GMAT Sat.ECC = 0.01 ;


BeginMissionSequence
If Sat.ElapsedDays < 1
Propagate DefaultProp(Sat) {Sat.ElapsedDays = 1}
EndIf
"""


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "mission.script"
        path.write_text(MESSY, encoding="utf-8")

        print("--- before ---")
        print(path.read_text(encoding="utf-8"), end="")

        # Read -> format -> write back: the in-place workflow `gmat-script format` automates.
        canonical = format(path.read_text(encoding="utf-8"))
        path.write_text(canonical, encoding="utf-8")

        print("\n--- after ---")
        print(path.read_text(encoding="utf-8"), end="")


if __name__ == "__main__":
    main()
