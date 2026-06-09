# Marketing assets

`demo.gif` — a short animated capture of the extension in action (highlighting + live diagnostics +
hover + format-on-save), shown at the top of the extension's marketplace listing and referenced from
`../README.md` (the reference is commented out until the file exists).

## Recording `demo.gif`

A repeatable ~8-second capture. Keep it small and looping.

**Setup**

1. Install the extension (run the *Extension Development Host* from this folder, or install the
   packaged `.vsix`) and `pip install "gmat-script[lsp]"` into the interpreter VS Code uses, so the
   language server is live.
2. Use a clean window: dark theme, no minimap, font size ~16, a single editor column ~80 columns
   wide. Hide the sidebar and status-bar clutter.
3. Create a new file `demo.script` and leave it empty.

**The take** (type at a natural pace; let each step settle for ~1 s)

1. Type the snippet below. Highlighting colours resources, fields, the burn axis, and commands as you
   go:

   ```text
   Create Spacecraft Sat
   Sat.SMA = 7000

   Create ImpulsiveBurn TOI
   TOI.Axes = VNB

   BeginMissionSequence
   Maneuver TOI(Sat)
   ```

2. Change `Sat.SMA = 7000` to `Sat.SMA = 'high'`. A red squiggle appears under `'high'`; hover it to
   show the `type-mismatch` diagnostic ("field 'SMA' expects a number, got a quoted string").
3. Hover `Axes` to show the field doc card (type + allowed values `VNB, LVLH, MJ2000Eq,
   SpacecraftBody`).
4. Fix `Sat.SMA` back to `7000`; the squiggle clears.
5. Mangle the spacing (e.g. `GMAT Sat.SMA=7000;`) and press **Save** — format-on-save snaps it back to
   canonical form.

**Export**

Capture the editor region only, export an optimized looping GIF (≈800 px wide, a few seconds), save
it here as `demo.gif`, and uncomment the `![GMAT Script in VS Code](images/demo.gif)` line in
`../README.md`.
