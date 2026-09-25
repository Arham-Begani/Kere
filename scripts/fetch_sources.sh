#!/usr/bin/env bash
# Re-download every public source this project uses. Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/raw data/flood
# US Army Map Service, Series U502, sheet ND 44-13 "Bangalore" (compiled 1954; public domain US government work),
# scans from the Perry-Castaneda Library Map Collection, University of Texas at Austin
curl -fsSL -o data/raw/nd-44-13a_front_250k.jpg https://maps.lib.utexas.edu/maps/ams/india/nd-44-13a.jpg
curl -fsSL -o data/raw/nd-44-13b_plan_25k.jpg   https://maps.lib.utexas.edu/maps/ams/india/nd-44-13b.jpg
# Other cities on the same series (same pipeline, for the "any city" stretch):
#   Madras ND 44-10 (nd-44-10a/b), Hyderabad NE 44-9 (ne-44-09a/b), Bombay NE 43-5, Poona NE 43-6, Mysore ND 43-16
# MOD Foundation water bodies (Building a Resilient Bengaluru), via Sonia Das's bengaluru-water-map (data baked into index.html)
curl -fsSL -o data/raw/bengaluru-water-map_index.html https://raw.githubusercontent.com/soniadas123/bengaluru-water-map/HEAD/index.html
python3 - <<'PY'
import json
s = open('data/raw/bengaluru-water-map_index.html', encoding='utf-8').read()
i = s.find('const DATA = ') + len('const DATA = ')
obj, _ = json.JSONDecoder().raw_decode(s[i:])
import os; os.makedirs('data/mod', exist_ok=True)
for k, v in obj.items():
    json.dump(v, open(f'data/mod/{k}.geojson', 'w'))
print('MOD layers:', {k: len(v['features']) for k, v in obj.items()})
PY
# Flood point lists (KGIS / BBMP via OpenCity, public domain)
B=https://data.opencity.in/dataset/b03218ea-4b7c-4fa9-ab67-b9054d7ecc4c/resource
curl -fsSL -o data/flood/vulnerable.kml  $B/a7d8a01f-1fbc-41e1-85f0-f15ea16b2d27/download/6b3c63b0-f461-4e9c-a2c2-006f734c5b41.kml
curl -fsSL -o data/flood/flood_prone.kml $B/d90fe768-caba-4c6e-b6b5-a75acd5e88a9/download/00fb1229-dcfd-4f59-813f-885e0c629add.kml
curl -fsSL -o data/flood/low_lying.kml   $B/62ceac3b-f6e2-4dd1-ae9f-be80b1f2fda8/download/8e87a2fc-e014-4c6e-81f1-d5cb4db57a46.kml
echo done
