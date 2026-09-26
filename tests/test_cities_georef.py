import json, os, sys
import numpy as np
import pytest
import cv2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from georef import bilinear_lonlat_to_px, bilinear_px_to_lonlat, find_sheet_neatline

CITIES = json.load(open(os.path.join(ROOT, "data", "cities.json")))["cities"]
CITIES = [c for c in CITIES if not c.get("hand_traced")]


def test_bilinear_round_trip_on_skewed_quad():
    # a mildly skewed, non-axis-aligned quad, unlike the identity case front_lonlat_to_px covers
    corners = {"tl": (100, 80), "tr": (900, 60), "bl": (120, 700), "br": (880, 720)}
    lon_w, lon_e, lat_n, lat_s = 10.0, 11.5, 20.0, 19.0
    for lon, lat in [(10.2, 19.8), (11.3, 19.1), (10.75, 19.5)]:
        x, y = bilinear_lonlat_to_px(corners, lon_w, lon_e, lat_n, lat_s, lon, lat)
        lo, la = bilinear_px_to_lonlat(corners, lon_w, lon_e, lat_n, lat_s, x, y)
        assert abs(lo - lon) < 1e-6 and abs(la - lat) < 1e-6
    # corners map back onto themselves
    for k, (lon, lat) in {"tl": (lon_w, lat_n), "tr": (lon_e, lat_n),
                           "bl": (lon_w, lat_s), "br": (lon_e, lat_s)}.items():
        x, y = bilinear_lonlat_to_px(corners, lon_w, lon_e, lat_n, lat_s, lon, lat)
        assert abs(x - corners[k][0]) < 1e-6 and abs(y - corners[k][1]) < 1e-6


@pytest.mark.parametrize("city", CITIES, ids=[c["key"] for c in CITIES])
def test_city_neatline_detection_is_sane(city):
    path = os.path.join(ROOT, "data", "raw", "cities", city["file"])
    if not os.path.exists(path):
        pytest.skip(f"{city['file']} not downloaded (run pipeline/cities.py download)")
    gray = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    corners, edges = find_sheet_neatline(gray)
    # a rectangle: top above bottom, left of right
    assert edges["top_y"] < edges["bot_y"]
    assert edges["left_x"] < edges["right_x"]
    # every U502 sheet is 1.5deg lon x 1deg lat; width/height in px should reflect that ratio
    # (not exactly 1.5, since these are Transverse Mercator, but not wildly off either)
    w_px = edges["right_x"] - edges["left_x"]
    h_px = edges["bot_y"] - edges["top_y"]
    ratio = w_px / h_px
    assert 1.2 < ratio < 1.9, f"unexpected aspect ratio {ratio:.2f} for {city['key']}"
    # the neatline shouldn't be a sliver hugging one edge of the scan (a real detection failure)
    H, W = gray.shape[:2]
    assert w_px > 0.7 * W and h_px > 0.7 * H


@pytest.mark.parametrize("city", CITIES, ids=[c["key"] for c in CITIES])
def test_city_center_projects_inside_or_near_sheet(city):
    path = os.path.join(ROOT, "data", "raw", "cities", city["file"])
    if not os.path.exists(path):
        pytest.skip(f"{city['file']} not downloaded (run pipeline/cities.py download)")
    gray = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    corners, edges = find_sheet_neatline(gray)
    b = city["bounds_lonlat"]
    lon, lat = city["city_center_lonlat"]
    x, y = bilinear_lonlat_to_px(corners, b["lon_w"], b["lon_e"], b["lat_n"], b["lat_s"], lon, lat)
    H, W = gray.shape[:2]
    pad = 0.05 * max(W, H)  # Mumbai's centre sits just outside its sheet's north edge
    assert -pad <= x <= W + pad and -pad <= y <= H + pad
