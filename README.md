# Kere

**The lakes Bengaluru forgot, read off a 1954 US Army map by Claude Opus 5.5.**

Built for the Bangalore Claude Opus Build Day (26 Sept 2026), Breakthrough track. Start with `IDEA.md` for the pitch and `CLAUDE.md` for the build spec. The test images are in `testset/`: you don't need to take any photos.

## Finding

Of 396 official flood points (KGIS/BBMP), **20% lie within 250 m of a lake the city lost, against 8% of random points (2.55×, p ≈ 1e-14)**. Near lakes it kept, the share is 13% against 17% (0.77×). To reproduce it: `python scripts/backtest.py --area gba`.

## Test the models tonight (about 10 minutes)

```bash
pip install -r requirements.txt
python scripts/build_testset.py          # regenerates the contrast-stretched plan (not shipped, 7 MB); ~20 s
pytest -q                                   # 6 tests: grower, georef, backtest finding, scorer
export ANTHROPIC_API_KEY=sk-ant-...
python eval/run_eval.py --runs 1 --tiles plan_r2c2 front_se   # 4 calls, check it works
python eval/run_eval.py                     # 2 models x 17 tiles x 3 runs
python eval/score.py                        # results/scoreboard.md + results/overlays/
```

**No API key?** Use `testset/quick_set/`. Upload each image to claude.ai with its `_prompt.txt`, in a new chat per image, once with Opus 5 and once with Opus 5.5. Save each reply to a file, then run:

```bash
python eval/add_manual.py --model claude-opus-5-5 --tile plan_r2c2 --file reply.txt
python eval/score.py
```

## Run the app

```bash
python pipeline/assemble.py --model claude-opus-5-5   # (or --results results_standin, see below)
python pipeline/assemble.py --model claude-opus-5
python pipeline/export.py                             # writes everything under app/data/
python -m http.server -d app 8000                      # http://localhost:8000
```

`assemble.py` turns saved model answers (`results/raw/<model>/*.json`) into georeferenced tank
outlines: it clusters points across tiles and runs, keeps a cluster only with 2-of-3-run
consensus, and grows the outline from the scan's own pixels (`pipeline/grow.py`) — never from a
model-drawn box. `export.py` builds everything else the static app reads: the sepia 1954 sheets,
crops, flood points, the search gazetteer, and the scoreboard/backtest numbers.

**No API key yet, or haven't run the eval?** `python scripts/make_standin_results.py` builds
`results_standin/` from the hand-traced answer key (perfect, by construction) so the whole
pipeline and app can be built and tested end to end before spending real API calls — run
`assemble.py --results results_standin` instead. The app then reads `app/data/demo_data.json`
and shows a red "DEMO DATA: answer key, not model output" banner automatically; nothing about the
real eval is faked. As soon as `results/scoreboard.json` exists, `export.py` switches to it and
the banner goes away on the next export — no app code changes needed.

![Kere: Shūle Tank at the Ashok Nagar football stadium, 1954 over 2026](docs/screenshots/b_stadium_1954_click.png)

## Scoreboard

The table below is regenerated from `app/data/scoreboard.json` every time `eval/score.py` runs.
**As shipped in this repo it reflects stand-in (answer-key) data for both model columns**, since
the real Opus 5 / Opus 5.5 eval hasn't completed here yet — see "Known issues" below. Once
`results/scoreboard.json` exists (`python eval/run_eval.py && python eval/score.py`), re-run
`pipeline/export.py` and this table becomes a real comparison.

| metric | Opus 5 | Opus 5.5 | Hand-traced |
|---|---|---|---|
| Plan: unique tanks found (of 18) | 18 | 18 | 18 |
| Plan: invented tanks per run | 0 | 0 | 0 |
| Plan: printed names read exactly | 100% | 100% | 100% |
| Plan: extent (box IoU) | 1.00 | 1.00 | 1.00 |
| Front: verified tanks found | 100% | 100% | 100% |

## Known issues

- **The real eval hasn't run in this environment.** The configured `ANTHROPIC_API_KEY` returns
  `This API key is not scoped to a workspace` on every call. Until a workspace-scoped key (or an
  `anthropic-workspace-id` header) is available, `app/data/` and the scoreboard above are built
  from `results_standin/` (the hand-traced answer key standing in for both models), and the app
  shows the red DEMO DATA banner accordingly.
- **`pipeline/grow.py`'s front-sheet resolution limit.** `grow.py`'s thresholds (`MIN_AREA=150`
  px, etc.) were tuned and validated only against the plan sheet (`tests/test_grow.py`). At the
  front sheet's native 1:250,000 scan resolution, several of the 16 known front tanks have under
  150 connected pixels of blue ink and are correctly refused as "too small" by the same,
  unmodified threshold — a real scan-resolution limit, not a bug, and not something we tuned
  (per CLAUDE.md, `grow.py`'s thresholds are frozen). These refusals show up honestly in the
  Fence panel. See `tests/test_assemble.py` for the exact accounting.

## How it works

```mermaid
flowchart LR
  A[1954 AMS sheet scans\nUT Austin PCL] --> B[17 tiles]
  B --> C[Opus 5 / Opus 5.5\npoint + box + printed name]
  C --> D[score.py vs hand-checked key]
  C --> E[grow.py: outline from scan pixels\nor refusal with reason]
  E --> F[georeference ±51 m] --> G[tanks GeoJSON\n+ MOD match, lost/surviving]
  G --> H[backtest vs city flood lists]
  G --> I[MapLibre 3D app\n1954 ↔ 2026 slider]
  D --> I
  H --> I
```

The model only points. The outline comes from the map's own pixels, and a point with no water drawn under it is refused and shown as refused.

## Credits

- US Army Map Service, Series U502, sheet ND 44-13 (public domain), from the Perry-Castañeda Library, UT Austin.
- MOD Foundation, *Building a Resilient Bengaluru* (water bodies), via github.com/soniadas123/bengaluru-water-map.
- KGIS / BBMP flood points via OpenCity (public domain).
- OpenFreeMap and OpenStreetMap contributors.
- AWS Terrain Tiles.
