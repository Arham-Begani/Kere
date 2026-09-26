# Build log

Honest, append-only record of what was built, when, and by whom. Two Claude Code sessions
worked this repo in parallel on 2026-09-25 evening; this file starts at the handoff point
between them.

## 2026-09-25, ~21:30–22:30 IST — kere-36 (Claude Code session), single-city build

Built per the original `CLAUDE.md`/`IDEA.md` spec (Bengaluru only):
- P0+P1: `pipeline/assemble.py`, `pipeline/export.py`, the MapLibre 3D app (`app/index.html`,
  `app/main.js`, `app/style.css`) — slider, camera presets, source cards, scoreboard, fence panel,
  search.
- P2: `pipeline/rain.py` (priority-flood depression filling on AWS Terrarium DEM tiles) and its UI
  drawer, explicitly labelled "not a flood prediction".
- Fixed the `ANTHROPIC_API_KEY` workspace-scoping issue that blocked model calls.
- Ran the real eval: `python eval/run_eval.py` — 102 calls, 2 models × 17 tiles × 3 runs, effort
  high, adaptive thinking, identical settings confirmed for both models. Cost: $1.74 (Opus 5) +
  $1.20 (Opus 5.5) = **$2.94 total**.
- Ran `eval/score.py`, re-ran `pipeline/assemble.py` and `pipeline/export.py` on the real results,
  re-ran `scripts/backtest.py` against the real Opus 5.5 tank layer. Stand-in banner (`demo_data.json
  .stand_in`) confirmed off.
- 18/18 tests green. Screenshots in `docs/screenshots/` (stadium 2026/1954, flood layer,
  scoreboard, fence, search, rain pooling).
- Committed and pushed to `origin/main` through `ad34b65`.

## 2026-09-25, 21:38 IST onward — kere-46 (this Claude Code session), "build 2" pivot

Given a second prompt: turn the one-time Bengaluru analysis into a multi-city product (city
picker, address search, downloads, live read, demo mode). `ListAgents` showed kere-36 active in
the same repo; coordinated directly with it (`SendMessage`) to avoid conflicting edits, then
confirmed with the user that build 2 supersedes and kere-36 could stand down. kere-36 had, by that
point, already finished and pushed the single-city work above cleanly — no conflict materialized.

Phase 0 audit (this session):
- `pip install -r requirements.txt`, `pytest -q` → 18/18 passed.
- `git grep -n "sk-ant-"` → only the placeholder in `README.md`'s usage snippet; no real key
  anywhere tracked. `.env` confirmed in `.gitignore`.
