"""Score saved model answers against the answer keys. Deterministic; no API calls.

  python eval/score.py                 # scores results/raw/*, writes results/scoreboard.{json,md} and overlays
  python eval/score.py --no-overlays

Rules (the same for every model):
  hit        prediction point inside a key tank's outline, grown by match_buffer_px (15 px plan, 14 px front)
  duplicate  a second prediction inside a tank already hit (not penalised, reported)
  ambiguous  prediction on a service reservoir (plan only): no credit, no penalty
  unverified front tile only: prediction on blue ink but not on a key tank (the front key is a verified subset)
  invented   anything else: a water body that is not on the map
  recall     full tanks hit / full tanks in the key (tanks cut by the tile edge are bonus, never penalised)
  names      for hit tanks whose printed label is on the tile: exact match after removing accents, case,
             spaces and a trailing "tank"; a name given for a tank with no label on the tile is "unsourced"
  extent     IoU between the model's bbox and the key tank's bounding box (hits on full tanks)
"""
import argparse, glob, json, math, os, re, statistics as st, unicodedata
from collections import defaultdict

import numpy as np
from PIL import Image, ImageDraw
from shapely.geometry import Point, Polygon

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTSET = os.path.join(ROOT, "testset")
PRICES = {"claude-opus-5": (5.0, 25.0), "claude-opus-5-5": (4.0, 20.0)}  # $ per million input / output tokens
N_PLAN_TANKS = 18


def norm(s):
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = re.sub(r"[^a-z]", "", "".join(c for c in s if not unicodedata.combining(c)).lower())
    return s[:-4] if s.endswith("tank") else s


def load_keys():
    manifest = json.load(open(os.path.join(TESTSET, "manifest.json")))
    return {t["tile"]: json.load(open(os.path.join(TESTSET, t["key"]))) for t in manifest["tiles"]}


_ink_cache = {}


def ink_share(key, x, y):
    path = os.path.join(TESTSET, key["ink_mask"])
    if path not in _ink_cache:
        _ink_cache[path] = np.array(Image.open(path)) > 0
    m = _ink_cache[path]; r = key["ink_radius_px"]
    yy, xx = np.ogrid[:m.shape[0], :m.shape[1]]
    disk = (xx - x) ** 2 + (yy - y) ** 2 <= r * r
    return float(m[disk].mean()) if disk.any() else 0.0


def score_answer(key, answer):
    """Return per-tile metrics and a labelled list of predictions."""
    preds = (answer or {}).get("tanks") or []
    W, H = key["width"], key["height"]
    rw, rh = (answer or {}).get("image_width") or W, (answer or {}).get("image_height") or H
    sx, sy = W / rw if rw else 1.0, H / rh if rh else 1.0
    buf = key["match_buffer_px"]
    truths = [(t, Polygon(t["polygon"]).buffer(buf)) for t in key["tanks"]]
    hit_by = {}
    labelled = []
    m = defaultdict(int)
    for p in preds:
        x, y = float(p["x"]) * sx, float(p["y"]) * sy
        pt = Point(x, y)
        inside = [(t, poly) for t, poly in truths if poly.contains(pt)]
        name = p.get("name_as_printed")
        if inside:
            t = min(inside, key=lambda tp: Point(tp[0]["centroid"]).distance(pt))[0]
            if t["id"] in hit_by:
                labelled.append(dict(x=x, y=y, kind="duplicate", tank=t["id"], name=name)); m["duplicates"] += 1
                continue
            hit_by[t["id"]] = p
            labelled.append(dict(x=x, y=y, kind="hit", tank=t["id"], name=name, bbox=p.get("bbox")))
            bb = p.get("bbox")
            if t["status"] == "full" and isinstance(bb, (list, tuple)) and len(bb) == 4:
                bx0, bx1 = sorted((bb[0] * sx, bb[2] * sx)); by0, by1 = sorted((bb[1] * sy, bb[3] * sy))
                tb = Polygon(t["polygon"]).bounds
                ix = max(0, min(bx1, tb[2]) - max(bx0, tb[0])) * max(0, min(by1, tb[3]) - max(by0, tb[1]))
                un = (bx1 - bx0) * (by1 - by0) + (tb[2] - tb[0]) * (tb[3] - tb[1]) - ix
                m["bbox_iou_sum"] += ix / un if un > 0 else 0.0
                m["bbox_n"] += 1
            if t.get("expected_name"):
                if t["status"] == "full":  # names are scored on full tanks only
                    if name and norm(name) == norm(t["expected_name"]):
                        m["names_correct"] += 1
                    elif name:
                        m["names_wrong"] += 1
                    else:
                        m["names_missing"] += 1
            elif name:
                m["names_unsourced"] += 1
            m["style_correct"] += int(p.get("style") == t["style"])
            continue
        amb = [a for a in key.get("ambiguous", []) if math.dist(a["center"], (x, y)) <= a["r"]]
        if amb:
            labelled.append(dict(x=x, y=y, kind="ambiguous", name=name)); m["ambiguous"] += 1
            continue
        if key.get("verified_subset_only") and ink_share(key, x, y) >= key["ink_min_share"]:
            labelled.append(dict(x=x, y=y, kind="unverified", name=name)); m["unverified"] += 1
            continue
        labelled.append(dict(x=x, y=y, kind="invented", name=name)); m["invented"] += 1
        if name:
            m["names_unsourced"] += 1
    full = [t for t in key["tanks"] if t["status"] == "full"]
    m["full_total"] = len(full)
    m["full_hit"] = sum(t["id"] in hit_by for t in full)
    m["partial_hit"] = sum(t["id"] in hit_by for t in key["tanks"] if t["status"] == "partial")
    m["names_expected"] = sum(bool(t.get("expected_name")) for t in full)
    m["predictions"] = len(preds)
    m["hits"] = len(hit_by)
    m["rescaled"] = int(abs(sx - 1) > 0.01 or abs(sy - 1) > 0.01)
    return dict(m), labelled, {tid for tid in hit_by if any(t["id"] == tid and t["status"] == "full" for t in key["tanks"])}


