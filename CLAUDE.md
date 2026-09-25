# CLAUDE.md: Kere

Instructions for Claude Code working in this repo. Read this file fully before writing code. IDEA.md has the pitch; this file is the build spec.

## What we're building

Kere reads a 1954 US Army map of Bangalore with Claude Opus 5.5, rebuilds the lakes ("tanks") the city built over, and shows them in a 3D map with a 2026 ↔ 1954 slider. It overlays the city's official flood points and a scoreboard: Opus 5 vs Opus 5.5 vs a hand-traced answer key.

**Headline finding** (reproduce with `python scripts/backtest.py --area gba`): official flood points lie within 250 m of a *lost* lake 2.55× more often than random points, and within 250 m of a *surviving* lake 0.77× as often.

**Event constraint:** code sprints run 11:45–13:00 and 14:30–15:30 IST, Sat 26 Sept 2026. Final submission is 15:30, and demos are 2 minutes. **Freeze features at 15:10.**

## Rules. These are the product; never break them.

1. **The model points; the pixels draw.** Model output is a point plus a box. Tank geometry only ever comes from `pipeline/grow.py` run on the scan. Never turn a model box or a model-drawn polygon into map geometry.
2. **Refusals are shown.** Every point `grow()` refuses goes to `refused_<model>.json` and appears in the app's Fence panel, with its reason and crop. Don't filter them out quietly.
3. **Names are sourced.** Show a tank name only if (a) it's `name_as_printed` from the model *and* the label is visible in the tank's crop, or (b) it comes from MOD's record by spatial match, labelled "MOD Foundation". Never show a name from model memory.
4. **Every number on screen is computed from a file in the repo** (`results/scoreboard.json`, `data/backtest*.json`, the GeoJSON files). No hard-coded statistics in the UI.
5. **Dates:** the plan is "on the 1954 compilation". The front sheet is "Survey of India 1945–46". Never say a lake held water in a given year.
6. **Never predict flooding for an address.** Show the distance to the nearest 1954 tank, what stands there now (MOD `current_use`), and the crop.
7. **The eval is frozen once results exist.** If `eval/prompt.py` changes, bump `PROMPT_VERSION` and re-run both models. Both models always get the same prompt, effort and settings. `score.py` warns if they didn't.
8. **Credit sources in the app footer:** US Army Map Service via UT Austin PCL (public domain), MOD Foundation (Building a Resilient Bengaluru, via soniadas123/bengaluru-water-map), KGIS/BBMP flood lists via OpenCity, OpenFreeMap / OpenStreetMap contributors, AWS Terrain Tiles.

## What already exists (built 25 Sept, research and evaluation; all tests pass)

| Path | What | Status |
|---|---|---|
| `data/raw/nd-44-13a_front_250k.jpg`, `nd-44-13b_plan_25k.jpg` | The two scans (5000 px wide) | ✓ |
| `data/raw/plan_25k_autocontrast.png` | The plan with contrast stretched. Everything uses this, never the faded raw scan | ✓ |
| `data/mod/*.geojson` | MOD layers: `lakes_lost` (111), `lakes_existing` (205), drains, wards, `gba_boundary` | ✓ |
| `data/flood/*.kml` | Flood points: KGIS vulnerable (200), flood-prone (70), BBMP low-lying (128) | ✓ |
| `data/flood_pins.geojson` | 7 news-reported flooded localities (2026-09-21 and 2022-09), with source URLs | ✓ |
| `data/plan_tanks.geojson` | The 18 tanks on the 1954 plan (answer key), georeferenced, with MOD match | ✓ |
| `data/plan_georef.json` | Plan affine (lon/lat → px), 6 GCPs, RMS 12.7 px ≈ 51 m | ✓ |
| `scripts/georef.py` | Front sheet: bilinear from printed corners (77.5–79.0 E, 12–13 N). Plan: affine helpers | ✓ tested |
| `scripts/build_testset.py` | Rebuilds tiles and keys from scratch (reproducible) | ✓ |
| `scripts/backtest.py` | Flood-point lift for lost vs surviving tanks. Takes any tank GeoJSON (`--tanks`, `--area plan/front/gba`) | ✓ tested |
| `scripts/fetch_sources.sh` | Re-downloads every source | ✓ |
| `testset/` | 17 tiles, keys, answer overlays, manual prompts, quick set. See `testset/README.md` | ✓ |
| `eval/prompt.py` | The prompt and strict tool `report_tanks` (point, bbox, name_as_printed, style, partial). `PROMPT_VERSION = kere-tanks-v2` | frozen |
| `eval/run_eval.py` | Runs both models (default 3 runs, effort high, adaptive thinking), saves raw responses, resumable | ✓ mock-tested |
| `eval/score.py` | Deterministic scoring → `results/scoreboard.{json,md}` plus overlays in `results/overlays/<model>/` | ✓ self-tested |
| `eval/add_manual.py` | Scores answers pasted from claude.ai (no API key needed) | ✓ |
| `pipeline/grow.py` | Point + box → outline from pixels, or a refusal with a reason. Gabor hatch detector + dark-fill test | ✓ mean IoU ≥ 0.72 vs key, refuses reservoir/text/racecourse/built-up |
| `tests/` | `pytest -q`: grow, georef, backtest finding, scorer self-test (6 tests, ~25 s) | ✓ 6 passed |

