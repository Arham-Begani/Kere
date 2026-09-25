# Kere map-reading test: scoreboard

Mean ± sd over runs. Plan = 16 tiles of the 1:25,000 city plan (18 tanks). Front = 1 tile of the 1:250,000 sheet (16 verified tanks).

| metric | claude-opus-5-5 | claude-opus-5 |
|---|---|---|
| Plan: unique tanks found (of 18) | 18.0 ± 0.0 | 18.0 ± 0.0 |
| Plan: recall per tile | 98% ± 2 | 98% ± 2 |
| Plan: invented tanks per run | 4.0 ± 1.0 | 3.7 ± 1.5 |
| Plan: precision | 90% ± 2 | 90% ± 4 |
| Plan: printed names read exactly | 88% ± 0 | 88% ± 0 |
| Plan: names given that are not printed on the tile | 2.0 ± 0.0 | 2.0 ± 0.0 |
| Plan: extent (box IoU with the drawn tank) | 86% ± 0 | 69% ± 1 |
| Front: verified tanks found | 90% ± 4 | 52% ± 4 |
| Front: invented (no blue ink) | 1.0 ± 1.0 | 11.0 ± 1.0 |
| Front: on blue ink but unverified | 19.0 ± 5.2 | 5.3 ± 1.2 |
| Cost, all runs (USD) | 1.2 | 1.74 |
| Mean latency per call (s) | 9.8 | 14.2 |