def draw_overlay(key, labelled, out):
    im = Image.open(os.path.join(TESTSET, key["image"])).convert("RGB")
    d = ImageDraw.Draw(im)
    for t in key["tanks"]:
        d.line([tuple(p) for p in t["polygon"]], fill=(0, 150, 0) if t["status"] == "full" else (230, 140, 0), width=3)
    for a in key.get("ambiguous", []):
        x, y = a["center"]; d.ellipse([x - a["r"], y - a["r"], x + a["r"], y + a["r"]], outline=(150, 0, 200), width=2)
    col = dict(hit=(0, 200, 0), duplicate=(0, 120, 255), ambiguous=(150, 0, 200), unverified=(230, 200, 0), invented=(255, 0, 0))
    for p in labelled:
        x, y, c = p["x"], p["y"], col[p["kind"]]
        if p["kind"] == "invented":
            d.line([(x - 12, y - 12), (x + 12, y + 12)], fill=c, width=5); d.line([(x - 12, y + 12), (x + 12, y - 12)], fill=c, width=5)
        else:
            d.ellipse([x - 9, y - 9, x + 9, y + 9], fill=c, outline=(0, 0, 0))
        bb = p.get("bbox")
        if p["kind"] == "hit" and isinstance(bb, (list, tuple)) and len(bb) == 4:
            d.rectangle([min(bb[0], bb[2]), min(bb[1], bb[3]), max(bb[0], bb[2]), max(bb[1], bb[3])], outline=(0, 200, 0), width=2)
        if p.get("name"):
            d.text((x + 12, y - 6), p["name"], fill=(200, 0, 0))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    im.save(out, quality=85)