- Added `python-dotenv` to `requirements.txt` and a guarded `load_dotenv()` to
  `eval/run_eval.py` (only fires if `ANTHROPIC_API_KEY` isn't already in the environment) per the
  build-2 key-safety rule — needed because this session's shell didn't inherit the key kere-36's
  shell had.
- Verified both models' raw result files (`results/raw/<model>/*.json`, 51 each) used identical
  request settings (`effort: high`, adaptive thinking, `max_tokens: 16000`, `strict_tool: true`,
  zero dropped params) — confirms CLAUDE.md rule 7 held.
- Wrote `app/data/narrative.json`: applies the build-2 decision rule to the real scoreboard.
  Result: **`"gap": "clear"`**, decided by the front (1:250,000) sheet — Opus 5.5 invents 1.0
  phantom tanks/run vs Opus 5's 11.0 (ratio 0.091, ≤ 0.60 bar; means 10 pooled-SDs apart), and
  finds 90% of verified tanks vs 52%. On the plan (1:25,000) sheet the two models are
  statistically tied (18/18 tanks each, 88%/88% printed names, invented counts within 1 SD) — the
  narrative does not claim a plan-sheet gap that the data doesn't show. This matches the
  README table kere-36 had already written by hand.

## 2026-09-26, ~08:20-10:30 IST — kere-46, Phase 2: the multi-city pipeline

Built from nothing (this is the genuinely new work build-2 exists for):

- `scripts/georef.py`: generalized the Bangalore-front-sheet-specific bilinear model
  (`bilinear_lonlat_to_px`/`bilinear_px_to_lonlat`, any 4 corners + printed bounds) and added
  `find_sheet_neatline`, an automatic neatline-corner detector (dark-pixel-fraction line search
  per edge). Iterated through several failed approaches before this one worked reliably (a
  naive "longest dark run" locks onto AMS sheets' outer decorative border instead of the true
  neatline; scan-bed edge artifacts also had to be excluded). Verified by eye against overlay
  renders on all 6 candidate sheets before trusting it, then by an automated aspect-ratio/
  city-falls-inside-sheet test (`tests/test_cities_georef.py`).
- Downloaded and read, by eye, the 4 printed corner coordinates and the verbatim compilation
  note for 6 U502 sheets (Chennai/Madras ND 44-10, Hyderabad NE 44-9, Mumbai/Bombay NE 43-5,
  Pune/Poona NE 43-6, Mysuru/Mysore ND 43-16, Kolkata/Calcutta NF 45-7) from UT Austin PCL --
  `data/cities.json`. Kolkata's note says "Compiled in 1955", not 1954 -- recorded verbatim
  rather than assumed.
- `pipeline/cities.py`: download, window selection (city centre +/- window_deg, clipped to the
  sheet), 2x-upscaled tiling (`≤1000px`), OSM Overpass queries for today's water and named
  features (had to add multipolygon *relation* parsing -- large lakes like Hussain Sagar are
  very often mapped as relations, not ways, and were silently dropped before that fix), grow()
  assembly (front/blue-ink mode, consensus >=2-of-3 runs), alignment QA, and export.
- `pipeline/city_prompt.py` (`PROMPT_VERSION = "kere-city-v1"`, its own file, `eval/prompt.py`
  untouched) + `pipeline/read_city.py`: the actual Opus 5.5 reads, 3 runs, effort high, same
  strict-tool-choice fallback as `eval/run_eval.py`.
- Ran real reads for all 6 cities (~$2.95; combined with the Bengaluru eval, **total spend so
  far is $5.89 of the $40 budget**). Alignment QA (median offset of the 3 largest *named*
  non-canal OSM lakes to the nearest blue ink, vs 400 m) passed for **Chennai (37 m), Hyderabad
  (0 m), Pune (0 m), Kolkata (0 m)** -- all exported to `app/data/cities/<city>/`. **Mumbai
  (520 m) and Mysuru (493 m) failed and were dropped**, not shipped, per "ship 3 good cities
  rather than 6 doubtful ones." Mumbai's failure has an identified cause: this specific sheet's
  reachable window is mostly Arabian Sea and rural Raigad district (Mumbai's own famous lakes
  are on the next sheet north); the named "lakes" available to check alignment against there
  are mostly river segments. Mysuru's cause is less clear -- the neatline detection and general
  georef checked out visually, but 2 of 3 reference lakes had large offsets; worth another look
  if there's time, not chased further today.
- `tests/test_cities_pipeline.py`: consensus clustering on a fake result (no network/API needed)
  + structural checks on the real exported city files (corner order, required properties, the
  "Unnamed tank" naming fallback, `now_osm` always labelled "OpenStreetMap", QA actually passed
  for anything shipped, a failed-QA city never appears under `app/data/cities/`).
- `pytest -q`: 39 passed (was 18 at the start of this session).

Not yet done: city picker UI, address search, downloads, live server, demo mode, docs/deliverables
(Phases 3-6 of the build-2 prompt). Holding off on `app/index.html`/`app/main.js`/`app/style.css`
pending kere-36's check with their own user about running two sessions in one local working
directory (no shared remote anymore, so the original file-collision risk is gone, but a second
session editing the same files live is a separate, real risk).
