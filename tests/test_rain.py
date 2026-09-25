"""pipeline/rain.py: priority-flood depression filling, and the P2 output if it exists.
Run: pytest -q. The algorithm test is a pure unit test (no network, no DEM fetch) -- it hand-
verifies that filling finds the true lowest escape route across the whole grid, not just the
nearest or highest border cell.
"""
import json, os, sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
from rain import DISCLAIMER, priority_flood  # noqa: E402

OUT = os.path.join(ROOT, "app", "data")


def test_fully_enclosed_basin_fills_to_the_rim():
    dem = np.array([
        [5, 5, 5, 5, 5],
        [5, 1, 1, 1, 5],
        [5, 1, 0, 1, 5],
        [5, 1, 1, 1, 5],
        [5, 5, 5, 5, 5],
    ], dtype=float)
    filled = priority_flood(dem)
    assert np.array_equal(filled[0, :], dem[0, :]), "border cells must never be raised"
    assert filled[2, 2] == 5.0, "a basin ringed everywhere by 5 must fill to 5, not stay at 0"
    assert np.all(filled[1:4, 1:4] == 5.0)


def test_water_escapes_through_the_lowest_spillway_not_the_nearest_edge():
    # same basin, but the west border has one low notch (2) instead of 5: water should rise
    # only to the notch's height (the true spill point), not to the surrounding rim of 5
    dem = np.array([
        [5, 5, 5, 5, 5],
        [5, 1, 1, 1, 5],
        [2, 1, 0, 1, 5],
        [5, 1, 1, 1, 5],
        [5, 5, 5, 5, 5],
    ], dtype=float)
    filled = priority_flood(dem)
    assert filled[2, 2] == 2.0, f"center should fill only to the 2-height spillway, got {filled[2,2]}"
    assert np.all(filled[1:4, 1:4] == 2.0)
    assert filled[2, 0] == 2.0, "the spillway cell itself is a border cell and must be untouched"


def test_a_cell_already_on_a_drainage_path_is_never_raised():
    dem = np.array([[5, 4, 3], [4, 3, 2], [3, 2, 1]], dtype=float)  # monotonic slope to one corner
    filled = priority_flood(dem)
    assert np.array_equal(filled, dem), "a DEM with no closed depressions must be returned unchanged"


def test_disclaimer_never_reads_as_a_flood_prediction():
    assert "not a flood prediction" in DISCLAIMER
    assert "pool" in DISCLAIMER.lower()


def test_output_if_generated():
    if not os.path.exists(os.path.join(OUT, "rain.json")):
        import pytest
        pytest.skip("app/data/rain.json not generated yet: run pipeline/rain.py (needs network)")
    meta = json.load(open(os.path.join(OUT, "rain.json")))
    assert meta["corner_order"] == "TL,TR,BR,BL"
    tl, tr, br, bl = meta["corners"]
    assert tl[0] < tr[0] and tl[1] > bl[1]
    assert meta["disclaimer"] == DISCLAIMER
    assert meta["max_depth_m"] >= 0
    assert os.path.exists(os.path.join(OUT, "rain_depth.png"))
