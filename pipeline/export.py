"""Export everything the static app reads from app/data/. No API calls; pure file transforms.

  python pipeline/export.py

Writes: plan_1954.jpg (+corners), front_1954.jpg (+corners), crops/<tank_id>.jpg for every
tank and every refused point in both models' geojson, flood_points.geojson, gazetteer.json,
scoreboard.json, two overlay tiles per model, backtest.json (via scripts/backtest.py), and
demo_data.json (whether the scoreboard/overlays are real eval results or stand-in answer-key
data -- the app must show a red "DEMO DATA" banner whenever this is true, CLAUDE.md rule).

Reuses: pipeline/assemble.py's affine inversion for the plan sheet, scripts/georef.py's
front_px_to_lonlat for the front sheet, scripts/build_testset.py's PLAN_MAP_AREA constant.
Never invents a name or a number: gazetteer/flood names come only from source properties.
"""
import glob, json, os, re, shutil, subprocess, sys

import cv2
import numpy as np
from PIL import Image
from shapely.geometry import shape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = lambda *a: os.path.join(ROOT, *a)
sys.path.insert(0, P("pipeline"))
sys.path.insert(0, P("scripts"))
from assemble import plan_px_to_lonlat  # noqa: E402
from georef import front_px_to_lonlat  # noqa: E402
from build_testset import PLAN_MAP_AREA  # noqa: E402

OUT = P("app", "data")
FRONT_WINDOW = (463, 275, 1400, 760)  # px on the raw front scan; the neatline window CLAUDE.md specifies
SEPIA = np.array([0x70, 0x42, 0x14], dtype=np.float32)  # #704214, RGB order (PIL)
SEPIA_ALPHA = 0.35
CROP_PAD = 40
CROP_MAX = 480
KML_LISTS = {"vulnerable.kml": "KGIS flood-vulnerable", "flood_prone.kml": "flood-prone", "low_lying.kml": "BBMP low-lying"}
MODELS = ["claude-opus-5", "claude-opus-5-5"]
OVERLAY_TILES = ["plan_r2c2", "plan_r1c1"]


def ensure_out():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(os.path.join(OUT, "crops"), exist_ok=True)
    os.makedirs(os.path.join(OUT, "overlays"), exist_ok=True)


def export_plan_sheet():
    x0, y0, x1, y1 = PLAN_MAP_AREA
    gray = Image.open(P("data", "raw", "plan_25k_autocontrast.png")).convert("L").crop((x0, y0, x1, y1))
    rgb = np.array(gray.convert("RGB")).astype(np.float32)
    multiply = rgb * SEPIA[None, None, :] / 255.0
    tinted = rgb * (1 - SEPIA_ALPHA) + multiply * SEPIA_ALPHA
    im = Image.fromarray(np.clip(tinted, 0, 255).astype(np.uint8))
    w = 2400
    h = round(im.height * w / im.width)
    im = im.resize((w, h), Image.LANCZOS)
    im.save(os.path.join(OUT, "plan_1954.jpg"), quality=82)
    A = json.load(open(P("data", "plan_georef.json")))["A"]
    corners = [plan_px_to_lonlat(A, px, py) for px, py in [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]]
    return dict(image="plan_1954.jpg", corners=[[round(float(v), 6) for v in c] for c in corners],
                corner_order="TL,TR,BR,BL", px_area=[x0, y0, x1, y1])