## Commands

```bash
pip install -r requirements.txt           # python 3.11
python scripts/build_testset.py           # first run only: regenerates data/raw/plan_25k_autocontrast.png (identical keys)
pytest -q                                 # must stay green; run before every commit
export ANTHROPIC_API_KEY=...
python eval/run_eval.py --runs 1 --tiles plan_r2c2 front_se   # smoke test, 4 calls
python eval/run_eval.py                   # full: 2 models x 17 tiles x 3 runs = 102 calls, roughly $6-20
python eval/score.py                      # -> results/scoreboard.md, results/overlays/
python scripts/backtest.py --area plan    # answer-key tanks vs flood points
python -m http.server -d app 8000         # serve the app
```

## Architecture

```
scans (UT Austin) --tiles--> eval/run_eval.py --> results/raw/<model>/<tile>__runN.json
                                              \--> eval/score.py --> results/scoreboard.json + overlays
results/raw --> pipeline/assemble.py --(grow.py on the scan, georef)--> app/data/tanks_<model>.geojson
                                                                    \--> app/data/refused_<model>.json
scans --> pipeline/export.py --> app/data/plan_1954.jpg + corners, front_1954.jpg + corners, crops/<id>.jpg
data/flood/*.kml + flood_pins --> pipeline/export.py --> app/data/flood_points.geojson, gazetteer.json
app/data/tanks_claude-opus-5-5.geojson --> scripts/backtest.py --> app/data/backtest.json
app/ (static: index.html + main.js + style.css, MapLibre GL JS 5 from jsDelivr) reads only app/data/*
```

The app is a static site: no server, no API key, and nothing the judge has to log in to. Deploy it to GitHub Pages or Netlify drop.

## Build plan (event day). Do these in order and don't start P1 until P0 passes.

**Tonight, already allowed as evidence gathering:** run the full eval, `score.py`, and commit `results/`. Look at `results/overlays/*/plan_r2c2__run1.jpg` for both models.

### P0 (Sprint 1, 11:45–13:00): data for the app and a map that shows it

