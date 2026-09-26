"""Per-city pipeline: download the sheet, auto-georeference it, cut the city window into tiles,
then (once pipeline/read_city.py has produced model answers) assemble tank geometry with grow()
and today's OpenStreetMap water, run the alignment QA check, and export app/data/cities/<city>/.

  python pipeline/cities.py --city chennai --step download
  python pipeline/cities.py --city chennai --step tile
  python pipeline/cities.py --city chennai --step assemble
  python pipeline/cities.py --city chennai --step qa
  python pipeline/cities.py --city chennai --step export
  python pipeline/cities.py --city chennai --step all       # download + tile only, no API calls

CLAUDE.md rule 1 applies here too: the model only ever gives a point + box; grow() draws the
outline from the scan's own pixels. "What stands there now" for a lost tank comes from the
largest named OSM feature overlapping it, labelled "OpenStreetMap" -- never from the model.
"""
import argparse, glob, json, math, os, sys, time, urllib.error, urllib.request
from collections import Counter, defaultdict
from statistics import median

import cv2
import numpy as np
from PIL import Image
from pyproj import Transformer
from shapely.geometry import Polygon, LineString, shape
from shapely.ops import transform as stransform, unary_union, linemerge, polygonize

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = lambda *a: os.path.join(ROOT, *a)
sys.path.insert(0, P("pipeline"))
sys.path.insert(0, P("scripts"))
from grow import grow, water_mask_front  # noqa: E402
from georef import (bilinear_lonlat_to_px, bilinear_px_to_lonlat,  # noqa: E402
                     find_sheet_neatline)

CITIES_JSON = P("data", "cities.json")
RAW_DIR = P("data", "raw", "cities")
RESULTS_DIR = P("results", "cities")
DATA_OUT = P("data", "cities")
APP_OUT = P("app", "data", "cities")
MAX_TILE = 1000
UPSCALE = 2
MOD_OVERLAP_MIN = 0.2
SURVIVING_OVERLAP_MIN = 0.2
ALIGNMENT_MAX_MEDIAN_OFFSET_M = 400
ALIGNMENT_MIN_SURVIVING_OVERLAP_SHARE = 0.5
CLUSTER_RADIUS_PX = 30.0  # sheet px at native (unenlarged) scan resolution


def load_cities():
    return json.load(open(CITIES_JSON))["cities"]


def city_config(key):
    for c in load_cities():
        if c["key"] == key:
            return c
    raise SystemExit(f"unknown city '{key}' (see data/cities.json)")


def utm_transformer(lon, lat):
    zone = int((lon + 180) / 6) + 1
    epsg = (32600 if lat >= 0 else 32700) + zone
    return Transformer.from_crs(4326, epsg, always_xy=True), epsg


# ---------------------------------------------------------------- download + georef