def export_front_sheet():
    im_bgr = cv2.imread(P("data", "raw", "nd-44-13a_front_250k.jpg"))
    x0, y0, x1, y1 = FRONT_WINDOW
    crop = im_bgr[y0:y1, x0:x1]
    cv2.imwrite(os.path.join(OUT, "front_1954.jpg"), crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
    corners = [front_px_to_lonlat(px, py) for px, py in [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]]
    return dict(image="front_1954.jpg", corners=[[round(float(v), 6) for v in c] for c in corners],
                corner_order="TL,TR,BR,BL", px_area=[x0, y0, x1, y1])


def _crop_and_save(sheet, bbox_px, out_path):
    if sheet == "plan_25k":
        src = np.array(Image.open(P("data", "raw", "plan_25k_autocontrast.png")).convert("RGB"))
    else:
        src = cv2.cvtColor(cv2.imread(P("data", "raw", "nd-44-13a_front_250k.jpg")), cv2.COLOR_BGR2RGB)
    H, W = src.shape[:2]
    x0, y0, x1, y1 = bbox_px
    x0, x1 = sorted((x0, x1)); y0, y1 = sorted((y0, y1))
    x0 = max(0, int(x0 - CROP_PAD)); y0 = max(0, int(y0 - CROP_PAD))
    x1 = min(W, int(x1 + CROP_PAD)); y1 = min(H, int(y1 + CROP_PAD))
    if x1 <= x0 or y1 <= y0:
        return False
    crop = Image.fromarray(src[y0:y1, x0:x1])
    scale = min(1.0, CROP_MAX / max(crop.size))
    if scale < 1.0:
        crop = crop.resize((max(1, round(crop.width * scale)), max(1, round(crop.height * scale))), Image.LANCZOS)
    crop.save(out_path, quality=85)
    return True


def export_crops():
    n = 0
    for model in MODELS:
        fc = json.load(open(os.path.join(OUT, f"tanks_{model}.geojson")))
        for f in fc["features"]:
            p = f["properties"]
            if _crop_and_save(p["sheet"], p["bbox_px"], os.path.join(OUT, "crops", os.path.basename(p["crop"]))):
                n += 1
        refused = json.load(open(os.path.join(OUT, f"refused_{model}.json")))
        for r in refused:
            if _crop_and_save(r["sheet"], r["bbox_px"], os.path.join(OUT, "crops", os.path.basename(r["crop"]))):
                n += 1
    return n


def kml_placemarks(path):
    s = open(path, encoding="utf-8").read()
    out = []
    for pm in re.findall(r"<Placemark[^>]*>(.*?)</Placemark>", s, re.S):
        coord = re.search(r"<coordinates>\s*([-\d.]+),([-\d.]+)", pm)
        if not coord:
            continue
        name = None
        m = re.search(r"<name>(.*?)</name>", pm, re.S)
        if m:
            name = m.group(1).strip() or None
        else:
            m = re.search(r'<SimpleData name="LocationName">(.*?)</SimpleData>', pm, re.S)
            if m:
                name = m.group(1).strip() or None
        out.append((float(coord.group(1)), float(coord.group(2)), name))
    return out


def export_flood_points():
    features = []
    for fn, listname in KML_LISTS.items():
        for lon, lat, name in kml_placemarks(P("data", "flood", fn)):
            features.append(dict(type="Feature", geometry=dict(type="Point", coordinates=[lon, lat]),
                                  properties=dict(list=listname, name=name)))
    pins = json.load(open(P("data", "flood_pins.geojson")))
    for f in pins["features"]:
        p = f["properties"]
        features.append(dict(type="Feature", geometry=f["geometry"],
                              properties=dict(list="news", name=p["locality"], date=p.get("date"),
                                               source=p.get("source"))))
    fc = dict(type="FeatureCollection", features=features)
    json.dump(fc, open(os.path.join(OUT, "flood_points.geojson"), "w"), indent=1)
    return len(features)


def export_gazetteer():
    seen, out = set(), []

    def add(name, lon, lat):
        if not name:
            return
        key = name.strip().lower()
        if key in seen:
            return
        seen.add(key)
        out.append(dict(name=name.strip(), lon=round(float(lon), 6), lat=round(float(lat), 6)))

    for fn in KML_LISTS:
        for lon, lat, name in kml_placemarks(P("data", "flood", fn)):
            add(name, lon, lat)
    pins = json.load(open(P("data", "flood_pins.geojson")))
    for f in pins["features"]:
        lon, lat = f["geometry"]["coordinates"]
        add(f["properties"]["locality"], lon, lat)
    wards = json.load(open(P("data", "mod", "gba_wards.geojson")))
    for f in wards["features"]:
        name = f["properties"].get("ward_name")
        if not name:
            continue
        display = re.sub(r"^\d+\s*-\s*", "", name).strip()
        c = shape(f["geometry"]).centroid
        add(display, c.x, c.y)
    json.dump(out, open(os.path.join(OUT, "gazetteer.json"), "w"), indent=1)
    return len(out)


def hand_traced_column():
    """The answer key as a scoreboard column, in the same shape as a model's entry, so the app
    can treat Opus 5 / Opus 5.5 / hand-traced uniformly and every number still comes from a file
    (testset/, data/plan_tanks.geojson), never a literal typed into the UI."""
    plan_tanks = json.load(open(P("data", "plan_tanks.geojson")))["features"]
    front_key = json.load(open(P("testset", "keys", "front_se.json")))
    zero = [0, 0.0]
    one = [1.0, 0.0]
    return dict(
        plan_25k=dict(runs=1, tiles_per_run=[16], recall=one, invented_per_run=zero, precision=one,
                      duplicates_per_run=zero, names_correct_rate=one,  # every printed name IS the source
                      names_wrong_per_run=zero, names_unsourced_per_run=zero, unverified_per_run=zero,
                      unparsed_per_run=zero, bbox_iou=one, unique_tanks_found_of_18=[len(plan_tanks), 0.0]),
        front_250k=dict(runs=1, tiles_per_run=[1], recall=one, invented_per_run=zero, precision=one,
                        duplicates_per_run=zero, names_correct_rate=zero, names_wrong_per_run=zero,
                        names_unsourced_per_run=zero, unverified_per_run=zero, unparsed_per_run=zero,
                        bbox_iou=one, unique_tanks_found_of_18=[len(front_key["tanks"]), 0.0]),
        cost_usd_total=0, mean_latency_s=None, mean_output_tokens=None,
        note="Hand-traced from the scan's own pixels (scripts/build_testset.py), checked by eye -- the answer key, not a model.")


def export_scoreboard_and_overlays():
    real = os.path.exists(P("results", "scoreboard.json"))
    src_root = P("results") if real else P("results_standin")
    board = json.load(open(os.path.join(src_root, "scoreboard.json")))
    board["scoreboard"]["hand-traced (answer key)"] = hand_traced_column()
    json.dump(board, open(os.path.join(OUT, "scoreboard.json"), "w"), indent=1)
    shutil.copyfile(P("data", "plan_georef.json"), os.path.join(OUT, "plan_georef.json"))
    for model in MODELS:
        os.makedirs(os.path.join(OUT, "overlays", model), exist_ok=True)
        for tile in OVERLAY_TILES:
            fn = f"{tile}__run1.jpg"
            src = os.path.join(src_root, "overlays", model, fn)
            if os.path.exists(src):
                shutil.copyfile(src, os.path.join(OUT, "overlays", model, fn))
    note = ("DEMO DATA: answer key, not model output" if not real else
            "Real Opus 5 / Opus 5.5 eval results")
    json.dump(dict(stand_in=not real, note=note), open(os.path.join(OUT, "demo_data.json"), "w"), indent=1)
    return real


def export_backtest():
    subprocess.run([sys.executable, P("scripts", "backtest.py"),
                     "--tanks", os.path.join(OUT, "tanks_claude-opus-5-5.geojson"),
                     "--label", "Opus 5.5 reading", "--area", "plan",
                     "--out", os.path.join(OUT, "backtest.json")], check=True, cwd=ROOT)


def main():
    ensure_out()
    plan_meta = export_plan_sheet()
    front_meta = export_front_sheet()
    json.dump(dict(plan=plan_meta, front=front_meta), open(os.path.join(OUT, "sheets.json"), "w"), indent=1)
    n_crops = export_crops()
    n_flood = export_flood_points()
    n_gaz = export_gazetteer()
    real = export_scoreboard_and_overlays()
    export_backtest()
    print(f"plan_1954.jpg + front_1954.jpg written (corners: {plan_meta['corner_order']})")
    print(f"{n_crops} crops written")
    print(f"{n_flood} flood points, {n_gaz} gazetteer entries")
    print(f"scoreboard/overlays source: {'results/ (real)' if real else 'results_standin/ (DEMO DATA)'}")
    print("backtest.json written")


if __name__ == "__main__":
    main()
