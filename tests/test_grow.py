"""The fence: outlines come from pixels, and points with no water drawing are refused. Run: pytest -q"""
import json, os, sys
import numpy as np
from PIL import Image
from shapely.geometry import Polygon
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
from grow import grow

G = np.array(Image.open(os.path.join(ROOT, "data", "raw", "plan_25k_autocontrast.png")))


def key_tanks():
    seen = {}
    for r in range(4):
        for c in range(4):
            k = json.load(open(os.path.join(ROOT, "testset", "keys", f"plan_r{r}c{c}.json")))
            ox, oy = k["origin_in_sheet_px"]
            for t in k["tanks"]:
                if t["status"] == "full" and t["id"] not in seen:
                    seen[t["id"]] = (Polygon([(a + ox, b + oy) for a, b in t["polygon"]]), (t["inside_point"][0] + ox, t["inside_point"][1] + oy))
    return seen


def test_outlines_match_the_answer_key():
    ious = {}
    for tid, (truth, (x, y)) in key_tanks().items():
        poly, msg = grow(G, x, y, "plan", list(truth.bounds))
        ious[tid] = poly.intersection(truth).area / poly.union(truth).area if poly else 0.0
    big = {k: v for k, v in ious.items() if k != "P04"}  # P04 is a 0.3 ha pond; refused by design (see SMALL_AREA)
    assert np.mean(list(big.values())) >= 0.72, ious
    assert min(big.values()) >= 0.35, ious


def test_fence_refuses_things_that_are_not_water():
    for x, y, bb, what in [(2500, 1700, [2470, 1670, 2530, 1730], "dark built-up shading"),
                           (2279, 1590, [2270, 1582, 2287, 1598], "service reservoir building"),
                           (2750, 2167, [2715, 2158, 2794, 2177], "the label 'Mud Tank'"),
                           (2200, 1650, [2150, 1620, 2250, 1680], "racecourse edge"),
                           (3500, 1000, [3450, 950, 3550, 1050], "blank countryside"),
                           (3000, 1400, [2950, 1350, 3050, 1450], "built-up shading")]:
        poly, msg = grow(G, x, y, "plan", bb)
        assert poly is None, f"{what} was accepted as water"
