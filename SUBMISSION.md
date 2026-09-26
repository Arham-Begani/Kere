What is your project?

https://github.com/Arham-Begani/Kere

Kere (ಕೆರೆ, Kannada for "lake") shows where Bengaluru's lost lakes used to be, and that the city floods where it built over them.

Claude Opus 5.5 reads a 1954 US Army Map Service sheet of Bangalore, finds the tanks (lakes) printed on it, and rebuilds them on a 3D map of today's city. A slider takes you between 2026 and 1954: the buildings sink and the old lakes come up underneath. At Ashok Nagar, the football stadium sits on "Shūle Tank". The hockey stadium sits on Mud Tank, and the Majestic bus stand on Dharmāmbudhi Tank.

On top of that, the app shows the city's own official flood points (KGIS/BBMP, 396 points). The result: flood points lie within 250 m of a lost lake 2.55x more often than random points (p ≈ 1e-14), and within 250 m of a surviving lake only 0.77x as often. Lakes the city kept still hold water. The places that flood are the ones that forgot a lake was there.

It's for people like the family in HSR Layout whose street flooded on 20–21 Sept 2026. Their neighbourhood was built on Parangipalya Kere, and the only record of that is a military map they can't read or line up with today's streets. It's also for city planners, who own both the flood list and the lost-lake record but have never had the two joined.

The problem it solves: MOD Foundation traced Bengaluru's 111 lost lakes by hand, and most Indian cities have no such layer at all. The US Army mapped all of India around 1954, with city plans for Madras, Hyderabad, Bombay, Poona and more. If a model can read those sheets reliably, every city can get this layer. Kere already runs the same pipeline on Chennai, Hyderabad, Pune and Kolkata. Two cities, Mumbai and Mysuru, failed alignment QA, so we left them out rather than ship bad data.

It's a static site with no login, no backend and no API key. It never predicts flooding for an address. It shows the distance to the nearest 1954 tank, what stands there now, and the original map crop so you can check for yourself.


How did Claude contribute?

Claude did two jobs here: it's the thing being tested, and it built most of the project with us.

Claude Opus 5.5 reads the map. For each map tile the model returns a point and a box for every lake, plus the name exactly as printed. We never use a box the model draws as geometry. A pixel-based grower traces each lake outline from the scan's own hatching. When the model points at something that isn't water (a reservoir building, text, a racecourse), the grower refuses it, and the app shows that refusal in a "Fence" panel instead of hiding it. Names only appear if they're actually printed on the map or come from MOD's record, never from model memory.

We scored Opus 5.5 against Opus 5 and a hand-traced answer key, using the same prompt and the same effort, over 17 tiles x 3 runs each. On the hard 1:250,000 colour sheet, Opus 5.5 found 90% of the verified lakes vs 52% for Opus 5, and invented 1 lake per run vs 11. On the easy 1:25,000 city plan both models tied at 18/18 lakes. Opus 5.5 drew much tighter extents (box IoU 86% vs 69%), and Opus 5 invented slightly fewer lakes per run (3.7 vs 4.0), which we show honestly on the scoreboard. Opus 5.5 was also cheaper ($1.20 vs $1.74 for all runs) and faster (9.8 s vs 14.2 s per call).

Claude Code (Opus 5.5) built it with us: the georeferencing, the clustering and consensus pipeline, the flood backtest, the MapLibre 3D app with the 1954/2026 slider, the multi-city pipeline, a rain-pooling layer, and 39 tests. Total real API spend for the evaluation was under $6.

Models used: Claude Opus 5.5 (claude-opus-5-5) for reading the maps and in Claude Code, and Claude Opus 5 (claude-opus-5) as the baseline for comparison.


Did you build using Anakin?

[A or B]


What's your biggest takeaway from today?

The newer model didn't win everywhere. On the easy map, Opus 5 and Opus 5.5 tied. The gap only showed up on the hard, faded 1:250,000 sheet, where 5.5 found almost twice as many real lakes and invented a tenth as many fake ones. You only see a breakthrough if you test on a problem hard enough to break the old model.


What would you tell someone who's never tried this?

Build the answer key before you build the app. We hand-traced 18 lakes the night before, and that one file let us score two models, test every piece of the pipeline, and say exactly what the model got right and wrong. And never let the model's output go straight onto the screen. Make something else check it, and show what got rejected.


Anything else you want to tell us about your project?

The inspiration was a football ground. The 1954 plan labels "Shūle Tank" exactly where the Ashok Nagar football stadium stands today, and once you see it you start noticing the same thing all over the city. Three of Bengaluru's sports grounds (football, hockey, and the KGA golf course) sit on 1954 tanks.

We tried to be strict about honesty. Every number on screen is computed from a file in the repo. The app says "drawn on the 1954 compilation" and never "held water in 1954", because an old map can copy even older sources. It never tells anyone their house will flood. We dropped two cities that failed alignment checks instead of shipping them.

All of it is built on public sources: US Army Map Service scans via UT Austin PCL (public domain), MOD Foundation's lost-lakes layer, KGIS/BBMP flood lists via OpenCity, OpenFreeMap/OpenStreetMap, and AWS Terrain Tiles.


Link to your project

https://github.com/Arham-Begani/Kere


What are you sharing?

A video of it in action (or a screen recording)
Close-up / detail shots (wiring, labels, sketches, UI)


Screenshots / videos of your project

docs/screenshots/i_real_data_stadium_1954.png
docs/screenshots/a_stadium_2026.png
docs/screenshots/b_stadium_1954_click.png
docs/screenshots/c_city_flood_on.png
docs/screenshots/d_scoreboard.png
docs/screenshots/e_fence.png


Links to additional media about your project

[Drive link to demo video]


Preferred attribution

Arham Begani, github.com/Arham-Begani


Consent to be contacted

[A or B]
