# Judge Q&A

Short, honest answers. Every number here is read from a file in this repo (`results/scoreboard.json`, `app/data/*`), not typed by hand.

### "Isn't this just vision plus a map?"

The comparison is scored, not asserted. Both models read the exact same 17 tiles of the same 1954 scans, with the same prompt, the same effort setting, and the same tool schema (`eval/prompt.py`, frozen; `eval/run_eval.py` confirms both models' requests matched before scoring). `eval/score.py` checks each answer against a hand-traced key (`data/plan_tanks.geojson`, `testset/keys/*`), not against the model's own claim.

Result: on the easy sheet (the 1:25,000 city plan), both models tie — 18 of 18 tanks, 88% of printed names read exactly. On the hard sheet (the 1:250,000 colour front sheet — smaller ink, more clutter), Opus 5.5 reads it far better: **90% verified recall vs 52%**, and **1 invented tank per run vs 11**, while being faster and cheaper per call. That gap is the actual finding (`app/data/narrative.json`), not a vibe.

And the map never draws anything: every tank outline on screen comes from `pipeline/grow.py` running on the scan's own pixels, never from the model's box. If the model points at nothing (a road, a shadow, built-up shading), `grow()` refuses, and the refusal is shown, not discarded — that's the Fence panel.

### "Didn't MOD Foundation already do this?"

For Bengaluru, yes — by hand. Their traced lost/existing lake layers are exactly what makes Bengaluru the one city we can *score* against (that's the whole reason it's the proof city). Every other city here has no such hand-traced record. A 1:250,000 US Army sheet, read by a model, is the only way this data exists at all for Chennai, Hyderabad, Pune or Kolkata today.

### "Does it predict floods?"

No, never. Two separate things, both real but neither is a forecast:

- **Bengaluru's flood backtest**: official flood points (KGIS/BBMP, 396 of them) sit within 250 m of a *lost* lake 2.55× more often than random chance, and within 250 m of a *surviving* lake 0.77× as often (`scripts/backtest.py --area gba`, reproduced live per-city in `app/data/backtest.json`). That's a historical correlation on the city's own published list — Bengaluru only, since it's the only city with a published flood-point list at all (build-2 rule 2).
- **The address card**, for every city: distance to the nearest 1954 tank, lost or surviving, what stands there now and its source. It never says whether a place will flood. The rain-pooling layer (Bengaluru only, P2) is explicitly labelled "where water would pool on today's terrain" — a DEM depression-fill, not a prediction either.

### "Who uses this next week?"

- Someone renting or buying, checking an address before they sign.
- Someone whose street floods every monsoon, looking for why.
- Civic groups and journalists downloading a city's lake data (GeoJSON + CSV, `LICENSE-DATA.txt`) for their own reporting, without having to trace 70-year-old scans themselves.

### "How accurate is the alignment?"

Bengaluru's plan sheet: ±51 m RMS from 6 ground-control points (`data/plan_georef.json`). Bengaluru's front sheet and every other city: the sheet's own printed neatline corners, read either by hand (Bengaluru's front sheet, historically) or auto-detected from the scan (`scripts/georef.find_sheet_neatline`, every other city), then checked against the 3 largest *named* lakes in the window — median offset to the nearest blue ink on the sheet vs the 400 m bar:

| City | Median offset | Shipped? |
|---|---:|---|
| Chennai | 37 m | Yes |
| Hyderabad | 0 m | Yes |
| Pune | 0 m | Yes |
| Kolkata | 0 m | Yes |
| Mumbai | 520 m | No — dropped |
| Mysuru | 493 m | No — dropped |

Mumbai and Mysuru failed and are not in the app. Mumbai's failure has an identified cause: this specific U502 sheet's reachable window (its centre sits right at the sheet's own edge) is mostly Arabian Sea and rural Raigad district — Mumbai's own well-known lakes (Vihar, Tulsi, Powai) are on the *next* sheet north, and the "named lakes" available to check alignment against in-window are mostly river segments, not compact lakes. Mysuru's cause is less clear: the neatline detection and the sheet's general georeferencing checked out fine by eye, but 2 of the 3 reference lakes (one a large, distant reservoir) had offsets over 400 m; worth a second look, not chased further given time. Per "ship 3 good cities rather than 6 doubtful ones," both are left out and the numbers above are the honest record of why.

### "What if Opus 5.5 is wrong?"

Four separate backstops, all visible in the app, not just claimed:

1. **Consensus.** A tank only ships if it's found in at least 2 of 3 independent runs.
2. **Refusals shown, not filtered.** Every point the model pointed at that `grow()` found no water under is in the Fence panel, with the reason and the crop — "The model pointed here. The map says no."
3. **A crop on every tank.** Click any tank (or any Fence entry) and see the actual sheet detail it was read from.
4. **Provenance on every download.** Every exported feature carries its status, its source for "what's there now," the model, the prompt version, how many runs agreed, and the city's measured alignment error.

### "What did you build today?"

See `BUILDLOG.md`, appended honestly through the day rather than reconstructed after. Short version: Phase 0 (audit) and the real Opus 5 vs 5.5 eval were substantially done by a parallel session (kere-36) before this session took over the multi-city pivot; this session built the generalized georeferencing, the full per-city pipeline (download → tile → read → assemble → OSM alignment QA → export) for 6 candidate cities, and the app's city-picker/search/downloads product layer.

### "What breaks first?"

Worst first:

- **Small ponds and tanks inside built-up colour fills.** `pipeline/grow.py`'s thresholds are frozen (tuned once against the answer key, never re-tuned to chase a score) — a tank under ~150 connected pixels of ink, or one whose fill is obscured by dense text or shading, is correctly refused rather than guessed at. This is the majority of Fence entries.
- **Cities whose alignment check failed** (Mumbai, Mysuru) aren't in the app at all — a silent failure mode by design (fail closed, not a bad map shown as good).
- **Names.** 1:250,000 sheets rarely print a tank's own name. Most non-Bengaluru tanks are "Unnamed tank near `<place>`" — honest, but less satisfying than Bengaluru's named tanks. Occasionally the model reads a name that *is* printed on the sheet but assigns it as `nearest_place_as_printed` instead of `name_as_printed` for a nearby label (e.g. Hussain Sagar in Hyderabad) — the fallback naming still works, but it's a real reading gap, not a hidden one.
- **The one-time full-page reload on city switch.** Switching cities via the picker reloads the page with a new `?city=` param rather than an in-place camera fly-through — a scope trade-off for reliability under time pressure, not the originally imagined transition.
