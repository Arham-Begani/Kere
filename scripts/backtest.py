"""Flood backtest: do the city's own flood-point lists sit closer to LOST lakes than chance, and to surviving lakes?

  python scripts/backtest.py                                  # answer-key tanks (truth) + MOD's hand-traced layer
  python scripts/backtest.py --tanks app/data/tanks_opus-5-5.geojson --label "Opus 5.5 reading"

A tank is "surviving" if at least 20% of its 1954 outline overlaps a water body in MOD's existing-lakes layer
(use OSM water for cities without a MOD layer); otherwise "lost". Distances are in metres (UTM 43N).
Baseline: 10,000 uniformly random points in the same study area (fixed seed). p: one-sided binomial test.
Flood points: KGIS flood-vulnerable locations (200), flood-prone locations (70), BBMP low-lying areas (128),
all from data.opencity.in (public domain), plus the news pins in data/flood_pins.geojson (reported, not tested).
"""
import argparse, json, os, re
from math import comb

import numpy as np
from pyproj import Transformer
from shapely.geometry import Point, Polygon, shape
from shapely.ops import transform as stransform, unary_union

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = lambda *a: os.path.join(ROOT, *a)
T = Transformer.from_crs(4326, 32643, always_xy=True)
to_m = lambda g: stransform(lambda x, y, z=None: T.transform(x, y), g)
LISTS = {"KGIS flood-vulnerable": "vulnerable.kml", "flood-prone": "flood_prone.kml", "BBMP low-lying": "low_lying.kml"}


def kml_points(path):
    s = open(path, encoding="utf-8").read()
    return [Point(float(a), float(b)) for a, b in re.findall(r"<coordinates>\s*([-\d.]+),([-\d.]+)", s)]


def geoms(path):
    out = []
    for f in json.load(open(path))["features"]:
        g = shape(f["geometry"])
        g = stransform(lambda x, y, z=None: (x, y), g).buffer(0)
        if not g.is_empty:
            out.append(g)
    return out


def binom_p(k, n, p):
    return sum(comb(n, j) * p ** j * (1 - p) ** (n - j) for j in range(k, n + 1))


def study_area(name):
    gba = to_m(geoms(P("data", "mod", "gba_boundary.geojson"))[0])
    if name == "gba":
        return gba
    if name == "plan":
        A = np.array(json.load(open(P("data", "plan_georef.json")))["A"])
        px2ll = lambda x, y: np.linalg.solve(A[:2].T, np.array([x, y]) - A[2])
        foot = Polygon([T.transform(*px2ll(x, y)) for x, y in [(915, 213), (4105, 213), (4105, 3390), (915, 3390)]])
        return foot.intersection(gba)
    if name == "front":
        return Polygon([T.transform(x, y) for x, y in [(77.60, 12.88), (77.78, 12.88), (77.78, 13.0), (77.60, 13.0)]]).intersection(gba)
    raise ValueError(name)


def split_lost(tank_geoms_m, existing_m):
    lost, kept = [], []
    for g in tank_geoms_m:
        (kept if g.intersection(existing_m).area >= 0.2 * g.area else lost).append(g)
    return unary_union(lost) if lost else Polygon(), unary_union(kept) if kept else Polygon()


def run(layers, area, radii=(100, 250), n_random=10000, seed=0):
    rng = np.random.default_rng(seed)
    minx, miny, maxx, maxy = area.bounds
    rand = []
    while len(rand) < n_random:
        p = Point(rng.uniform(minx, maxx), rng.uniform(miny, maxy))
        if area.contains(p):
            rand.append(p)
    pts = []
    for fn in LISTS.values():
        pts += [to_m(p) for p in kml_points(P("data", "flood", fn))]
    pts = [p for p in pts if area.contains(p)]
    out = {"n_flood_points": len(pts), "rows": []}
    for lname, g in layers.items():
        if g.is_empty:
            continue
        rd = np.array([g.distance(p) for p in rand]); d = np.array([g.distance(p) for p in pts])
        for r in radii:
            k = int((d <= r).sum()); base = float((rd <= r).mean())
            out["rows"].append(dict(layer=lname, radius_m=r, flood_points_within=k, n=len(d), share=round(k / len(d), 3),
                                    random_share=round(base, 3), lift=round(k / len(d) / base, 2) if base else None,
                                    p_one_sided=float(f"{binom_p(k, len(d), base):.2g}")))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tanks", default=P("data", "plan_tanks.geojson"))
    ap.add_argument("--label", default="1954 plan tanks, answer key")
    ap.add_argument("--area", default="plan", choices=["plan", "front", "gba"])
    ap.add_argument("--out", default=P("data", "backtest.json"))
    args = ap.parse_args()
    existing = to_m(unary_union(geoms(P("data", "mod", "lakes_existing.geojson"))))
    area = study_area(args.area)
    lost, kept = split_lost([to_m(g) for g in geoms(args.tanks)], existing)
    mod_lost = to_m(unary_union(geoms(P("data", "mod", "lakes_lost.geojson"))))
    res = {"study_area": args.area, "area_km2": round(area.area / 1e6, 1)}
    res["this_layer"] = run({f"{args.label}: lost": lost, f"{args.label}: surviving": kept}, area)
    res["reference_MOD_hand_traced"] = run({"MOD lost lakes (1854-1969 surveys)": mod_lost.intersection(area),
                                            "MOD existing lakes": existing.intersection(area)}, area)
    json.dump(res, open(args.out, "w"), indent=1)
    print(f"study area: {args.area}, {res['area_km2']} km2, flood points inside: {res['this_layer']['n_flood_points']}")
    for block in ("this_layer", "reference_MOD_hand_traced"):
        for r in res[block]["rows"]:
            print(f"  {r['layer']:52s} <= {r['radius_m']:>3} m: {r['flood_points_within']:>3}/{r['n']} = {r['share']*100:4.0f}%"
                  f"  vs random {r['random_share']*100:4.0f}%  lift x{r['lift']}  p={r['p_one_sided']}")


if __name__ == "__main__":
    main()