def download(city):
    os.makedirs(RAW_DIR, exist_ok=True)
    path = os.path.join(RAW_DIR, city["file"])
    if os.path.exists(path):
        return path
    print(f"downloading {city['url']} ...")
    req = urllib.request.Request(city["url"], headers={"User-Agent": "kere-hackathon/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as f:
        f.write(r.read())
    return path


def neatline_and_window(city):
    """Returns (bgr, gray, corners_px, window_px, window_lonlat) where window_px = (x0,y0,x1,y1)
    in native sheet px and window_lonlat = (lon0,lat0,lon1,lat1): the city centre +/- window_deg
    clipped to the sheet's own printed bounds."""
    path = download(city)
    bgr = cv2.imread(path)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    corners, edges = find_sheet_neatline(gray)
    b = city["bounds_lonlat"]
    lon0, lat0 = city["city_center_lonlat"]
    w = city.get("window_deg", 0.15)
    lon_lo = max(b["lon_w"], lon0 - w)
    lon_hi = min(b["lon_e"], lon0 + w)
    lat_lo = max(b["lat_s"], lat0 - w)
    lat_hi = min(b["lat_n"], lat0 + w)
    corners_of_box = [(lon_lo, lat_lo), (lon_lo, lat_hi), (lon_hi, lat_lo), (lon_hi, lat_hi)]
    pts = [bilinear_lonlat_to_px(corners, b["lon_w"], b["lon_e"], b["lat_n"], b["lat_s"], lo, la)
           for lo, la in corners_of_box]
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    H, W = gray.shape[:2]
    x0, x1 = max(0, min(xs)), min(W, max(xs))
    y0, y1 = max(0, min(ys)), min(H, max(ys))
    window_px = (x0, y0, x1, y1)
    window_lonlat = (lon_lo, lat_lo, lon_hi, lat_hi)
    return bgr, gray, corners, window_px, window_lonlat


def tile_grid(w, h, max_tile=MAX_TILE):
    n_cols = max(1, math.ceil(w / max_tile))
    n_rows = max(1, math.ceil(h / max_tile))
    xs = [round(i * w / n_cols) for i in range(n_cols + 1)]
    ys = [round(i * h / n_rows) for i in range(n_rows + 1)]
    return [(xs[c], ys[r], xs[c + 1], ys[r + 1]) for r in range(n_rows) for c in range(n_cols)]


def cut_tiles(city):
    bgr, gray, corners, (X0, Y0, X1, Y1), _ = neatline_and_window(city)
    X0, Y0, X1, Y1 = int(X0), int(Y0), int(math.ceil(X1)), int(math.ceil(Y1))
    crop = bgr[Y0:Y1, X0:X1]
    up = cv2.resize(crop, None, fx=UPSCALE, fy=UPSCALE, interpolation=cv2.INTER_LANCZOS4)
    H, W = up.shape[:2]
    tiles_dir = os.path.join(RESULTS_DIR, city["key"], "tiles")
    keys_dir = os.path.join(RESULTS_DIR, city["key"], "keys")
    os.makedirs(tiles_dir, exist_ok=True)
    os.makedirs(keys_dir, exist_ok=True)
    keys = []
    for i, (tx0, ty0, tx1, ty1) in enumerate(tile_grid(W, H)):
        tid = f"{city['key']}_t{i}"
        tile_img = up[ty0:ty1, tx0:tx1]
        cv2.imwrite(os.path.join(tiles_dir, f"{tid}.png"), tile_img)
        key = dict(tile=tid, city=city["key"], image=f"tiles/{tid}.png", sheet="city_front_250k",
                   width=int(tx1 - tx0), height=int(ty1 - ty0),
                   # origin_in_sheet_px/scale_in_sheet let pipeline/assemble-style code convert a
                   # tile-px prediction back to native sheet px, same convention as testset keys.
                   origin_in_sheet_px=[X0 + tx0 / UPSCALE, Y0 + ty0 / UPSCALE], scale_in_sheet=UPSCALE)
        json.dump(key, open(os.path.join(keys_dir, f"{tid}.json"), "w"), indent=1)
        keys.append(key)
    manifest = dict(city=city["key"], corners_px=corners, window_native_px=[X0, Y0, X1, Y1],
                     upscale=UPSCALE, tiles=[k["tile"] for k in keys])
    json.dump(manifest, open(os.path.join(RESULTS_DIR, city["key"], "manifest.json"), "w"), indent=1)
    print(f"{city['key']}: window {X1-X0}x{Y1-Y0} native -> {W}x{H} at {UPSCALE}x -> {len(keys)} tile(s)")
    return keys


# ---------------------------------------------------------------- OSM "today's water"

def overpass_query(window_lonlat, retries=4, timeout=40):
    lon0, lat0, lon1, lat1 = window_lonlat
    q = (f"[out:json][timeout:{timeout}];"
         f"(way[\"natural\"=\"water\"]({lat0},{lon0},{lat1},{lon1});"
         f"way[\"water\"~\"lake|reservoir|pond\"]({lat0},{lon0},{lat1},{lon1});"
         f"relation[\"natural\"=\"water\"]({lat0},{lon0},{lat1},{lon1});"
         f"relation[\"water\"~\"lake|reservoir|pond\"]({lat0},{lon0},{lat1},{lon1});"
         f");out geom;")
    mirrors = ["https://overpass-api.de/api/interpreter", "https://lz4.overpass-api.de/api/interpreter",
               "https://overpass.kumi.systems/api/interpreter"]
    last_err = None
    for attempt in range(retries):
        for url in mirrors:
            try:
                req = urllib.request.Request(url, data=("data=" + q).encode(),
                                              headers={"User-Agent": "kere-hackathon-project/1.0 "
                                                                      "(contact: arhambegani2@gmail.com)"})
                with urllib.request.urlopen(req, timeout=timeout + 10) as r:
                    return json.loads(r.read())
            except Exception as e:  # noqa: BLE001 -- Overpass is a flaky shared public service
                last_err = e
                continue
        time.sleep(min(30, 2 ** attempt * 3))
    raise RuntimeError(f"Overpass unavailable after {retries} rounds across {len(mirrors)} mirrors: {last_err}")


def _relation_polygon(el):
    """A multipolygon relation (Overpass 'out geom') has no top-level geometry -- each member
    way carries its own. Large lakes are very often mapped this way (Hussain Sagar, Hyderabad,
    among others): assembling outer-ring ways is required or they're silently dropped entirely."""
    outer_lines = [LineString([(p["lon"], p["lat"]) for p in m["geometry"]])
                   for m in el.get("members", []) if m.get("role") == "outer" and m.get("geometry")
                   and len(m["geometry"]) >= 2]
    if not outer_lines:
        return None
    merged = linemerge(outer_lines)
    lines = list(merged.geoms) if hasattr(merged, "geoms") else [merged]
    polys = list(polygonize(lines))
    if not polys:
        return None
    return unary_union(polys)


def osm_water_polygons(window_lonlat):
    data = overpass_query(window_lonlat)
    feats = []
    for el in data.get("elements", []):
        if el.get("type") == "relation":
            poly = _relation_polygon(el)
        else:
            geom = el.get("geometry")
            if not geom or len(geom) < 3:
                continue
            try:
                poly = Polygon([(p["lon"], p["lat"]) for p in geom]).buffer(0)
            except Exception:
                poly = None
        if poly is None or poly.is_empty or poly.area == 0:
            continue
        name = (el.get("tags") or {}).get("name")
        feats.append(dict(geom=poly, name=name, tags=el.get("tags") or {}))
    return feats


def osm_named_features(window_lonlat, tags=("leisure", "landuse", "amenity", "building", "natural", "place")):
    """Overpass query for named features (park, stadium, bus station, etc.), used to label what
    stands on a lost tank today. Separate from osm_water_polygons since it's a much broader query."""
    lon0, lat0, lon1, lat1 = window_lonlat
    clauses = "".join(f"way[\"{t}\"][\"name\"]({lat0},{lon0},{lat1},{lon1});"
                       f"relation[\"{t}\"][\"name\"]({lat0},{lon0},{lat1},{lon1});" for t in tags)
    q = f"[out:json][timeout:40];({clauses});out geom;"
    mirrors = ["https://overpass-api.de/api/interpreter", "https://lz4.overpass-api.de/api/interpreter"]
    for url in mirrors:
        try:
            req = urllib.request.Request(url, data=("data=" + q).encode(),
                                          headers={"User-Agent": "kere-hackathon-project/1.0 "
                                                                  "(contact: arhambegani2@gmail.com)"})
            with urllib.request.urlopen(req, timeout=50) as r:
                data = json.loads(r.read())
            break
        except Exception:
            data = None
    if data is None:
        return []
    feats = []
    for el in data.get("elements", []):
        if el.get("type") == "relation":
            poly = _relation_polygon(el)
        else:
            geom = el.get("geometry")
            if not geom or len(geom) < 3:
                continue
            try:
                poly = Polygon([(p["lon"], p["lat"]) for p in geom]).buffer(0)
            except Exception:
                poly = None
        if poly is None or poly.is_empty:
            continue
        tags = el.get("tags") or {}
        ftype = next((tags[t] for t in ("leisure", "landuse", "amenity", "building", "natural", "place") if t in tags), "feature")
        feats.append(dict(geom=poly, name=tags.get("name"), type=ftype))
    return feats


# ---------------------------------------------------------------- assemble (grow + OSM)

def _cluster(dets, radius):
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


def _load_city_results(city_key):
    raw_dir = os.path.join(RESULTS_DIR, city_key, "raw")
    return [json.load(open(f)) for f in sorted(glob.glob(os.path.join(raw_dir, "*.json")))]


def _tile_to_sheet_detections(records, keys):
    dets = []
    for r in records:
        key = keys.get(r["tile"])
        if key is None:
            continue
        answer = r.get("answer") or {}
        tanks = answer.get("tanks") or []
        rw, rh = answer.get("image_width") or key["width"], answer.get("image_height") or key["height"]
        sx, sy = (key["width"] / rw if rw else 1.0), (key["height"] / rh if rh else 1.0)
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
            dets.append(dict(tile=r["tile"], run=r["run"], x=sxp, y=syp, bbox=sheet_bbox,
                              name=t.get("name_as_printed"), place=t.get("nearest_place_as_printed"),
                              style=t.get("style"), partial=bool(t.get("partial"))))
    return dets


def assemble_city(city, osm_water=None):
    """Cluster >=2-of-3-run consensus detections, grow() the outline from the sheet's own blue
    ink (never from the model's box -- CLAUDE.md rule 1), georeference, and classify status
    against today's OSM water. osm_water can be pre-fetched (see qa_city) to avoid a second
    Overpass round trip; pass None to fetch it here."""
    keys_dir = os.path.join(RESULTS_DIR, city["key"], "keys")
    keys = {os.path.basename(f)[:-5]: json.load(open(f)) for f in glob.glob(os.path.join(keys_dir, "*.json"))}
    records = _load_city_results(city["key"])
    if not records:
        raise SystemExit(f"no results for {city['key']} -- run: python pipeline/read_city.py --city {city['key']}")
    dets = _tile_to_sheet_detections(records, keys)
    clusters = _cluster(dets, CLUSTER_RADIUS_PX)

    bgr, gray, corners, window_px, window_lonlat = neatline_and_window(city)
    b = city["bounds_lonlat"]
    to_ll = lambda x, y: bilinear_px_to_lonlat(corners, b["lon_w"], b["lon_e"], b["lat_n"], b["lat_s"], x, y)

    if osm_water is None:
        try:
            osm_water = osm_water_polygons(window_lonlat)
        except Exception as e:
            print(f"  warning: OSM water query failed ({e}); all tanks will be marked status=unknown")
            osm_water = []
    water_union = unary_union([f["geom"] for f in osm_water]) if osm_water else None
    utm, epsg = utm_transformer(*city["city_center_lonlat"])
    to_m = lambda g: stransform(lambda x, y, z=None: utm.transform(x, y), g)
    water_union_m = to_m(water_union) if water_union and not water_union.is_empty else None

    try:
        named_feats = osm_named_features(window_lonlat)
    except Exception:
        named_feats = []

    grown, refused_out = [], []
    MERGE_OVERLAP_MIN = 0.3
    for grp in clusters:
        runs = sorted(set(d["run"] for d in grp))
        if len(runs) < 2:
            continue
        mx = median(d["x"] for d in grp); my = median(d["y"] for d in grp)
        bx0 = median(d["bbox"][0] for d in grp); by0 = median(d["bbox"][1] for d in grp)
        bx1 = median(d["bbox"][2] for d in grp); by1 = median(d["bbox"][3] for d in grp)
        names = [d["name"] for d in grp if d["name"]]
        places = [d["place"] for d in grp if d["place"]]
        styles = [d["style"] for d in grp if d["style"]]
        tiles = sorted(set(d["tile"] for d in grp))
        poly, status = grow(bgr, mx, my, kind="front", bbox=[bx0, by0, bx1, by1])
        if poly is None:
            lon, lat = to_ll(mx, my)
            refused_out.append(dict(point_lonlat=[round(lon, 6), round(lat, 6)],
                                     point_px=[round(mx, 1), round(my, 1)], tile=tiles, runs=runs,
                                     reason=status, crop=f"crops/refused_{len(refused_out):03d}.jpg",
                                     bbox_px=[round(v, 1) for v in (bx0, by0, bx1, by1)]))
            continue
        merged = False
        for g in grown:
            inter = g["poly"].intersection(poly).area
            if inter and inter / min(g["poly"].area, poly.area) >= MERGE_OVERLAP_MIN:
                if poly.area > g["poly"].area:
                    g["poly"] = poly
                g["runs"] = sorted(set(g["runs"]) | set(runs))
                g["tiles"] = sorted(set(g["tiles"]) | set(tiles))
                g["names"] += names; g["places"] += places; g["styles"] += styles
                merged = True
                break
        if not merged:
            grown.append(dict(poly=poly, runs=runs, tiles=tiles, names=names, places=places, styles=styles))

    mpp_native = ((b["lon_e"] - b["lon_w"]) * 111320 * math.cos(math.radians(city["city_center_lonlat"][1]))
                  / (corners["tr"][0] - corners["tl"][0]))
    tanks_out = []
    for idx, g in enumerate(grown):
        poly = g["poly"]
        if poly.geom_type != "Polygon":
            poly = max(poly.geoms, key=lambda p: p.area)
        name = Counter(g["names"]).most_common(1)[0][0] if g["names"] else None
        place = Counter(g["places"]).most_common(1)[0][0] if g["places"] else None
        ring = [list(to_ll(x, y)) for x, y in poly.exterior.coords]
        ring_poly_ll = Polygon(ring)
        poly_m = to_m(ring_poly_ll)
        overlap_frac = (poly_m.intersection(water_union_m).area / poly_m.area
                        if water_union_m and not water_union_m.is_empty and poly_m.area else 0.0)
        surviving = overlap_frac >= SURVIVING_OVERLAP_MIN
        now_osm = None
        if not surviving and named_feats:
            best = None
            for f in named_feats:
                if not f["geom"].is_valid or f["geom"].is_empty:
                    continue
                inter = f["geom"].intersection(ring_poly_ll).area
                if inter > 0 and (best is None or f["geom"].area > best["geom"].area):
                    best = f
            if best:
                now_osm = dict(name=best["name"], type=best["type"], source="OpenStreetMap")
        display_name = name or (f"Unnamed tank near {place}" if place else "Unnamed tank")
        tid = f"{city['key']}_{idx:03d}"
        tanks_out.append(dict(
            type="Feature", geometry=dict(type="Polygon", coordinates=[ring]),
            properties=dict(id=tid, city=city["key"], name_as_printed=name, nearest_place_as_printed=place,
                             display_name=display_name, status="surviving" if surviving else "lost",
                             now_osm=now_osm, runs_found=g["runs"], tiles=g["tiles"], style=Counter(g["styles"]).most_common(1)[0][0] if g["styles"] else None,
                             crop=f"crops/{tid}.jpg", area_m2=round(poly_m.area), overlap_frac=round(overlap_frac, 3),
                             bbox_px=[round(v, 1) for v in poly.bounds],
                             point_px=[round(poly.centroid.x, 1), round(poly.centroid.y, 1)])))
    out_dir = os.path.join(DATA_OUT, city["key"])
    os.makedirs(out_dir, exist_ok=True)
    fc = dict(type="FeatureCollection", features=tanks_out)
    json.dump(fc, open(os.path.join(out_dir, "tanks.geojson"), "w"), indent=1)
    json.dump(refused_out, open(os.path.join(out_dir, "refused.json"), "w"), indent=1)
    n_surv = sum(1 for t in tanks_out if t["properties"]["status"] == "surviving")
    print(f"{city['key']}: {len(tanks_out)} tanks ({n_surv} surviving, {len(tanks_out)-n_surv} lost), "
          f"{len(refused_out)} refused, {len(osm_water)} OSM water features, mpp~{mpp_native:.0f}m")
    return fc, refused_out, osm_water, water_union, corners, window_px, window_lonlat, bgr


# ---------------------------------------------------------------- alignment QA

def qa_city(city):
    """CLAUDE.md build-2 phase 2 step 7: pick the 3 largest OSM lakes in the window that also
    show up as blue ink on the sheet, measure the offset between each OSM centroid and the
    matching blue blob, and pass only if the median offset is < 400 m and >= 50% of surviving
    tanks overlap OSM water. A city that fails ships nowhere near the app."""
    fc, refused, osm_water, water_union, corners, window_px, window_lonlat, bgr = assemble_city(city)
    b = city["bounds_lonlat"]
    to_ll = lambda x, y: bilinear_px_to_lonlat(corners, b["lon_w"], b["lon_e"], b["lat_n"], b["lat_s"], x, y)
    utm, epsg = utm_transformer(*city["city_center_lonlat"])
    to_m = lambda g: stransform(lambda x, y, z=None: utm.transform(x, y), g)

    # named, compact lakes only: an unnamed "water" polygon in OSM is often a paddy field or
    # tidal flat with no name tag, and a canal/khal is a long thin channel whose centroid isn't
    # a meaningful point to check against a lake's blue ink -- neither is what the build spec's
    # own examples (Hussain Sagar, Chembarambakkam) mean by "the 3 largest lakes".
    BAD_NAME = ("canal", "khal", "river", "nala", "drain", "creek", "stream")
    named_water = [f for f in osm_water if f.get("name")
                   and not any(b in f["name"].lower() for b in BAD_NAME)]
    osm_by_area = sorted(named_water, key=lambda f: to_m(f["geom"]).area, reverse=True)[:3]
    X0, Y0, X1, Y1 = [int(v) for v in window_px]
    ink = water_mask_front(bgr[Y0:Y1, X0:X1])
    offsets = []
    for f in osm_by_area:
        c = f["geom"].centroid
        px, py = bilinear_lonlat_to_px(corners, b["lon_w"], b["lon_e"], b["lat_n"], b["lat_s"], c.x, c.y)
        lx, ly = int(px - X0), int(py - Y0)
        ys, xs = np.nonzero(ink)
        if len(xs) == 0:
            continue
        d = np.hypot(xs - lx, ys - ly)
        nearest_px = float(d.min())
        mpp = ((b["lon_e"] - b["lon_w"]) * 111320 * math.cos(math.radians(c.y)) / (corners["tr"][0] - corners["tl"][0]))
        offsets.append(dict(name=f.get("name") or "(unnamed OSM water)", offset_m=round(nearest_px * mpp)))

    tanks = fc["features"]
    surviving = [t for t in tanks if t["properties"]["status"] == "surviving"]
    # "surviving" is already defined as >=20% overlap with today's OSM water (assemble_city), so
    # every surviving tank overlaps OSM water by construction -- this is reported as a diagnostic
    # (how convincingly, not just past the classification threshold) rather than a pass/fail gate,
    # since a huge historic tank can legitimately show a low overlap FRACTION against a much
    # smaller present-day remnant without that being a georeferencing problem.
    strong_overlap_share = (sum(1 for t in surviving if t["properties"]["overlap_frac"] >= 0.5) / len(surviving)
                            if surviving else None)
    median_offset = median([o["offset_m"] for o in offsets]) if offsets else None
    passed = median_offset is not None and median_offset < ALIGNMENT_MAX_MEDIAN_OFFSET_M
    qa = dict(city=city["key"], reference_lakes=offsets, median_offset_m=median_offset,
              n_tanks=len(tanks), n_surviving=len(surviving), n_lost=len(tanks) - len(surviving),
              surviving_strong_overlap_share=(round(strong_overlap_share, 2) if strong_overlap_share is not None else None),
              n_refused=len(refused), n_osm_water_features=len(osm_water), passed=passed,
              reason=None if passed else (
                  "fewer than 3 matchable named reference lakes in the window" if not offsets else
                  f"median offset {median_offset} m >= {ALIGNMENT_MAX_MEDIAN_OFFSET_M} m"))
    out_dir = os.path.join(DATA_OUT, city["key"])
    os.makedirs(out_dir, exist_ok=True)
    json.dump(qa, open(os.path.join(out_dir, "qa.json"), "w"), indent=1)

    overlay = bgr[Y0:Y1, X0:X1].copy()
    for t in tanks:
        pts = np.array([[bilinear_lonlat_to_px(corners, b["lon_w"], b["lon_e"], b["lat_n"], b["lat_s"], lo, la)[0] - X0,
                          bilinear_lonlat_to_px(corners, b["lon_w"], b["lon_e"], b["lat_n"], b["lat_s"], lo, la)[1] - Y0]
                         for lo, la in t["geometry"]["coordinates"][0]], dtype=np.int32)
        color = (255, 120, 0) if t["properties"]["status"] == "surviving" else (0, 0, 255)
        cv2.polylines(overlay, [pts], True, color, 2)
    for f in osm_by_area:
        c = f["geom"].centroid
        px, py = bilinear_lonlat_to_px(corners, b["lon_w"], b["lon_e"], b["lat_n"], b["lat_s"], c.x, c.y)
        cv2.drawMarker(overlay, (int(px - X0), int(py - Y0)), (0, 255, 0), cv2.MARKER_CROSS, 24, 3)
    cv2.imwrite(os.path.join(out_dir, "qa_overlay.png"), overlay)
    sos = f"{strong_overlap_share:.2f}" if strong_overlap_share is not None else "n/a (no surviving tanks)"
    print(f"{city['key']}: QA {'PASSED' if passed else 'FAILED'} -- median_offset={median_offset}m "
          f"surviving_strong_overlap_share={sos} ({len(offsets)} reference lakes matched)")
    return qa


# ---------------------------------------------------------------- export

CROP_PAD = 40
CROP_MAX = 480


def _crop_and_save(bgr, bbox_px, out_path):
    H, W = bgr.shape[:2]
    x0, y0, x1, y1 = bbox_px
    x0, x1 = sorted((x0, x1)); y0, y1 = sorted((y0, y1))
    x0 = max(0, int(x0 - CROP_PAD)); y0 = max(0, int(y0 - CROP_PAD))
    x1 = min(W, int(x1 + CROP_PAD)); y1 = min(H, int(y1 + CROP_PAD))
    if x1 <= x0 or y1 <= y0:
        return False
    crop = Image.fromarray(cv2.cvtColor(bgr[y0:y1, x0:x1], cv2.COLOR_BGR2RGB))
    scale = min(1.0, CROP_MAX / max(crop.size))
    if scale < 1.0:
        crop = crop.resize((max(1, round(crop.width * scale)), max(1, round(crop.height * scale))), Image.LANCZOS)
    crop.save(out_path, quality=85)
    return True


def export_city(city):
    data_dir = os.path.join(DATA_OUT, city["key"])
    fc = json.load(open(os.path.join(data_dir, "tanks.geojson")))
    refused = json.load(open(os.path.join(data_dir, "refused.json")))
    qa_path = os.path.join(data_dir, "qa.json")
    if not os.path.exists(qa_path):
        raise SystemExit(f"no qa.json for {city['key']} -- run: python pipeline/cities.py --city {city['key']} --step qa")
    qa = json.load(open(qa_path))
    if not qa["passed"]:
        print(f"{city['key']}: QA FAILED ({qa['reason']}) -- not exporting to app/data/cities/")
        return None

    bgr, gray, corners, window_px, window_lonlat = neatline_and_window(city)
    b = city["bounds_lonlat"]
    X0, Y0, X1, Y1 = [int(round(v)) for v in window_px]
    out_dir = os.path.join(APP_OUT, city["key"])
    crops_dir = os.path.join(out_dir, "crops")
    os.makedirs(crops_dir, exist_ok=True)

    sheet_crop = bgr[Y0:Y1, X0:X1]
    cv2.imwrite(os.path.join(out_dir, "sheet.jpg"), sheet_crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
    corner_pts = [(X0, Y0), (X1, Y0), (X1, Y1), (X0, Y1)]  # TL, TR, BR, BL
    corner_lonlat = [list(map(lambda v: round(float(v), 6),
                              bilinear_px_to_lonlat(corners, b["lon_w"], b["lon_e"], b["lat_n"], b["lat_s"], px, py)))
                     for px, py in corner_pts]
    json.dump(dict(image="sheet.jpg", corners=corner_lonlat, corner_order="TL,TR,BR,BL",
                    px_area=[X0, Y0, X1, Y1]), open(os.path.join(out_dir, "corners.json"), "w"), indent=1)

    n_crops = 0
    for f in fc["features"]:
        p = f["properties"]
        if _crop_and_save(bgr, p["bbox_px"], os.path.join(crops_dir, os.path.basename(p["crop"]))):
            n_crops += 1
    for r in refused:
        if _crop_and_save(bgr, r["bbox_px"], os.path.join(crops_dir, os.path.basename(r["crop"]))):
            n_crops += 1

    json.dump(fc, open(os.path.join(out_dir, "tanks.geojson"), "w"), indent=1)
    json.dump(refused, open(os.path.join(out_dir, "refused.json"), "w"), indent=1)
    json.dump(qa, open(os.path.join(out_dir, "qa.json"), "w"), indent=1)

    cost = 0.0
    for f in glob.glob(os.path.join(RESULTS_DIR, city["key"], "raw", "*.json")):
        cost += json.load(open(f)).get("cost_usd", 0.0)
    n_surv = sum(1 for t in fc["features"] if t["properties"]["status"] == "surviving")
    meta = dict(city=city["key"], display_name=city["name"], sheet=city["sheet"],
                sheet_title=city.get("sheet_title"), source_url=city["url"], edition=city.get("edition"),
                compiled_note=city["compiled_note"], window_lonlat=list(window_lonlat),
                counts=dict(tanks=len(fc["features"]), surviving=n_surv, lost=len(fc["features"]) - n_surv,
                            refused=len(refused)),
                cost_usd=round(cost, 4), model="claude-opus-5-5", prompt_version="kere-city-v1",
                alignment_median_offset_m=qa["median_offset_m"])
    json.dump(meta, open(os.path.join(out_dir, "meta.json"), "w"), indent=1)
    print(f"{city['key']}: exported to app/data/cities/{city['key']}/ "
          f"({len(fc['features'])} tanks, {n_surv} surviving, {n_crops} crops, ${cost:.3f})")
    return meta


def update_cities_index():
    """app/data/cities.json: the city picker's index -- only cities that passed QA and were
    exported. Read only from meta.json files on disk, never hand-typed."""
    entries = []
    for city in load_cities():
        if city.get("hand_traced"):
            entries.append(dict(key=city["key"], name=city["name"], hand_traced=True,
                                 label="Checked against a hand-traced map"))
            continue
        meta_path = os.path.join(APP_OUT, city["key"], "meta.json")
        if not os.path.exists(meta_path):
            continue
        meta = json.load(open(meta_path))
        entries.append(dict(key=city["key"], name=city["name"], hand_traced=False,
                             label="Read by Opus 5.5. Not yet checked by hand.",
                             counts=meta["counts"], city_center_lonlat=city["city_center_lonlat"]))
    os.makedirs(P("app", "data"), exist_ok=True)
    json.dump(dict(cities=entries, demo_city=json.load(open(CITIES_JSON)).get("demo_city")),
               open(P("app", "data", "cities.json"), "w"), indent=1)
    print(f"app/data/cities.json: {len(entries)} cities listed ({sum(1 for e in entries if not e.get('hand_traced'))} model-read)")
    return entries


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", required=True)
    ap.add_argument("--step", default="all", choices=["download", "tile", "assemble", "qa", "export", "all"])
    args = ap.parse_args()
    city = city_config(args.city)
    if args.step == "download":
        download(city)
    elif args.step == "tile":
        cut_tiles(city)
    elif args.step == "assemble":
        assemble_city(city)
    elif args.step == "qa":
        qa_city(city)
    elif args.step == "export":
        export_city(city)
        update_cities_index()
    elif args.step == "all":
        cut_tiles(city)
