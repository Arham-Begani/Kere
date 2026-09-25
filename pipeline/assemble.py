"""Turn saved model answers into georeferenced tank geometry.

The model only ever gives a point and a box (eval/prompt.py). This script:
  1. converts every predicted point/box from tile px to sheet px,
  2. clusters points per sheet across overlapping tiles and runs,
  3. keeps a cluster only if >=2 of 3 runs agree (consensus),
  4. runs grow() (pipeline/grow.py) on the SCAN's own pixels to get the outline
     -- the model never draws the shape, the pixels do (CLAUDE.md rule 1),
  5. georeferences the outline, matches it to MOD Foundation's layer, and
  6. writes app/data/tanks_<model>.geojson and app/data/refused_<model>.json.

  python pipeline/assemble.py --model claude-opus-5-5
  python pipeline/assemble.py --model claude-opus-5 --results results_standin
"""
import argparse, glob, json, os, sys
from collections import Counter, defaultdict
from statistics import median

import cv2
import numpy as np
from PIL import Image
from pyproj import Transformer
from shapely.geometry import Polygon
from shapely.ops import transform as stransform, unary_union

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = lambda *a: os.path.join(ROOT, *a)
sys.path.insert(0, P("pipeline"))
sys.path.insert(0, P("scripts"))
from grow import grow  # noqa: E402
from georef import front_px_to_lonlat  # noqa: E402
from build_testset import load_mod  # noqa: E402

TESTSET = P("testset")
CLUSTER_RADIUS_PX = {"plan_25k": 45.0, "front_250k": 6.0}   # sheet px; see CLAUDE.md P0.1
SHEET_MPP = {"plan_25k": 4.0, "front_250k": 37.7}            # metres per sheet px (unenlarged scan)
REDATED_YEARS = {"1854", "1870", "1897"}
MOD_OVERLAP_MIN = 0.2          # match a tank to a MOD record if >= 20% of the smaller area overlaps
SURVIVING_OVERLAP_MIN = 0.2    # a tank is "surviving" if >= 20% of it overlaps MOD's existing-lakes layer

UTM = Transformer.from_crs(4326, 32643, always_xy=True)
to_m = lambda g: stransform(lambda x, y, z=None: UTM.transform(x, y), g)


def load_keys():
    manifest = json.load(open(os.path.join(TESTSET, "manifest.json")))
    return {t["tile"]: json.load(open(os.path.join(TESTSET, t["key"]))) for t in manifest["tiles"]}


def load_results(results_dir, model):
    out = []
    for f in sorted(glob.glob(os.path.join(ROOT, results_dir, "raw", model, "*.json"))):
        out.append(json.load(open(f)))
    return out


def tile_to_sheet_detections(records, keys):
    """Every predicted tank across every tile/run, converted to sheet px."""
    dets = []
    for r in records:
        key = keys.get(r["tile"])
        if key is None:
            continue
        answer = r.get("answer") or {}
        tanks = answer.get("tanks") or []
        rw, rh = answer.get("image_width") or key["width"], answer.get("image_height") or key["height"]
        sx, sy = key["width"] / rw if rw else 1.0, key["height"] / rh if rh else 1.0
        ox, oy = key["origin_in_sheet_px"]
        scale = key["scale_in_sheet"]
        for t in tanks:
            tx, ty = float(t["x"]) * sx, float(t["y"]) * sy
            sxp, syp = ox + tx / scale, oy + ty / scale
            bbox = t.get("bbox") or [tx, ty, tx, ty]
            bx0, by0 = float(bbox[0]) * sx, float(bbox[1]) * sy
            bx1, by1 = float(bbox[2]) * sx, float(bbox[3]) * sy
            bx0, bx1 = sorted((bx0, bx1)); by0, by1 = sorted((by0, by1))
            sheet_bbox = [ox + bx0 / scale, oy + by0 / scale, ox + bx1 / scale, oy + by1 / scale]
            dets.append(dict(sheet=key["sheet"], tile=r["tile"], run=r["run"], x=sxp, y=syp,
                              bbox=sheet_bbox, name=t.get("name_as_printed"),
                              style=t.get("style"), partial=bool(t.get("partial"))))
    return dets


