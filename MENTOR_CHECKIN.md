## What did you build till now?

- Read a 1954 US Army map of Bengaluru with Claude Opus 5 and Opus 5.5, scored both against a hand-traced 18-tank answer key
- Real result: on the hard 1:250,000 sheet, Opus 5.5 gets 90% verified recall vs Opus 5's 52%, and invents 1 tank per run vs 11. On the easy 1:25,000 sheet both tie 18/18
- Pipeline never trusts a model box as geometry: grow.py grows every tank outline from the scan's own pixels, and any point the model finds that isn't real water is refused and shown, not hidden
- Backtest: official flood points sit within 250m of a lost lake 2.55x more often than random, and 0.77x as often near lakes the city kept
- Built the 3D map app: 1954/2026 slider, camera presets, source cards per tank, scoreboard panel, refusal ("fence") panel, search
- Generalized the georeferencing and pipeline to other cities, ran real reads on 6 more 1954 sheets, shipped 4 that passed alignment QA (Chennai, Hyderabad, Pune, Kolkata) with a city picker and GeoJSON/CSV downloads in the app; dropped 2 that failed QA (Mumbai, Mysuru) instead of shipping bad data
- Added a rain-pooling layer (today's terrain, not a flood prediction)
- 39 tests green, real API spend so far $5.89 of $40 budget
- Pushed the whole repo to GitHub so the team can pull it

## What are you planning to build next?

- Deploy the static app to GitHub Pages or Netlify
- Test the deployed link in a logged-out browser
- Record the 60 second backup demo video
- Freeze features and do a final README/screenshot pass
- If time allows, revisit why Mysuru failed alignment QA (Mumbai's failure is understood and not worth chasing further)

## How can mentors help you?

- Gut check on the pitch: is "scored Opus 5 vs 5.5 gap plus a real flood correlation" the right headline for judges, or should we lead differently
- Feedback on the 2 minute demo flow before we freeze at 15:10
- Quick opinion on GitHub Pages vs Netlify for a same-day deploy under time pressure
- Whether showing 4 cities strengthens or dilutes the "Bengaluru is the proof, this generalizes" story
