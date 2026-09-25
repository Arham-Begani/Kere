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

Next: Phase 2 (multi-city pipeline) — this is genuinely new work, nothing existed for it yet.