def cluster(dets, radius):
    """Connected components: two detections are linked if their sheet points are within radius."""
    n = len(dets)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    for i in range(n):
        for j in range(i + 1, n):
            if (dets[i]["x"] - dets[j]["x"]) ** 2 + (dets[i]["y"] - dets[j]["y"]) ** 2 <= radius * radius:
                union(i, j)
    groups = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(dets[i])
    return list(groups.values())


def plan_px_to_lonlat(A, x, y):
    M = np.array(A)
    return np.linalg.solve(M[:2].T, np.array([x, y]) - M[2])


def polygon_to_lonlat(poly, sheet, A):
    if sheet == "plan_25k":
        ring = [list(map(float, plan_px_to_lonlat(A, x, y))) for x, y in poly.exterior.coords]
    else:
        ring = [list(map(float, front_px_to_lonlat(x, y))) for x, y in poly.exterior.coords]
    return ring


def point_to_lonlat(x, y, sheet, A):
    if sheet == "plan_25k":
        return list(map(float, plan_px_to_lonlat(A, x, y)))
    return list(map(float, front_px_to_lonlat(x, y)))


def load_mod_utm():
    feats = load_mod()  # [{layer, props, geom(lonlat)}, ...] from scripts/build_testset.py
    existing = [f for f in feats if f["layer"] == "existing"]
    out = []
    for f in feats:
        out.append(dict(layer=f["layer"], props=f["props"], geom_m=to_m(f["geom"])))
    existing_union_m = to_m(unary_union([f["geom"] for f in existing])) if existing else Polygon()
    return out, existing_union_m


def match_mod(tank_geom_lonlat, mod_utm):
    tank_m = to_m(tank_geom_lonlat)
    best = None
    for f in mod_utm:
        g = f["geom_m"]
        if not g.is_valid or g.is_empty:
            continue
        inter = g.intersection(tank_m).area
        if inter <= 0:
            continue
        score = inter / min(g.area, tank_m.area)
        if score >= MOD_OVERLAP_MIN and (best is None or score > best[0]):
            best = (score, f)
    return best


