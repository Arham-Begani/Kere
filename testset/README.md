# Kere test set: can the model read a 1954 map?

17 image tiles cut from two scans of one US Army Map Service sheet, each with a hand-checked answer key. You don't need to take any photos: every image is already here.

| Sheet | Tiles | What's on it | Key |
|---|---|---|---|
| **City plan**, "Bangalore and Vicinity", 1:25,000, greyscale (back of sheet ND 44-13) | 16 tiles, `plan_r{row}c{col}.png`, 1000×1000 px, 4 m per px, overlapping by ~270 px | 18 tanks, 6 with printed names (Dharmāmbudhi, Halsūr, Agrahār, Kempāmbudhi, Shūle, Mud Tank), 2 service reservoirs, racecourse, parade grounds, quarries, cemeteries | Complete: every tank on the plan, outlined from its pixels and checked by eye |
| **Front sheet**, 1:250,000 colour (ND 44-13), compiled 1954 from Survey of India 1945–46 | 1 tile, `front_se.png`, 990×676 px (2× enlargement of 77.60–77.78 E, 12.88–13.00 N) | Koramangala → Bellandur → Varthur. Dozens of blue-hatched tanks | Partial: 16 tanks verified against MOD Foundation records. Other detections are checked with a blue-ink test |

## Files

- `tiles/`: the images you send to the model (identical for both models).
- `keys/<tile>.json`: the answer for each tile, with each tank's outline, a guaranteed-inside point, its status (`full`, or `partial` when cut by the tile edge), the name printed on this tile (if any), and the MOD Foundation match (name, lost or existing, last survey year, what stands there now).
- `answer_overlays/`: every tile with its key drawn on it. Look at these before you trust the key.
- `manual/<tile>_prompt.txt`: the prompt to paste into claude.ai if you test by hand (it asks for JSON instead of a tool call).
- `quick_set/`: 6 tiles plus their prompts for a 12-chat manual test. See `QUICK_SET.jpg`.
  1. `plan_r2c2`: Shūle Tank (now the Ashok Nagar football stadium) and Mud Tank (now the hockey stadium)
  2. `plan_r2c0`: Agrahār and Kempāmbudhi, plus two unlabelled tanks
  3. `plan_r1c1`: Dharmāmbudhi (now the Majestic bus stand), plus traps: two "Reservoir" buildings and a racecourse
  4. `plan_r2c3`: Chelgatta (now the KGA golf course), Kodihalli and a crescent tank
  5. `plan_r0c3`: **no tanks at all.** Any tank reported here is invented
  6. `front_se`: the colour sheet, Bellandur and Varthur

## How it's scored (`eval/score.py`)

- **Hit:** the model's point falls inside a key tank's outline, grown by 15 px (14 px on the front tile).
- **Invented:** the point isn't on any tank, reservoir or (front tile only) blue ink.
- **Recall** counts full tanks only, so a tank cut by the tile edge is a bonus if found and no penalty if missed.
- **Names:** exact match after removing accents, case and a trailing "Tank". A name given for a tank whose label isn't on the tile counts as **unsourced**: it came from memory, not from the map.
- **Extent:** IoU between the model's box and the key tank's box.
- **Unique tanks found (of 18)** is the headline plan number. A tank counts if it's found in any tile where it is complete.

## How the key was made (`scripts/build_testset.py`, reproducible)

1. **Plan tanks.** Each tank was boxed by hand. Its outline was traced from the scan's own pixels (dark fill or hatch texture), then every outline was checked by eye.
2. **Georeferencing the plan.** An affine fit to 6 tanks that are unambiguous on both the plan and MOD's layer. RMS error is 12.7 px, about 51 m.
3. **Matching to MOD.** Each tank is matched to MOD Foundation's hand-traced layer by overlap. 17 of 18 match. The unmatched one, P04, is a 0.3 ha pond.
4. **Front sheet.** Georeferenced from its printed corner coordinates. A MOD tank enters the key only if its outline sits on blue ink. Four false positives found by eye were removed: a grid line, the grid number "1", a grid crossing, and a text label.

## Sources and licences

- **Maps:** US Army Map Service, Series U502, sheet ND 44-13 (compiled 1954, first printing 1959). US Government work, public domain. Scans from the Perry-Castañeda Library Map Collection, University of Texas at Austin.
- **Water bodies:** MOD Foundation, *Building a Resilient Bengaluru*, via github.com/soniadas123/bengaluru-water-map (snapshot of 23 May 2026). Credit them wherever their data appears.
- **Flood points:** KGIS flood-vulnerable locations, flood-prone locations and BBMP low-lying areas, from data.opencity.in (public domain).
- **News pins** are geocoded with Nominatim (© OpenStreetMap contributors, ODbL).
