# Kere: Bengaluru floods where it lost its lakes, not where it kept them

**Event:** Bangalore Claude Opus Build Day, Sat 26 Sept 2026, Anakin. **Track:** Breakthrough ("bring a problem the last model couldn't handle, and see how far this one gets"). **Kere** (ಕೆರೆ) is Kannada for lake or tank.

**One line:** Claude Opus 5.5 reads a 1954 US Army map of Bangalore, rebuilds the lakes the city built over, and shows that the city's own flood list clusters on those lost lakes. It is scored against Opus 5 and against a map traced by hand.

> The name was "Kere '46" in the chat. It changed because the front sheet is from 1945–46 surveys but the city plan doesn't state its sources. Everything here says "on the 1954 compilation" and nothing older.

---

## 1. The claim (already checked, reproducible with `python scripts/backtest.py`)

**The city's official flood-point lists** (396 points inside the GBA boundary: KGIS flood-vulnerable, flood-prone, and BBMP low-lying, via OpenCity):

| Within 250 m of… | Flood points | Random points | Lift | p (one-sided) |
|---|---|---|---|---|
| a **lost** lake (MOD Foundation's hand-traced layer) | **20%** (80/396) | 8% | **2.55×** | 1e-14 |
| a **surviving** lake | 13% (52/396) | 17% | **0.77×** | 0.99 |

**In the city core, using the tanks drawn on the 1954 plan itself** (answer key, 163 flood points):

| Within 250 m of… | Flood points | Random points | Lift | p |
|---|---|---|---|---|
| a 1954 tank that is **gone today** | 12% (19/163) | 6% | **1.9×** | 0.005 |
| a 1954 tank that **still exists** | 2% (4/163) | 3% | 0.87× | 0.68 |

**What this means for the pitch.** Flooding isn't about lakes in general. Lakes that still exist hold water. The places that flood are the ones that forgot a lake was there. The lost/surviving contrast is the insight, and a smart person could disagree with it; that is why it's worth showing.

**What it does not mean:** that a given house will flood. The app never says that.

## 2. Why this is a Breakthrough entry

To get Bengaluru's lost-lake layer, MOD Foundation's team traced 111 lost water bodies by hand from surveys dated 1854–1969. Most Indian cities have no such layer. The US Army Map Service mapped all of India at 1:250,000 around 1954, with city plans on the back of many sheets: Madras, Hyderabad, Bombay, Poona and Mysore are all on the same series. If a model can read those sheets well enough, every city can have this layer.

Opus 5.5's own release notes name the skill this needs: "sharper reading of charts, diagrams, and screenshots … meaning that depends on where things are in the image." Which blob of hatching is a tank, which printed name belongs to which blob, and which dark square is a reservoir building rather than water: all of it is layout.

**The test** (`eval/`): 17 map tiles, both models, same prompt, same effort, 3 runs each, scored against a hand-checked answer key. See section 5.

## 3. Who it's for

**A family in HSR Layout whose street went under on 20–21 Sept 2026** (Deccan Herald). MOD's record says HSR Layout was built on Parangipalya Kere. They have never heard of it. The only record of where the water used to sit is a military map they can't read or line up with today's streets.

The second audience is the city itself. The flood list is theirs, and so is the lost-lake record. Kere joins the two, and it does the same for cities that have no lost-lake record at all.

**Edge:** you play football in Karnataka. The 1954 plan labels "Shūle Tank" exactly where the Ashok Nagar football stadium stands now. The demo opens there. If you've played at that ground, say so in the first ten seconds.

## 4. Already found (verified 25 Sept 2026, in `data/plan_tanks.geojson`)

The 1954 city plan shows **18 tanks**. **13 are gone** and 4 survive (Sankey, Ulsoor, Kempambudhi, Kadiranpalya). The 18th, P04, is a 0.3 ha pond with no MOD record.

**Eight tanks** that MOD's record last shows on an 1870 or 1897 survey are **still drawn on the 1954 compilation.** Here is each one with what MOD says stands there now:

| On the 1954 plan | MOD name (last surveyed) | There now (MOD) |
|---|---|---|
| **Shūle Tank** | Shoolay Tank (1870) | **Ashok Nagar Football Stadium** |
| **Mud Tank** | Akkitimmanahalli tank (1870) | **Karnataka State Hockey Stadium** |
| **Dharmāmbudhi Tank** | Dharmambudh Tank (1870) | **Majestic bus stand** |
| unlabelled | Koramangala Kere (1870) | National Dairy Research Institute |
| unlabelled | Jakraya lake (1870) | Krishna Flour Mills |
| unlabelled | Miller's Tank (1897) | residential and commercial layouts |
| unlabelled | Agasana Tank (1897) | Mariyappana Palya Park |
| unlabelled | Sonnenahalli lake (1870), lower-confidence match (overlap 0.37) | Austin Town |

**Say it this way:** "still drawn in 1954." Don't say "still held water in 1954." A 1954 map can copy older sources.

**Also say** that three of Bengaluru's sports grounds (football, hockey, and the KGA golf course on Chelgatta Tank) sit on 1954 tanks.

## 5. The numbers to show (fill in tonight from `results/scoreboard.md`)

| | Opus 5 | Opus 5.5 | Hand-traced (MOD / key) |
|---|---|---|---|
| Tanks found on the 1954 plan (of 18) | … | … | 18 |
| Invented tanks per run (16 tiles) | … | … | 0 |
| Printed names read exactly (6 labels) | … | … | 6 |
| Names given that aren't printed on the map | … | … | 0 |
| Extent accuracy (box IoU) | … | … | 1.0 |
| Colour sheet: verified tanks found (of 16) | … | … | 16 |
| Flood lift near lost tanks it read (core) | … | … | 1.9× |

**The Breakthrough sentence:** "Opus 5 found X of 18 and invented Y. Opus 5.5 found Z and invented W." If Opus 5.5 is *not* better, say that on stage instead; "see how far this one gets" is the brief. Then fall back on the claim in section 1, which doesn't depend on the comparison.

## 6. The fence (what the model is never allowed to do, shown on screen)

1. **The model only points.** It gives a point and a box. The outline is traced from the scan's own pixels (`pipeline/grow.py`). A point with no hatching or dark water fill under it is **refused**, and the refusal is listed on screen with its reason. Examples: "no hatching and not dark enough for a water fill", or "small and not a solid fill: could be text or a building". Tests prove it refuses the "Reservoir" buildings, the racecourse, dark built-up shading and the label "Mud Tank" (`tests/test_grow.py`).
2. **Names are sourced.** A name appears only if it's printed on the sheet (with the crop to prove it) or comes from MOD's record by location (credited). Names from the model's memory are counted as a failure ("unsourced") on the scoreboard.
3. **Lost or surviving is computed, not claimed:** at least 20% overlap with MOD's existing-lakes layer.
4. **Every number on screen is computed from files in the repo.** The two stadium facts are MOD's `current_use` field, shown with credit.
5. **It never predicts flooding for an address.** It shows distance to the nearest 1954 tank, what stands there now, and the sheet crop.

## 7. Demo script (2 minutes, rehearse it to 1:50)

| Time | On screen | Say |
|---|---|---|
| 0:00 | 3D map at dusk, Ashok Nagar stadium, 2026 | "This is the Ashok Nagar football stadium. [I've played here.] In 1954 it was a lake." |
| 0:12 | Drag the slider to 1954: buildings sink, the sepia 1954 sheet drapes over the terrain, Shūle Tank fills blue, the source card shows the crop with "Shūle Tank" printed | "That's the US Army's 1954 map. Claude read it: Opus 5.5, released four days ago." |
| 0:30 | Pull back over the city: 18 tanks, 13 marked gone, flood points appear | "The city publishes 396 places that flood. They sit next to lakes Bengaluru *lost*, 2.5 times more than chance, and *not* next to the ones it kept." |
| 0:55 | **Hand the laptop to the judge:** "type your neighbourhood" | Camera flies there and shows the nearest 1954 tank, its distance, what stands there now, and the crop |
| 1:20 | Scoreboard: Opus 5 vs Opus 5.5 vs hand-traced, with a tile overlay (red X = invented) | "Same map, same prompt. The last model found X and invented Y. This one found Z." |
| 1:40 | Fence panel: refused points | "When it points at a building, the pixels say no, and we show you." |
| 1:50 | End card | "Every Indian city was mapped this way in 1954. Bengaluru is the one we could check." |

**Backup:** a 60-second screen recording of the same flow, recorded by 15:15.

## 8. The 11:30 idea checkpoint (say it in 20 seconds)

"Kere: Claude reads a 1954 US Army map of Bangalore and rebuilds the lakes the city built over. The city's own flood list clusters 2.5× on lost lakes and not at all on surviving ones. We score Opus 5.5 against Opus 5 and against a map traced by hand. It opens on the football stadium that was Shūle Tank."

**Team you need (ask at 10:45):** one person on the map UI (MapLibre). You run the data and the scoreboard.

## 9. Risks and what to do about them

| Risk | Move |
|---|---|
| Opus 5.5 isn't better than Opus 5 on the tiles | Run the eval **tonight**. If there's no gap, lead with the flood claim and the fence, and say the result honestly: "it got this far." |
| The 3D map eats the clock | Build order in CLAUDE.md: the scoreboard and tank layer come first, 3D second. Fallback: 2D with the sepia overlay and the slider. |
| Georeferencing looks off on screen | The RMS error is ~51 m on the plan. Show it in the source card: "aligned ±51 m using 6 tanks." |
| A judge asks "didn't MOD already do this?" | "For Bengaluru, by hand, and it's our answer key. The model is how every other city gets one." MOD's layer also can't date when a lake disappeared; the 1954 sheet adds a dated observation for 8 of them. |
| Venue Wi-Fi | Map tiles need the network. Pre-cache by opening the demo route once, and keep the recorded video. |
| "Does it predict floods?" | No. It measures distance to where water used to be, and the flood list is the city's own. |

**Cut:** first-person walking, drains, other cities (a stretch only: same pipeline, sheets listed in `scripts/fetch_sources.sh`), accounts, live model calls during the demo (results are precomputed and shown with their run IDs).

## 10. Sources (all public)

- US Army Map Service, Series U502, sheet ND 44-13 "Bangalore" (compiled 1954 from Survey of India 1945–46; first printing 1959), and the verso city plan "Bangalore and Vicinity" 1:25,000. Public domain. Scans from UT Austin, Perry-Castañeda Library: maps.lib.utexas.edu/maps/ams/india/
- MOD Foundation, *Building a Resilient Bengaluru*: existing and lost water bodies, via github.com/soniadas123/bengaluru-water-map (snapshot of 23 May 2026)
- Flood points: KGIS / BBMP via data.opencity.in (public domain)
- News: Deccan Herald, 21 Sept 2026 (waterlogging at Bellandur, Whitefield, HSR Layout, Panathur); Newslaundry, 13 Sept 2022 (Marathahalli, Yemalur, Devarabeesanahalli)
- Opus 5.5 capabilities: anthropic.com/claude-opus-5-5 and platform.claude.com/docs/en/models/opus-5-5/whats-new-opus-5-5
- The bar: the Opus 4.8 Build Day winners, Tekton (sourced reconstruction) and Sim Francisco (backtest on a known outcome)
