"""pipeline/export.py: corner order, output files exist, GeoJSON parses. Run: pytest -q

Runs the real exporter into a scratch app/data-like directory is impractical (it reads/writes
a fixed set of paths under app/data/ and shells out to scripts/backtest.py), so this test runs
the actual pipeline/export.py against the repo's real app/data/ (assumes pipeline/assemble.py
has already been run for both models -- tests/test_assemble.py or the P0 build step does this)
and checks its output, which is what the app actually reads.
"""
import json, os, subprocess, sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "app", "data")
_ran = False


def _ensure_export_ran():
    global _ran
    if not os.path.exists(os.path.join(OUT, "tanks_claude-opus-5-5.geojson")):
        pytest.skip("app/data/tanks_*.geojson missing: run pipeline/assemble.py for both models first")
    if not _ran:
        subprocess.run([sys.executable, os.path.join(ROOT, "pipeline", "export.py")], check=True, cwd=ROOT)
        _ran = True


def test_output_files_exist():
    _ensure_export_ran()
    for fn in ("plan_1954.jpg", "front_1954.jpg", "sheets.json", "flood_points.geojson",
               "gazetteer.json", "scoreboard.json", "backtest.json", "demo_data.json"):
        assert os.path.exists(os.path.join(OUT, fn)), f"missing {fn}"
    assert len(os.listdir(os.path.join(OUT, "crops"))) > 0, "no crops written"
    for model in ("claude-opus-5", "claude-opus-5-5"):
        for tile in ("plan_r2c2", "plan_r1c1"):
            p = os.path.join(OUT, "overlays", model, f"{tile}__run1.jpg")
            assert os.path.exists(p), f"missing overlay {p}"


def test_corner_order_is_tl_tr_br_bl():
    _ensure_export_ran()
    sheets = json.load(open(os.path.join(OUT, "sheets.json")))
    for name, meta in sheets.items():
        assert meta["corner_order"] == "TL,TR,BR,BL"
        tl, tr, br, bl = meta["corners"]
        assert tl[0] < tr[0], f"{name}: TL should be west of TR"
        assert bl[0] < br[0], f"{name}: BL should be west of BR"
        assert tl[1] > bl[1], f"{name}: TL should be north of BL"
        assert tr[1] > br[1], f"{name}: TR should be north of BR"


def test_geojson_outputs_parse():
    _ensure_export_ran()
    flood = json.load(open(os.path.join(OUT, "flood_points.geojson")))
    assert flood["type"] == "FeatureCollection"
    assert len(flood["features"]) > 0
    for f in flood["features"][:5]:
        assert f["geometry"]["type"] == "Point"
        assert "list" in f["properties"]

    gaz = json.load(open(os.path.join(OUT, "gazetteer.json")))
    assert isinstance(gaz, list) and len(gaz) > 0
    for g in gaz[:5]:
        assert {"name", "lon", "lat"} <= set(g)

    for model in ("claude-opus-5", "claude-opus-5-5"):
        fc = json.load(open(os.path.join(OUT, f"tanks_{model}.geojson")))
        assert fc["type"] == "FeatureCollection"
        refused = json.load(open(os.path.join(OUT, f"refused_{model}.json")))
        assert isinstance(refused, list)


def test_demo_data_flag_reflects_source():
    _ensure_export_ran()
    demo = json.load(open(os.path.join(OUT, "demo_data.json")))
    assert "stand_in" in demo and "note" in demo
    real_scoreboard_exists = os.path.exists(os.path.join(ROOT, "results", "scoreboard.json"))
    assert demo["stand_in"] == (not real_scoreboard_exists)


def test_backtest_numbers_present():
    _ensure_export_ran()
    bt = json.load(open(os.path.join(OUT, "backtest.json")))
    assert "this_layer" in bt and "reference_MOD_hand_traced" in bt
    assert bt["this_layer"]["rows"], "backtest produced no rows"