def mean_sd(v):
    return (round(st.mean(v), 3), round(st.stdev(v), 3) if len(v) > 1 else 0.0) if v else (None, None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=os.path.join(ROOT, "results"))
    ap.add_argument("--no-overlays", action="store_true")
    args = ap.parse_args()
    keys = load_keys()
    per_run = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))  # model -> run -> metric
    found_ids = defaultdict(lambda: defaultdict(set))
    usage = defaultdict(lambda: [0, 0, 0.0, 0])
    tiles_seen = defaultdict(lambda: defaultdict(set))
    rows = []
    configs = defaultdict(set)
    for f in sorted(glob.glob(os.path.join(args.results, "raw", "*", "*.json"))):
        r = json.load(open(f))
        rq = r.get("request") or {}
        configs[r["model"]].add((rq.get("effort"), json.dumps(rq.get("thinking")), rq.get("strict_tool"), r.get("prompt_version")))
        key = keys[r["tile"]]
        m, labelled, found = score_answer(key, r.get("answer"))
        sheet = key["sheet"]
        bucket = per_run[r["model"]][(sheet, r["run"])]
        for k, v in m.items():
            bucket[k] += v
        bucket["unparsed"] += int(r.get("parse") == "unparsed")
        found_ids[r["model"]][r["run"]] |= found if sheet == "plan_25k" else set()
        tiles_seen[r["model"]][(sheet, r["run"])].add(r["tile"])
        u = usage[r["model"]]; u[0] += r["usage"]["input_tokens"]; u[1] += r["usage"]["output_tokens"]; u[2] += r["latency_s"]; u[3] += 1
        rows.append(dict(model=r["model"], tile=r["tile"], run=r["run"], **m))
        if not args.no_overlays:
            draw_overlay(key, labelled, os.path.join(args.results, "overlays", r["model"], f"{r['tile']}__run{r['run']}.jpg"))
    board = {}
    for model, runs in per_run.items():
        res = {}
        for sheet in ("plan_25k", "front_250k"):
            rr = {run: b for (s, run), b in runs.items() if s == sheet}
            if not rr:
                continue
            g = lambda fn: mean_sd([fn(b) for b in rr.values()])
            res[sheet] = dict(
                runs=len(rr), tiles_per_run=sorted({len(tiles_seen[model][(sheet, r)]) for r in rr}),
                recall=g(lambda b: b["full_hit"] / b["full_total"] if b["full_total"] else 0),
                invented_per_run=g(lambda b: b["invented"]),
                precision=g(lambda b: b["hits"] / (b["hits"] + b["invented"]) if (b["hits"] + b["invented"]) else 1.0),
                duplicates_per_run=g(lambda b: b["duplicates"]),
                names_correct_rate=g(lambda b: b["names_correct"] / b["names_expected"] if b["names_expected"] else 0),
                names_wrong_per_run=g(lambda b: b["names_wrong"]),
                names_unsourced_per_run=g(lambda b: b["names_unsourced"]),
                unverified_per_run=g(lambda b: b["unverified"]),
                unparsed_per_run=g(lambda b: b["unparsed"]),
                bbox_iou=g(lambda b: b["bbox_iou_sum"] / b["bbox_n"] if b["bbox_n"] else 0),
            )
            if sheet == "plan_25k":
                res[sheet]["unique_tanks_found_of_18"] = mean_sd([len(found_ids[model][r]) for r in rr])
        u = usage[model]; pin, pout = PRICES.get(model, (0, 0))
        res["cost_usd_total"] = round(u[0] / 1e6 * pin + u[1] / 1e6 * pout, 2)
        res["mean_latency_s"] = round(u[2] / u[3], 1) if u[3] else None
        res["mean_output_tokens"] = round(u[1] / u[3]) if u[3] else None
        board[model] = res
    os.makedirs(args.results, exist_ok=True)
    json.dump(dict(scoreboard=board, per_tile=rows), open(os.path.join(args.results, "scoreboard.json"), "w"), indent=1)
    md = ["# Kere map-reading test: scoreboard", "",
          "Mean ± sd over runs. Plan = 16 tiles of the 1:25,000 city plan (18 tanks). Front = 1 tile of the 1:250,000 sheet (16 verified tanks).", ""]
    fmt = lambda v, pct=False: "n/a" if v[0] is None else (f"{v[0]*100:.0f}% ± {v[1]*100:.0f}" if pct else f"{v[0]:.1f} ± {v[1]:.1f}")
    lines = [("Plan: unique tanks found (of 18)", "plan_25k", "unique_tanks_found_of_18", False),
             ("Plan: recall per tile", "plan_25k", "recall", True),
             ("Plan: invented tanks per run", "plan_25k", "invented_per_run", False),
             ("Plan: precision", "plan_25k", "precision", True),
             ("Plan: printed names read exactly", "plan_25k", "names_correct_rate", True),
             ("Plan: names given that are not printed on the tile", "plan_25k", "names_unsourced_per_run", False),
             ("Plan: extent (box IoU with the drawn tank)", "plan_25k", "bbox_iou", True),
             ("Front: verified tanks found", "front_250k", "recall", True),
             ("Front: invented (no blue ink)", "front_250k", "invented_per_run", False),
             ("Front: on blue ink but unverified", "front_250k", "unverified_per_run", False)]
    models = list(board)
    md.append("| metric | " + " | ".join(models) + " |")
    md.append("|---|" + "---|" * len(models))
    for label, sheet, k, pct in lines:
        md.append(f"| {label} | " + " | ".join(fmt(board[m].get(sheet, {}).get(k, (None, None)), pct) for m in models) + " |")
    md.append("| Cost, all runs (USD) | " + " | ".join(str(board[m]["cost_usd_total"]) for m in models) + " |")
    md.append("| Mean latency per call (s) | " + " | ".join(str(board[m]["mean_latency_s"]) for m in models) + " |")
    all_cfg = set().union(*configs.values()) if configs else set()
    if len(all_cfg) > 1:
        md += ["", "**Warning: the models did not all run with the same settings** (effort, thinking, strict tool, prompt version):"]
        md += [f"- {m}: {sorted(c)}" for m, c in configs.items()]
    open(os.path.join(args.results, "scoreboard.md"), "w").write("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