def assemble(model, results_dir, out_dir=None):
    keys = load_keys()
    records = load_results(results_dir, model)
    if not records:
        raise SystemExit(f"no results for {model} under {results_dir}/raw/{model}/*.json")
    dets = tile_to_sheet_detections(records, keys)

    georef = json.load(open(P("data", "plan_georef.json")))
    A = georef["A"]
    plan_img = np.array(Image.open(P("data", "raw", "plan_25k_autocontrast.png")).convert("L"))
    front_img = cv2.imread(P("data", "raw", "nd-44-13a_front_250k.jpg"))
    mod_utm, existing_union_m = load_mod_utm()

    tanks_out, refused_out = [], []
    MERGE_OVERLAP_MIN = 0.3  # two grown outlines that share this much area are the same tank seen twice
    for sheet in ("plan_25k", "front_250k"):
        sheet_dets = [d for d in dets if d["sheet"] == sheet]
        clusters = cluster(sheet_dets, CLUSTER_RADIUS_PX[sheet])
        grown = []  # [{poly, runs, tiles, names(list), styles(list), bboxes(list)}]
        for grp in clusters:
            runs = sorted(set(d["run"] for d in grp))
            if len(runs) < 2:
                continue
            mx = median(d["x"] for d in grp)
            my = median(d["y"] for d in grp)
            bx0 = median(d["bbox"][0] for d in grp); by0 = median(d["bbox"][1] for d in grp)
            bx1 = median(d["bbox"][2] for d in grp); by1 = median(d["bbox"][3] for d in grp)
            names = [d["name"] for d in grp if d["name"]]
            styles = [d["style"] for d in grp if d["style"]]
            tiles = sorted(set(d["tile"] for d in grp))

            sheet_img = plan_img if sheet == "plan_25k" else front_img
            kind = "plan" if sheet == "plan_25k" else "front"
            poly, status = grow(sheet_img, mx, my, kind=kind, bbox=[bx0, by0, bx1, by1])
            if poly is None:
                refused_out.append(dict(
                    sheet=sheet, point_lonlat=point_to_lonlat(mx, my, sheet, A),
                    point_px=[round(mx, 1), round(my, 1)], tile=tiles, runs=runs,
                    reason=status, crop=f"crops/refused_{model}_{sheet}_{len(refused_out):03d}.jpg",
                    bbox_px=[round(v, 1) for v in (bx0, by0, bx1, by1)]))
                continue
            # a partial view of a tank in one tile and a full view in another tile can land
            # >radius apart and form two clusters; grow() then returns overlapping/identical
            # outlines for both, so merge by geometry (not just by point distance) before output.
            merged = False
            for g in grown:
                inter = g["poly"].intersection(poly).area
                if inter and inter / min(g["poly"].area, poly.area) >= MERGE_OVERLAP_MIN:
                    if poly.area > g["poly"].area:
                        g["poly"] = poly
                    g["runs"] = sorted(set(g["runs"]) | set(runs))
                    g["tiles"] = sorted(set(g["tiles"]) | set(tiles))
                    g["names"] += names
                    g["styles"] += styles
                    merged = True
                    break
            if not merged:
                grown.append(dict(poly=poly, runs=runs, tiles=tiles, names=names, styles=styles))

        for idx, g in enumerate(grown):
            poly = g["poly"]
            name = Counter(g["names"]).most_common(1)[0][0] if g["names"] else None
            style = Counter(g["styles"]).most_common(1)[0][0] if g["styles"] else None
            bx0, by0, bx1, by1 = poly.bounds

            ring = polygon_to_lonlat(poly, sheet, A)
            match = match_mod(Polygon(ring), mod_utm)
            mod_name = mod_last_mapped = mod_current_use = None
            if match:
                p = match[1]["props"]
                mod_name, mod_last_mapped = p.get("name"), p.get("year")
                mod_current_use = p.get("current_use")
            surviving = to_m(Polygon(ring)).intersection(existing_union_m).area >= SURVIVING_OVERLAP_MIN * to_m(Polygon(ring)).area
            redated = sheet == "plan_25k" and mod_last_mapped in REDATED_YEARS

            tid = f"{model}_{('plan' if sheet == 'plan_25k' else 'front')}_{idx:03d}"
            tanks_out.append(dict(
                type="Feature", geometry=dict(type="Polygon", coordinates=[ring]),
                properties=dict(
                    id=tid, sheet=sheet, name_as_printed=name, mod_name=mod_name,
                    mod_last_mapped=mod_last_mapped, mod_current_use=mod_current_use,
                    status="surviving" if surviving else "lost", redated=redated,
                    runs_found=g["runs"], tiles=g["tiles"], crop=f"crops/{tid}.jpg",
                    area_m2=round(poly.area * SHEET_MPP[sheet] ** 2),
                    style=style, bbox_px=[round(v, 1) for v in (bx0, by0, bx1, by1)],
                    point_px=[round(poly.centroid.x, 1), round(poly.centroid.y, 1)])))

    fc = dict(type="FeatureCollection", features=tanks_out)
    out_dir = out_dir or P("app", "data")
    os.makedirs(out_dir, exist_ok=True)
    json.dump(fc, open(os.path.join(out_dir, f"tanks_{model}.geojson"), "w"), indent=1)
    json.dump(refused_out, open(os.path.join(out_dir, f"refused_{model}.json"), "w"), indent=1)
    n_plan = sum(1 for t in tanks_out if t["properties"]["sheet"] == "plan_25k")
    n_front = sum(1 for t in tanks_out if t["properties"]["sheet"] == "front_250k")
    print(f"{model}: {n_plan} plan tanks, {n_front} front tanks, {len(refused_out)} refused "
          f"(from {len(records)} result files, {len(dets)} raw detections)")
    return fc, refused_out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--results", default="results")
    args = ap.parse_args()
    assemble(args.model, args.results)


if __name__ == "__main__":
    main()
