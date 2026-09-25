"""Check the scorer with fake answers whose correct scores are known in advance. No API key needed.
  python eval/selftest.py"""
import json, os, random, shutil, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(__file__))
from score import load_keys, score_answer, norm
from shapely.geometry import Point, Polygon

keys = load_keys()
random.seed(7)

def empty_point(key):
    polys = [Polygon(t["polygon"]).buffer(key["match_buffer_px"] + 40) for t in key["tanks"]]
    for _ in range(10000):
        x, y = random.uniform(20, key["width"] - 20), random.uniform(20, key["height"] - 20)
        if all(not p.contains(Point(x, y)) for p in polys) and all(((x - a["center"][0]) ** 2 + (y - a["center"][1]) ** 2) ** .5 > a["r"] + 20 for a in key.get("ambiguous", [])):
            if key.get("verified_subset_only"):
                from score import ink_share
                if ink_share(key, x, y) > 0:
                    continue
            return x, y
    raise RuntimeError("no empty point")

fails = 0
def check(cond, msg):
    global fails
    if not cond:
        fails += 1; print("FAIL:", msg)

# 1. perfect answers: every tank, inside point, printed name when the label is on the tile
tot_full = tot_hit = 0
for tid, key in keys.items():
    ans = dict(image_width=key["width"], image_height=key["height"], tanks=[
        dict(x=t["inside_point"][0], y=t["inside_point"][1], bbox=list(Polygon(t["polygon"]).bounds), name_as_printed=t.get("expected_name"), style=t["style"], partial=t["status"] == "partial")
        for t in key["tanks"]])
    m, lab, found = score_answer(key, ans)
    if m.get("bbox_n"):
        check(abs(m["bbox_iou_sum"] / m["bbox_n"] - 1) < 1e-6, f"{tid}: perfect boxes should have IoU 1")
    check(m["full_hit"] == m["full_total"], f"{tid}: perfect answer should hit every full tank ({m['full_hit']}/{m['full_total']})")
    check(m.get("invented", 0) == 0 and m.get("duplicates", 0) == 0, f"{tid}: perfect answer should have no invented/duplicates {m}")
    check(m.get("names_correct", 0) == m["names_expected"], f"{tid}: names {m.get('names_correct',0)}/{m['names_expected']}")
    check(m.get("names_unsourced", 0) == 0, f"{tid}: no unsourced names expected")
    tot_full += m["full_total"]; tot_hit += m["full_hit"]
print(f"perfect answers: {tot_hit}/{tot_full} full tanks hit across {len(keys)} tiles")

# 2. a model that misses some tanks, invents some, repeats one, and names unlabelled tanks from memory
for tid, key in keys.items():
    full = [t for t in key["tanks"] if t["status"] == "full"]
    keep = full[: max(0, len(full) - 1)]  # miss the last full tank
    preds = [dict(x=t["inside_point"][0], y=t["inside_point"][1], name_as_printed=t.get("expected_name") or "Memory Kere", style="mixed", partial=False) for t in keep]
    if keep:
        preds.append(dict(x=keep[0]["inside_point"][0] + 1, y=keep[0]["inside_point"][1], name_as_printed=None, style="mixed", partial=False))  # duplicate
    for _ in range(2):
        x, y = empty_point(key)
        preds.append(dict(x=x, y=y, name_as_printed=None, style="solid", partial=False))  # invented
    m, lab, found = score_answer(key, dict(image_width=key["width"], image_height=key["height"], tanks=preds))
    check(m["full_hit"] == len(keep), f"{tid}: expected {len(keep)} hits, got {m['full_hit']}")
    check(m.get("invented", 0) == 2, f"{tid}: expected 2 invented, got {m.get('invented',0)}")
    check(m.get("duplicates", 0) == (1 if keep else 0), f"{tid}: duplicates {m.get('duplicates',0)}")
    exp_unsourced = sum(1 for t in keep if not t.get("expected_name"))
    check(m.get("names_unsourced", 0) == exp_unsourced, f"{tid}: unsourced names expected {exp_unsourced}, got {m.get('names_unsourced',0)}")
print("imperfect answers: counts match construction")

# 3. a model that saw a half-size image: coordinates must be rescaled
key = keys["plan_r1c3"]
ans = dict(image_width=key["width"] // 2, image_height=key["height"] // 2, tanks=[
    dict(x=t["inside_point"][0] / 2, y=t["inside_point"][1] / 2, name_as_printed=None, style="solid", partial=False) for t in key["tanks"]])
m, _, _ = score_answer(key, ans)
check(m["full_hit"] == m["full_total"] and m["rescaled"] == 1, f"rescale: {m}")
print("rescaling: ok")

# 4. name normalisation
check(norm("Halsūr Tank") == norm("halsur") == norm("HALSUR TANK"), "diacritics/case/'tank' suffix")
check(norm("Shūle Tank") != norm("Shoolay Tank"), "a modern spelling is not the printed name")
print("name normalisation: ok")

# 5. end to end: fake result files -> score.py -> scoreboard
tmp = tempfile.mkdtemp()
for model, drop in [("claude-opus-5", 2), ("claude-opus-5-5", 0)]:
    for run in (1, 2):
        for tid, key in keys.items():
            full = [t for t in key["tanks"] if t["status"] == "full"]
            ts = full[: max(0, len(full) - drop)]
            ans = dict(image_width=key["width"], image_height=key["height"], tanks=[dict(x=t["inside_point"][0], y=t["inside_point"][1], name_as_printed=t.get("expected_name"), style=t["style"], partial=False) for t in ts])
            os.makedirs(f"{tmp}/raw/{model}", exist_ok=True)
            json.dump(dict(model=model, tile=tid, run=run, answer=ans, parse="tool_use", usage=dict(input_tokens=2000, output_tokens=3000), latency_s=10.0),
                      open(f"{tmp}/raw/{model}/{tid}__run{run}.json", "w"))
out = subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "score.py"), "--results", tmp, "--no-overlays"], capture_output=True, text=True)
check(out.returncode == 0, "score.py failed: " + out.stderr[-500:])
b = json.load(open(f"{tmp}/scoreboard.json"))["scoreboard"]
check(b["claude-opus-5-5"]["plan_25k"]["unique_tanks_found_of_18"][0] == 18, f"fake 5.5 should find 18 unique tanks: {b['claude-opus-5-5']['plan_25k']}")
check(b["claude-opus-5"]["plan_25k"]["recall"][0] < 1, "fake Opus 5 dropped tanks, recall must be < 1")
print(out.stdout)
shutil.rmtree(tmp)
print("SELFTEST", "PASSED" if fails == 0 else f"FAILED ({fails})")
sys.exit(1 if fails else 0)