1. **`pipeline/assemble.py --model claude-opus-5-5` (and the same for `claude-opus-5`)**
   - For every result file, convert each predicted point and box from tile px to sheet px: `sheet = origin_in_sheet_px + tile_px / scale_in_sheet` (from the tile's key).
   - Cluster points per sheet across overlapping tiles and runs. Plan radius 45 px (~180 m); front radius 6 px in sheet px (~225 m), which is `front_se` px / 2.
   - Keep a cluster only if it appears in ≥ 2 of the 3 runs (consensus). Take the median point and median box. The name is the majority `name_as_printed`, using only runs where the tank's label falls inside that tile.
   - Run `grow(sheet_img, x, y, kind, bbox)`. The plan uses `data/raw/plan_25k_autocontrast.png` (greyscale); the front uses the raw colour scan (BGR). A refusal goes to `refused_<model>.json` as `{point_lonlat, tile, runs, reason}`.
   - Georeference each outline. Plan: invert the affine in `data/plan_georef.json` (`lonlat = solve(A[:2].T, px - A[2])`). Front: `scripts/georef.front_px_to_lonlat`.
   - Match to MOD by overlap (≥ 0.2 of the smaller area), exactly as `build_testset.py` does. Set `status`: surviving if ≥ 20% of the outline overlaps `lakes_existing`, else lost. Set `redated`: true if MOD `last_mapped` is 1854/1870/1897 and the tank is on the plan.
   - Write `app/data/tanks_<model>.geojson`. Properties: `id, sheet, name_as_printed, mod_name, mod_last_mapped, mod_current_use, status, redated, runs_found, tiles, crop, area_m2`.
   - **Check:** assembling the answer key's inside points gives 17–18 plan tanks. Add a test: `tests/test_assemble.py` feeds a fake result built from the key and expects ≥ 17 accepted and 0 refused.
2. **`pipeline/export.py`**
   - `plan_1954.jpg`: the plan's map area `(915,213)-(4105,3390)` from the autocontrast PNG, tinted sepia (multiply toward #704214 at about 35%), JPEG quality 82, ~2400 px wide. Corners are the 4 crop corners through the inverse affine, ordered TL, TR, BR, BL for MapLibre.
   - `front_1954.jpg`: the front window `(463,275)-(1400,760)` (77.50–77.84 E, 12.83–13.00 N; inside the neatline), unmodified colour. Corners come from `front_px_to_lonlat`.
   - `crops/<tank_id>.jpg`: each tank's bbox + 40 px from its sheet, max 480 px.
   - `flood_points.geojson`: the 3 KML lists with `list` and `name` properties, plus the news pins with `source` URLs.
   - `gazetteer.json`: localities for search, taken from flood-point names, MOD ward names and news pins, as `{name, lon, lat}`. This means no geocoding calls during the demo.
   - Copy `results/scoreboard.json` and 2 overlay tiles per model (`plan_r2c2`, `plan_r1c1`) to `app/data/`.
3. **`app/` skeleton**
   - MapLibre GL JS 5 (`https://cdn.jsdelivr.net/npm/maplibre-gl@5/dist/maplibre-gl.js`, plus its CSS). Style: `https://tiles.openfreemap.org/styles/liberty`. It has a `building-3d` fill-extrusion layer on `render_height` from zoom 14.
   - Terrain: raster-dem source `https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png` with `encoding: "terrarium"`, `tileSize: 256`, `maxzoom: 15`, and `map.setTerrain({source, exaggeration: 4})`. Bengaluru is flat (870–920 m), so exaggerate.
   - Image sources for `plan_1954.jpg` and `front_1954.jpg`, as raster layers above the land and below the buildings.
   - `tanks` GeoJSON: a fill (water `#2f6f9f`), a 2 px outline, and labels from `name_as_printed` in italic serif. Lost tanks are dashed; surviving ones are solid.
   - **Slider (0 = 2026, 1 = 1954), one input:** overlay `raster-opacity = t`; `building-3d` `fill-extrusion-height = ["*", ["get","render_height"], 1 - t]`; tank `fill-opacity = 0.15 + 0.7*t`; basemap label opacity `1 - 0.8*t`.
   - Camera presets as buttons: **Stadium** (Ashok Nagar, on Shūle Tank: 77.6117, 12.9686, z16.5, pitch 60, bearing -20), **City** (77.60, 12.97, z12.3, pitch 45), **HSR** (77.6389, 12.9116, z15, pitch 55).
   - **P0 check:** open the app, press Stadium, and drag the slider. The stadium's buildings sink, Shūle Tank appears under them, and the sepia sheet lines up with the roads (within ~50 m).

### P1 (Sprint 2, 14:30–15:10): the story and the proof

4. **Source card** (click a tank): the crop, the name as printed ("printed on the 1954 sheet") or the MOD name ("MOD Foundation record"), status, "last surveyed by MOD: 1870, still drawn on the 1954 compilation" when `redated`, what's there now, and "aligned ±51 m using 6 tanks".
5. **Flood layer:** circles coloured by list, and news pins pulsing (CSS marker) with a link. There's a toggle, and the legend states the backtest from `app/data/backtest.json`, e.g. "20% of 396 flood points are within 250 m of a lost lake vs 8% of random points; surviving lakes 13% vs 17%".
6. **Scoreboard panel:** reads `scoreboard.json`. Rows are tanks found (of 18), invented per run, printed names exact, unsourced names, box IoU, and colour-sheet recall. Columns are Opus 5, Opus 5.5 and Hand-traced. Below it, the two overlay tiles side by side (red X = invented, green = hit).
7. **Search:** a text input with a `gazetteer.json` prefix match. Fly to the match and show the nearest tank (turf-free: compute distance in JS with an equirectangular approximation) with its distance and card.
8. **Fence panel:** a count and list of refused points with reason and crop. The header reads "The model pointed here. The map says no."
9. `python scripts/backtest.py --tanks app/data/tanks_claude-opus-5-5.geojson --label "Opus 5.5 reading" --area plan --out app/data/backtest.json` powers the legend numbers.

### P2 (only if P1 is done by 14:55)

- **Rain:** get a DEM mosaic for the study box from the same Terrarium tiles (z14), run priority-flood depression filling (numpy + heapq), and save the depth as a PNG plus bounds. In the app, use a MapLibre `canvas` source that thresholds depth over 3 s. Label it "where water would pool on today's terrain", never "flood prediction".
- **Another city:** Madras (ND 44-10 a/b) through the same pipeline. Show it only if the tanks look right by eye.

### Freeze (15:10–15:30)

`pytest -q`, a README screenshot, deploy, test the deployed link in a logged-out browser, record the 60 s backup video, and submit.

## Visual design (one look, chosen)

- Dusk: MapLibre `sky`/fog with a warm horizon and cool zenith. The 1954 layers are sepia paper; water is `#2f6f9f` at 0.85; flood points are `#e4572e`.
- Type: tank names in an italic serif (Google Fonts "IM Fell English" or "EB Garamond" italic), echoing the map's own lettering. UI in Inter.
- A single bottom bar holds the year slider (big "1954" / "2026" labels at the ends), camera presets and search. Panels (card, scoreboard, fence) are right-side drawers. No dashboard grid.
- The first screen says in one line what this is: "The lakes Bengaluru forgot, read off a 1954 map by Claude Opus 5.5."

## Model and API notes

- IDs are `claude-opus-5` (the last model) and `claude-opus-5-5` (released 22 Sept 2026).
- **Opus 5.5 thinking is always on and can't be disabled.** Control it with `output_config.effort`. The default is `medium` on 5.5 and `high` on 5, so always set `effort` explicitly and identically.
- **Opus 5.5 rejects forced `tool_choice`** (`any` or `tool`). Use `tool_choice: {"type": "auto"}` with `strict: true` on the tool. `run_eval.py` does this and falls back if a param is refused, recording the change in `request.dropped_params`.
- On 5.5, notes between tool calls arrive as thinking blocks. That's irrelevant here because we make a single call.
- Tiles are ≤ 1000 px so no API-side resizing happens. The model also reports the image size it saw, and the scorer rescales if needed.

## Testing rules

- `pytest -q` stays green. Add a test with every pipeline module: `test_assemble.py` (fake result → tanks), `test_export.py` (corner order TL, TR, BR, BL; image files exist; GeoJSON parses).
- Never tune `grow.py` thresholds on the tiles you report scores for without saying so. The current thresholds were set on the answer key on 25 Sept and are documented in the file.
- The self-test (`eval/selftest.py`) proves the scorer. Keep it passing if you touch `score.py`.

## Don't

- Don't add a chat box, login, database or backend.
- Don't call the API from the browser, and don't commit `ANTHROPIC_API_KEY`.
- Don't use Nominatim during the demo (use the gazetteer). If you geocode at build time, 1 request per second with a generic User-Agent, never a personal email.
- Don't restyle the whole UI after 14:55.
- Don't claim what the data doesn't show. If the Opus 5 vs 5.5 gap is small, the scoreboard shows that and the pitch says so.
